from pydantic import BaseModel

class TranscribeURLRequest(BaseModel):
    audio_url: str
    save_files: bool = True  # Whether to save output files or just return the transcript
