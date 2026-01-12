from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from pathlib import Path
import os
import json
import shutil
from datetime import datetime
from openai import OpenAI
from config import settings
from pydub import AudioSegment
import math
import traceback
import time
import requests
from urllib.parse import urlparse
import httpx
from openai import InternalServerError, APITimeoutError
import database



timeout = httpx.Timeout(
    connect=120.0,
    read=1800.0,
    write=600.0,
    pool=60.0
)

# Initialize Database
database.init_db()

# FastAPI app
app = FastAPI(
    title="Audio Transcription API",
    description="Transcribe audio with diarization using OpenAI gpt-4o-transcribe-diarize",
    version="4.0.0"
)

# OpenAI client
client = OpenAI(
    api_key=settings.openai_api_key,
    timeout=timeout
)

# Ensure output folder exists
settings.output_folder.mkdir(exist_ok=True)

# Max duration for chunking (20 minutes recommended < 23 min)
MAX_CHUNK_DURATION_MS = 20 * 60 * 1000


# Request model for URL-based transcription
class TranscribeURLRequest(BaseModel):
    audio_url: str
    save_files: bool = True  # Whether to save output files or just return the transcript


def safe_transcribe(client, **kwargs):
    """
    Retry wrapper for OpenAI transcription API.
    Retries on InternalServerError or connection resets.
    """
    max_retries = 5
    base_delay = 3  # seconds

    for attempt in range(1, max_retries + 1):
        try:
            return client.audio.transcriptions.create(**kwargs)

        except (InternalServerError, APITimeoutError) as e:
            print(f"[OpenAI ERROR] Attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                raise
            time.sleep(base_delay * attempt)  # exponential backoff

        except Exception as e:
            # If it's a connection reset or upstream disconnect
            msg = str(e).lower()
            if "connect error" in msg or "disconnect" in msg or "reset" in msg:
                print(f"[NETWORK ERROR] Attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    raise
                time.sleep(base_delay * attempt)
            else:
                raise  # real fatal error → do not retry


# Helper: Convert seconds to HH:MM:SS format
def format_timestamp(seconds: float) -> str:
    """Convert seconds to HH:MM:SS format."""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


# Helper: Load prompt from file
def load_prompt() -> str:
    """Load the formatting prompt from prompt.md file."""
    prompt_path = Path(__file__).parent / "prompt.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: prompt.md not found at {prompt_path}")
        return ""
    except Exception as e:
        print(f"Warning: Error loading prompt.md: {e}")
        return ""


# Helper: Load MoM prompt from file
def load_mom_prompt() -> str:
    """Load the MoM formatting prompt from mom_prompt.md file."""
    prompt_path = Path(__file__).parent / "mom_prompt.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: mom_prompt.md not found at {prompt_path}")
        return ""
    except Exception as e:
        print(f"Warning: Error loading mom_prompt.md: {e}")
        return ""


# Helper: Parse VTT transcript from Teams
def parse_vtt_transcript(vtt_content: str) -> list:
    """
    Robust parser for Microsoft Teams VTT transcripts.
    Supports <v Speaker>text</v> and ignores cue IDs.
    """
    utterances = []
    lines = vtt_content.splitlines()
    i = 0

    # Regex to extract speakers in <v Name> format
    import re
    speaker_tag = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.DOTALL)

    while i < len(lines):
        line = lines[i].strip()

        # Skip cue ID lines (Teams uses GUID/NN)
        if re.match(r'^[A-Za-z0-9\-]+\/\d+-\d+$', line):
            i += 1
            continue

        # Timestamp line
        if "-->" in line:
            try:
                start_ts, end_ts = line.split("-->")
                start_seconds = _timestamp_to_seconds(start_ts.strip())
                end_seconds = _timestamp_to_seconds(end_ts.strip())
            except:
                i += 1
                continue

            # Next line should contain <v Speaker> text
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()

                # Match <v Speaker>sentence</v>
                m = speaker_tag.search(next_line)
                if m:
                    speaker = m.group(1).strip()
                    text = m.group(2).strip()

                    utterances.append({
                        "speaker": speaker,
                        "text": text,
                        "start": start_seconds,
                        "end": end_seconds
                    })

                    i += 2
                    continue

        i += 1

    return utterances


