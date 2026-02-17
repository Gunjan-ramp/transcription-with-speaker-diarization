from pydantic import BaseModel

from typing import List, Optional

class TranscribeURLRequest(BaseModel):
    audio_url: str
    save_files: bool = True  # Whether to save output files or just return the transcript
    recipients: Optional[List[str]] = None  # Optional list of email recipients
