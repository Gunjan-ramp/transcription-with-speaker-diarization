from fastapi import APIRouter, UploadFile, File, HTTPException
from pathlib import Path
from datetime import datetime
import json
import traceback

from app.core.config import settings
from app.core import database
from app.services.parsers import parse_vtt_transcript
from app.services.llm import format_transcript_with_llm

router = APIRouter()

@router.post("/upload-teams-transcript")
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