def _timestamp_to_seconds(timestamp: str) -> float:
    """
    Convert VTT timestamp (HH:MM:SS.mmm) to seconds.
    
    Args:
        timestamp: String like "00:01:23.456"
    
    Returns:
        Float seconds
    """
    parts = timestamp.split(':')
    hours = int(parts[0])
    minutes = int(parts[1])
    seconds = float(parts[2])
    
    return hours * 3600 + minutes * 60 + seconds


# Helper: Format transcript with LLM
def format_transcript_with_llm(utterances: list, participants: str = None) -> str:
    """
    Use LLM to format transcript professionally using instructions from prompt.md.
    Uses chunking to avoid output token limits.
    """
    if not settings.enable_llm_formatting:
        return "\n".join([
            f"[{format_timestamp(u['start'])}] {u['speaker']}: {u['text']}"
            for u in utterances
        ])
    
    # Load base prompt
    prompt_instructions = load_prompt()
    if not prompt_instructions:
        print("Warning: Using simple format due to prompt loading failure")
        fallback = "\n".join([
            f"[{format_timestamp(u['start'])}] {u['speaker']}: {u['text']}"
            for u in utterances
        ])
        return fallback, ""  # Return empty summary as second part
    
    # Calculate metadata
    current_date = datetime.now().strftime("%B %d, %Y")
    if utterances:
        total_duration_seconds = max(u['end'] for u in utterances)
        hours = int(total_duration_seconds // 3600)
        minutes = int((total_duration_seconds % 3600) // 60)
        duration_str = f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}" if hours > 0 else f"{minutes} minute{'s' if minutes != 1 else ''}"
        unique_speakers = sorted(set(u['speaker'] for u in utterances))
        participants_str = ", ".join(unique_speakers)
    else:
        duration_str, participants_str = "Unknown", "Unknown"

    # --- Phase 1: Format Conversation Chunks ---
    formatted_conversation_parts = []
    chunk_size = 50  # Process 50 segments at a time
    total_chunks = math.ceil(len(utterances) / chunk_size)
    
    print(f"Formatting transcript in {total_chunks} chunks...")

    for i in range(total_chunks):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, len(utterances))
        current_chunk = utterances[start_idx:end_idx]
        
        print(f"Processing chunk {i+1}/{total_chunks}...")

        # Prepare context from previous chunk (last 3 items)
        context_str = ""
        if i > 0:
            prev_chunk = utterances[start_idx-3:start_idx]
            context_items = "\n".join([f"{u['speaker']}: {u['text']}" for u in prev_chunk])
            context_str = f"\n\nCONTEXT FROM PREVIOUS CHUNK (DO NOT REPEAT, JUST FOR CONTEXT):\n{context_items}\n"

        chunk_data = {
            "segments": [
                {"speaker": u['speaker'], "text": u['text'], "start": u['start'], "end": u['end']}
                for u in current_chunk
            ]
        }

        # Specific prompt for this chunk
        chunk_system_prompt = prompt_instructions + "\n\n" + \
            (f"PARTICIPANT LIST PROVIDED BY USER: {participants}\n"
             "INSTRUCTION: Attempt to attribute the diarized labels (Speaker 0, Speaker 1, etc.) to these names based on context clues (e.g., self-introductions, being addressed by name). "
             "If you are unsure, keep the generic Speaker label.\n\n" if participants else "") + \
            "SPECIAL INSTRUCTION: Output ONLY the formatted conversation dialogue for the provided segments. " \
            "Do NOT output the metadata header, summary, or action items yet. " \
            "Do NOT wrap in markdown code blocks. Just the designated speaker dialogue lines.\n" \
            "IMPORTANT: Do NOT repeat the same sentence multiple times. Write it once. If the speaker repeats themselves extensively, summarize the repetition (e.g., 'So these are the type of mails [repeated]...')."

        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": chunk_system_prompt},
                    {"role": "user", "content": f"{context_str}\n\nTranscript Segment Data to Format:\n{json.dumps(chunk_data, ensure_ascii=False)}"}
                ],
                temperature=0.3,
                frequency_penalty=0.5, # Reduce repetition
                presence_penalty=0.3   # Encourage new topics
            )
            
            part = response.choices[0].message.content.strip()
            # Cleanup potential markdown fences if model ignores instruction
            if part.startswith("```markdown"): part = part.replace("```markdown", "", 1)
            if part.startswith("```"): part = part.replace("```", "", 1)
            if part.endswith("```"): part = part[:-3]
            
            formatted_conversation_parts.append(part.strip())

        except Exception as e:
            print(f"Error formatting chunk {i+1}: {e}")
            # Fallback for chunk
            fallback = "\n\n".join([f"**{u['speaker']}** ({format_timestamp(u['start'])})\n{u['text']}" for u in current_chunk])
            formatted_conversation_parts.append(fallback)
    
    full_conversation_text = "\n\n".join(formatted_conversation_parts)

    # --- Phase 2: Generate Summary/Actions/Decisions ---
    print("Generating meeting summary...")
    
    # We send the RAW text for summary generation to save tokens, formatted text is not needed for understanding
    # If raw text is massive, we might need to truncate, but 128k context usually fits.
    # We'll take a simplified approach: Send the full raw transcript
    
    # Load MoM prompt
    mom_instructions = load_mom_prompt()
    if not mom_instructions:
        mom_instructions = prompt_instructions + "\n\n" + \
            "SPECIAL INSTRUCTION: Based on the transcript designated below, generate ONLY the following sections:\n" \
            "1. ## Meeting Summary\n" \
            "2. ## Key Discussion Points\n" \
            "3. ## Action Items\n" \
            "4. ## Decisions Made\n" \
            "5. ## Follow-up Required\n\n" \
            "Do NOT output the metadata header or the conversation dialogue. Just these summary sections."

    # Convert all utterances to a simple string for the summary model
    full_raw_text = "\n".join([f"{u['speaker']}: {u['text']}" for u in utterances])
    
    action_items = []
    summary_section = "## Meeting Summary\n\n(Summary generation failed)."

    try:
        # We'll ask for JSON to get both the Markdown content AND structured data
        system_instruction = (
            "You are a professional meeting secretary. You need to generate a meeting summary based on the transcript.\n"
            "Output MUST be in JSON format with the following keys:\n"
            "1. 'summary_markdown': The full markdown text containing Meeting Summary, Key Points, Action Items, Decisions, etc. (Formatted as requested)\n"
            "2. 'action_items': A list of objects, each having {'title': str, 'description': str, 'assigned_to': str, 'priority': str}\n"
            "\n"
            f"Here are the specific formatting instructions for the 'summary_markdown':\n{mom_instructions}"
        )

        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"Full Transcript:\n{full_raw_text}"}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        
        summary_section = data.get("summary_markdown", "")
        action_items = data.get("action_items", [])
        
    except Exception as e:
        print(f"Error generating summary/actions: {e}")
        # Fallback to text-only generation if JSON fails
        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": mom_instructions},
                    {"role": "user", "content": f"Full Transcript:\n{full_raw_text}"}
                ],
                temperature=0.3
            )
            summary_section = response.choices[0].message.content.strip()
            # Cleanup potential markdown fences
            if summary_section.startswith("```markdown"): summary_section = summary_section.replace("```markdown", "", 1)
            if summary_section.startswith("```"): summary_section = summary_section.replace("```", "", 1)
            if summary_section.endswith("```"): summary_section = summary_section[:-3]
        except Exception as e2:
             print(f"Fallback summary generation failed: {e2}")

    # --- Phase 3: Assembly ---

    # --- Phase 3: Assembly ---
    final_output = f"""# Meeting Transcript

**Date:** {current_date}
**Duration:** {duration_str}
**Participants:** {participants_str}

---

## Conversation

{full_conversation_text}

---

{summary_section}
"""
    return final_output, summary_section, action_items


