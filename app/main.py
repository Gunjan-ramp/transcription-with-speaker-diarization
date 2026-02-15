from fastapi import FastAPI
import static_ffmpeg

# Initialize ffmpeg early to ensure paths are set before pydub is imported
static_ffmpeg.add_paths()

from app.core import database
from app.core.config import settings
from app.api.routers import transcription, teams, auth

# Initialize Database
database.init_db()

# FastAPI app
app = FastAPI(
    title="Audio Transcription API",
    description="Transcribe audio with diarization using OpenAI gpt-4o-transcribe-diarize",
    version="4.0.0"
)

# Ensure output folder exists
settings.output_folder.mkdir(exist_ok=True)

# Include Routers
app.include_router(transcription.router)
app.include_router(teams.router)
app.include_router(auth.router)

@app.get("/")
async def root():
    return {
        "message": "Audio Diarization API",
        "version": "4.0.0",
        "endpoints": {
            "url": "/transcribe-from-url",
            "teams_transcript": "/upload-teams-transcript"
        }
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
