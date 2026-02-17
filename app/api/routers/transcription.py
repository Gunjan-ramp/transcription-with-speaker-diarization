from fastapi import APIRouter, HTTPException
from urllib.parse import urlparse
import os
import shutil
import requests
import json
import traceback
import time
from pathlib import Path
from datetime import datetime
from app.schemas.requests import TranscribeURLRequest
from app.core.config import settings
from app.core.openai_client import client
from app.core import database
from app.services.audio import split_audio
from app.services.transcription import safe_transcribe
from app.services.llm import format_transcript_with_llm

router = APIRouter()

@router.post("/transcribe-from-url")
async def transcribe_from_url(request: TranscribeURLRequest):
    """
    Download audio file from URL, transcribe it, and return formatted output.
    
    Args:
        audio_url: URL or local path to the audio file
        save_files: Whether to save output files (default: True)
    
    Returns:
        Formatted transcript and metadata
    """
    from app.services.transcription_workflow import process_transcription as process_transcription_workflow
    from app.services.graph_service import GraphService
    
    try:
        result = await process_transcription_workflow(request.audio_url, request.save_files)
        
        # --- Email Sending Logic ---
        # Determine recipients: Request > Manager > Target User
        recipients = request.recipients
        if not recipients:
            fallback = settings.manager_email or settings.target_user_email
            if fallback:
                recipients = [fallback]
        
        if recipients:
            # Check if MoM was generated
            mom_path = result.get("saved_files", {}).get("mom_md")
            file_name = os.path.basename(request.audio_url) # Simple fallback if filename not available in result. 
            # Note: process_transcription doesn't return filename explicitly in top-level dict, but we can infer or use audio_url
            
            if mom_path and os.path.exists(mom_path):
                with open(mom_path, "r", encoding="utf-8") as f:
                    mom_content_md = f.read()
                import markdown
                mom_content_html = markdown.markdown(mom_content_md, extensions=['tables', 'nl2br'])
            else:
                mom_content_html = "<p>Minutes of Meeting could not be generated.</p>"

            email_body = f"""
            <p><b>Source:</b> {request.audio_url}</p>
            <p><b>Date:</b> {datetime.now().strftime('%Y-%m-%d %H:%M')}</p>
            <hr>
            <h3>Meeting Minutes</h3>
            <div style="font-family: sans-serif;">
            {mom_content_html}
            </div>
            """
            
            # Send Email
            try:
                # We need a user context for GraphService. Use target_user_email as sender context.
                sender_context = settings.target_user_email or settings.sender_email
                if sender_context:
                    graph = GraphService(user_email=sender_context)
                    graph.send_email(
                        to_email=recipients,
                        subject=f"Transcription Result: {datetime.now().strftime('%Y-%m-%d')}",
                        content=email_body,
                        attachment_paths=[]
                    )
                    result["email_status"] = f"Sent to {recipients}"
                else:
                    result["email_status"] = "Skipped (No sender configured)"
            except Exception as e:
                print(f"Failed to send email: {e}")
                result["email_status"] = f"Failed: {str(e)}"
        else:
             result["email_status"] = "Skipped (No recipients)"

        return result
    except requests.exceptions.RequestException as e:
        raise HTTPException(500, f"Failed to download file: {str(e)}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {str(e)}")