# Helper: Split audio with PyDub 
def split_audio(file_path: str):
    audio = AudioSegment.from_file(file_path)
    duration_ms = len(audio)

    if duration_ms <= MAX_CHUNK_DURATION_MS:
        return [(file_path, 0)]

    chunks = []
    num_chunks = math.ceil(duration_ms / MAX_CHUNK_DURATION_MS)

    for i in range(num_chunks):
        start = i * MAX_CHUNK_DURATION_MS
        end = min((i + 1) * MAX_CHUNK_DURATION_MS, duration_ms)

        chunk = audio[start:end]
        chunk_path = f"{file_path}_chunk_{i+1}.mp3"
        chunk.export(chunk_path, format="mp3")

        chunks.append((chunk_path, start / 1000))

    return chunks


# Root
@app.get("/")
async def root():
    return {
        "message": "Audio Diarization API",
        "version": "4.0.0",
        "endpoints": {
            "upload": "/transcribe-with-diarization",
            "url": "/transcribe-from-url",
            "teams_transcript": "/upload-teams-transcript"
        }
    }


# URL-BASED ENDPOINT - Download and transcribe from URL
@app.post("/transcribe-from-url")
async def transcribe_from_url(request: TranscribeURLRequest):
    """
    Download audio file from URL, transcribe it, and return formatted output.
    
    Args:
        audio_url: URL or local path to the audio file
        save_files: Whether to save output files (default: True)
    
    Returns:
        Formatted transcript and metadata
    """
    audio_url = request.audio_url
    save_files = request.save_files
    
    # Extract filename from URL
    parsed_url = urlparse(audio_url)
    filename = os.path.basename(parsed_url.path) or "downloaded_audio.wav"
    
    # Download file
    temp_path = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    chunk_files = []
    
    try:
        # Download the file
        print(f"Downloading file from: {audio_url}")
        
        if audio_url.startswith(('http://', 'https://')):
            # Download from URL
            response = requests.get(audio_url, stream=True, timeout=300)
            response.raise_for_status()
            
            with open(temp_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
        else:
            # Copy from local path
            if not os.path.exists(audio_url):
                raise HTTPException(404, f"File not found: {audio_url}")
            shutil.copy(audio_url, temp_path)
        
        print(f"File downloaded successfully: {temp_path}")
        
        # Validate file extension
        ext = Path(temp_path).suffix.lower()
        if ext not in settings.allowed_extensions:
            raise HTTPException(400, f"Unsupported file type: {ext}. Allowed: {settings.allowed_extensions}")
        
        # Split audio if needed
        chunk_files = split_audio(temp_path)
        
        all_segments = []
        raw_chunks = []
        
        # Transcribe each chunk
        for idx, (chunk_path, time_offset) in enumerate(chunk_files, 1):
            print(f"Transcribing chunk {idx}/{len(chunk_files)}...")
            
            with open(chunk_path, "rb") as audio_file:
                transcript = safe_transcribe(
                    client,
                    model="gpt-4o-transcribe-diarize",
                    file=audio_file,
                    response_format="diarized_json",
                    chunking_strategy="auto"
                )

            
            raw_chunks.append({
                "chunk": idx,
                "offset_seconds": time_offset,
                "raw": transcript.model_dump() if hasattr(transcript, "model_dump") else transcript.__dict__
            })
            
            # Collect adjusted diarized segments
            for seg in transcript.segments:
                seg.start += time_offset
                seg.end += time_offset
                all_segments.append(seg)
        
        print(f"Transcription complete. Total segments: {len(all_segments)}")
        
        # Prepare utterances
        utterances = [
            {
                "speaker": seg.speaker,
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end
            }
            for seg in all_segments
        ]
        
        # Generate formatted transcript
        # Generate formatted transcript
        print("Formatting transcript with LLM...")
        formatted_transcript, summary_section, extracted_action_items = format_transcript_with_llm(utterances)
        
        print(f"DEBUG: Extracted {len(extracted_action_items)} action items.")
        
        # Prepare response
        response_data = {
            "message": "Success",
            "source_url": audio_url,
            "total_segments": len(utterances),
            "formatted_transcript": formatted_transcript,
            "utterances": utterances
        }
        
        # Save files if requested
        print(f"DEBUG: save_files={save_files}")
        if save_files:
            existing = sorted(settings.output_folder.glob("output_*_diarized.json"))
            next_index = len(existing) + 1
            
            base = f"output_{next_index}"
            diarized_json_path = settings.output_folder / f"{base}_diarized.json"
            raw_output_path = settings.output_folder / f"{base}_raw.json"
            txt_path = settings.output_folder / f"{base}_transcript.txt"
            formatted_path = settings.output_folder / f"{base}_formatted.md"
            
            # Save diarized JSON
            final_json = {
                "source_url": audio_url,
                "output_index": next_index,
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                "chunks": len(chunk_files),
                "utterances": utterances
            }
            
            with open(diarized_json_path, "w", encoding="utf-8") as f:
                json.dump(final_json, f, indent=2, ensure_ascii=False)
            
            # Save RAW output
            with open(raw_output_path, "w", encoding="utf-8") as f:
                json.dump({"chunks": raw_chunks}, f, indent=2, ensure_ascii=False)
            
            # Save Plain Transcript
            transcript_text = "\n".join([f"{u['speaker']}: {u['text']}" for u in utterances])
            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(transcript_text)
            
            # Save Formatted Transcript
            with open(formatted_path, "w", encoding="utf-8") as f:
                f.write(formatted_transcript)
            
            # Save separate MoM file
            mom_path = settings.output_folder / f"{base}_mom.md"
            with open(mom_path, "w", encoding="utf-8") as f:
                f.write(summary_section)

            # Store in Database
            try:
                # Estimate date from filename if possible, else now
                meeting_date = datetime.now() 
                
                # Basic Action Item Extraction from Summary (Simple Heuristic for now)
                # Ideally this would be done by LLM returning JSON
                action_items = []
                
                database.store_meeting_data(
                    title=filename,
                    date=meeting_date,
                    duration_seconds=sum(u['end'] - u['start'] for u in utterances),
                    audio_path=str(audio_url), # Original URL/Path
                    transcript_path=str(formatted_path),
                    mom_path=str(mom_path),
                    utterances=utterances,
                    action_items=extracted_action_items, 
                    summary_text=summary_section
                )
            except Exception as e:
                print(f"Database storage failed: {e}")

            # Add file paths to response
            print(f"DEBUG: Files saved to {settings.output_folder.absolute()}")
            response_data["saved_files"] = {
                "diarized_json": str(diarized_json_path),
                "raw_output": str(raw_output_path),
                "transcript_txt": str(txt_path),
                "formatted_md": str(formatted_path),
                "mom_md": str(mom_path)
            }
            response_data["output_index"] = next_index
        
        return response_data
    
    except requests.exceptions.RequestException as e:
        raise HTTPException(500, f"Failed to download file: {str(e)}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Transcription failed: {str(e)}")
    
    finally:
        # Cleanup
        for p, _ in chunk_files:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as e:
                    print(f"Warning: Could not delete chunk file {p}: {e}")
        
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except Exception as e:
                print(f"Warning: Could not delete temp file {temp_path}: {e}")


def group_speaker_transcript(response_json):
    speaker_transcripts = []
    last_speaker = None

    words = response_json["results"]["channels"][0]["alternatives"][0]["words"]

    for word in words:
        speaker = word["speaker"]
        text = word["word"]

        if speaker != last_speaker:
            speaker_transcripts.append({
                "speaker": speaker,
                "text": text
            })
        else:
            speaker_transcripts[-1]["text"] += " " + text

        last_speaker = speaker

    return speaker_transcripts

# TEAMS TRANSCRIPT ENDPOINT - Upload Teams VTT transcript
@app.post("/upload-teams-transcript")
async def upload_teams_transcript(file: UploadFile = File(...)):
    """
    Upload a Microsoft Teams VTT transcript file and format it professionally.
    
    This endpoint skips audio transcription and uses the existing transcript
    from Teams meetings, then applies LLM formatting.
    
    Args:
        file: VTT file from Teams meeting
    
    Returns:
        Formatted transcript and metadata
    """
    # Validate file extension
    ext = Path(file.filename).suffix.lower()
    if ext not in ['.vtt', '.txt']:
        raise HTTPException(400, f"Only VTT files are supported. Got: {ext}")
    
    try:
        # Read VTT content
        vtt_content = await file.read()
        vtt_text = vtt_content.decode('utf-8')
        
        print(f"Processing Teams transcript: {file.filename}")
        
        # Parse VTT to utterances
        utterances = parse_vtt_transcript(vtt_text)
        
        if not utterances:
            raise HTTPException(400, "No utterances found in VTT file")
        
        print(f"Parsed {len(utterances)} utterances from VTT")
        
        # Generate formatted transcript using existing LLM pipeline
        # Generate formatted transcript using existing LLM pipeline
        print("Formatting transcript with LLM...")
        formatted_transcript, summary_section, extracted_action_items = format_transcript_with_llm(utterances)
        
        # Determine output filenames
        existing = sorted(settings.output_folder.glob("output_*_diarized.json"))
        next_index = len(existing) + 1
        
        base = f"output_{next_index}"
        diarized_json_path = settings.output_folder / f"{base}_diarized.json"
        txt_path = settings.output_folder / f"{base}_transcript.txt"
        formatted_path = settings.output_folder / f"{base}_formatted.md"
        
        # Save diarized JSON
        final_json = {
            "original_filename": file.filename,
            "source": "teams_transcript",
            "output_index": next_index,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "utterances": utterances
        }
        
        with open(diarized_json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, indent=2, ensure_ascii=False)
        
        # Save Plain Transcript
        transcript_text = "\n".join([f"{u['speaker']}: {u['text']}" for u in utterances])
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(transcript_text)
        
        # Save Formatted Transcript
        with open(formatted_path, "w", encoding="utf-8") as f:
            f.write(formatted_transcript)
        
        # Save separate MoM file
        mom_path = settings.output_folder / f"{base}_mom.md"
        with open(mom_path, "w", encoding="utf-8") as f:
            f.write(summary_section)
        
        print(f"✓ Saved outputs with index {next_index}")
        
        # Store in Database
        try:
             database.store_meeting_data(
                title=file.filename,
                date=datetime.now(),
                duration_seconds=utterances[-1]['end'] if utterances else 0,
                audio_path="N/A (Teams Transcript)",
                transcript_path=str(formatted_path),
                mom_path=str(mom_path),
                utterances=utterances,
                action_items=extracted_action_items, 
                summary_text=summary_section
            )
        except Exception as e:
            print(f"Database storage failed: {e}")

        # Return response
        return {
            "message": "Success",
            "source": "teams_transcript",
            "output_index": next_index,
            "total_segments": len(utterances),
            "utterances": utterances,
            "diarized_json_file": str(diarized_json_path),
            "transcript_txt": str(txt_path),
            "formatted_transcript": str(formatted_path),
            "mom_file": str(mom_path)
        }
    
    except ValueError as e:
        raise HTTPException(400, f"Invalid VTT format: {str(e)}")
    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Processing failed: {str(e)}")


# UPLOAD ENDPOINT - Upload file directly
@app.post("/transcribe-with-diarization")
async def transcribe_with_diarization(
    file: UploadFile = File(...),
    participants: str = Form(None)
):
    ext = Path(file.filename).suffix.lower()
    if ext not in settings.allowed_extensions:
        raise HTTPException(400, f"Allowed: {settings.allowed_extensions}")

    # save uploaded file
    temp_path = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{file.filename}"
    with open(temp_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    # Explicitly close the uploaded file handle
    file.file.close()

    chunk_files = []

    try:
        # split if needed
        chunk_files = split_audio(temp_path)

        all_segments = []
        raw_chunks = []

        # -------------------------------------------------------
        # Transcribe each chunk using official API call ONLY
        # -------------------------------------------------------
        for idx, (chunk_path, time_offset) in enumerate(chunk_files, 1):
            with open(chunk_path, "rb") as audio_file:
                transcript = safe_transcribe(
                    client,
                    model="gpt-4o-transcribe-diarize",
                    file=audio_file,
                    response_format="diarized_json",
                    chunking_strategy="auto"
                )


            # keep raw response
            raw_chunks.append({
                "chunk": idx,
                "offset_seconds": time_offset,
                "raw": transcript.model_dump() if hasattr(transcript, "model_dump") else transcript.__dict__
            })

            # collect adjusted diarized segments
            for seg in transcript.segments:
                seg.start += time_offset
                seg.end += time_offset
                all_segments.append(seg)

        # -------------------------------------------------------
        # Determine output filenames
        # -------------------------------------------------------
        existing = sorted(settings.output_folder.glob("output_*_diarized.json"))
        next_index = len(existing) + 1

        base = f"output_{next_index}"
        diarized_json_path = settings.output_folder / f"{base}_diarized.json"
        raw_output_path = settings.output_folder / f"{base}_raw.json"
        txt_path = settings.output_folder / f"{base}_transcript.txt"
        formatted_path = settings.output_folder / f"{base}_formatted.md"

        # -------------------------------------------------------
        # Save diarized JSON
        # -------------------------------------------------------
        utterances = [
            {
                "speaker": seg.speaker,
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end
            }
            for seg in all_segments
        ]

        final_json = {
            "original_filename": file.filename,
            "output_index": next_index,
            "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            "chunks": len(chunk_files),
            "utterances": utterances
        }

        with open(diarized_json_path, "w", encoding="utf-8") as f:
            json.dump(final_json, f, indent=2, ensure_ascii=False)

        # -------------------------------------------------------
        # Save RAW output
        # -------------------------------------------------------
        with open(raw_output_path, "w", encoding="utf-8") as f:
            json.dump({"chunks": raw_chunks}, f, indent=2, ensure_ascii=False)

        # -------------------------------------------------------
        # Save Plain Transcript
        # -------------------------------------------------------
        transcript_text = "\n".join([f"{u['speaker']}: {u['text']}" for u in utterances])

        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(transcript_text)

        # -------------------------------------------------------
        # Generate and Save Formatted Transcript with LLM
        # -------------------------------------------------------
        formatted_transcript, summary_section, extracted_action_items = format_transcript_with_llm(utterances, participants)
        
        with open(formatted_path, "w", encoding="utf-8") as f:
            f.write(formatted_transcript)

        # Save separate MoM file
        mom_path = settings.output_folder / f"{base}_mom.md"
        with open(mom_path, "w", encoding="utf-8") as f:
            f.write(summary_section)

        # Store in Database
        try:
            database.store_meeting_data(
                title=file.filename,
                date=datetime.now(),
                duration_seconds=sum(u['end'] - u['start'] for u in utterances) if utterances else 0,
                audio_path=str(temp_path), # We might want to store the PERMANENT path if we kept it? Rght now it deletes temp.
                # Ideally we should move the temp file to a storage dir if we want to keep it.
                # For now just storing the temp path reference even though it gets deleted, or maybe just "Uploaded File"
                transcript_path=str(formatted_path),
                mom_path=str(mom_path),
                utterances=utterances,
                action_items=extracted_action_items, 
                summary_text=summary_section
            )
        except Exception as e:
            print(f"Database storage failed: {e}")

        # -------------------------------------------------------
        # Return clean JSON response
        # -------------------------------------------------------
        return {
            "message": "Success",
            "output_index": next_index,
            "utterances": utterances,
            "diarized_json_file": str(diarized_json_path),
            "raw_output_file": str(raw_output_path),
            "transcript_txt": str(txt_path),
            "formatted_transcript": str(formatted_path),
            "mom_file": str(mom_path)
        }

    except Exception as e:
        traceback.print_exc()
        raise HTTPException(500, f"Transcription failed: {e}")

    finally:
        for p, _ in chunk_files:
            if os.path.exists(p):
                for attempt in range(3):
                    try:
                        time.sleep(0.1)
                        os.remove(p)
                        break
                    except PermissionError:
                        if attempt == 2:
                            print(f"Warning: Could not delete chunk file {p} after 3 attempts")
                        time.sleep(0.5)
                    except Exception as e:
                        print(f"Warning: Error deleting chunk file {p}: {e}")
                        break
        
        # Clean up main temp file
        if os.path.exists(temp_path):
            for attempt in range(3):
                try:
                    time.sleep(0.1)  # Small delay to allow file handles to close
                    os.remove(temp_path)
                    break
                except PermissionError:
                    if attempt == 2:
                        print(f"Warning: Could not delete temp file {temp_path} after 3 attempts")
                    time.sleep(0.5)
                except Exception as e:
                    print(f"Warning: Error deleting temp file {temp_path}: {e}")
                    break


@app.get("/health")
async def health():
    return {"status": "ok"}



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)