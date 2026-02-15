import os
import shutil
import requests
import json
import traceback
import time
from pathlib import Path
from datetime import datetime
from fastapi import HTTPException

from app.core.config import settings
from app.core.openai_client import client
from app.core import database
from app.services.audio import split_audio
from app.services.transcription import safe_transcribe
from app.services.llm import format_transcript_with_llm

async def process_transcription(audio_url: str, save_files: bool = True):
    """
    Core logic to download, transcribe, and save results.
    Can be called by API router or internal scheduler.
    """
    
    # Extract filename from URL
    from urllib.parse import urlparse
    parsed_url = urlparse(audio_url)
    filename = os.path.basename(parsed_url.path) or "downloaded_audio.wav"
    
    # Download file
    temp_path = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"
    chunk_files = []
    
    # Return data structure
    response_data = {
        "message": "Processing",
        "source_url": audio_url,
        "saved_files": {}
    }

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
                raise FileNotFoundError(f"File not found: {audio_url}")
            shutil.copy(audio_url, temp_path)
        
        print(f"File downloaded successfully: {temp_path}")
        
        # Validate file extension
        ext = Path(temp_path).suffix.lower()
        if ext not in settings.allowed_extensions:
            # For scheduler, we might just skip, but raising error is fine
            raise ValueError(f"Unsupported file type: {ext}. Allowed: {settings.allowed_extensions}")
        
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
        print("Formatting transcript with LLM...")
        formatted_transcript, summary_section, extracted_action_items = format_transcript_with_llm(utterances)
        
        print(f"DEBUG: Extracted {len(extracted_action_items)} action items.")
        
        response_data["total_segments"] = len(utterances)
        response_data["formatted_transcript"] = formatted_transcript
        response_data["utterances"] = utterances
        
        # Save files if requested
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
        
        response_data["message"] = "Success"
        return response_data
    
    except Exception as e:
        traceback.print_exc()
        # Re-raise or return error dict?
        # For internal usage, re-raising is often better, but let's keep it clean
        raise e
    
    finally:
        # Cleanup
        for p, _ in chunk_files:
            if os.path.exists(p):
                try:
                    os.remove(p)
                except Exception as e:
                    print(f"Warning: Could not delete chunk file {p}: {e}")
        
        if os.path.exists(temp_path):
            max_retries = 3
            for i in range(max_retries):
                try:
                    os.remove(temp_path)
                    break
                except PermissionError:
                    if i < max_retries - 1:
                        time.sleep(1)
                    else:
                        print(f"Warning: Could not delete temp file {temp_path} after retries.")
                except Exception as e:
                    print(f"Warning: Could not delete temp file {temp_path}: {e}")
