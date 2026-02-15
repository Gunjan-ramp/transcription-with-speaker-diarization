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
    
    try:
        return await process_transcription_workflow(request.audio_url, request.save_files)
    except requests.exceptions.RequestException as e:
        raise HTTPException(500, f"Failed to download file: {str(e)}")
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(500, f"Transcription failed: {str(e)}")

