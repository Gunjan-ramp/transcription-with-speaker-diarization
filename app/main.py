from fastapi import FastAPI
from contextlib import asynccontextmanager
import static_ffmpeg
import os

# Initialize ffmpeg early to ensure paths are set before pydub is imported
static_ffmpeg.add_paths()

from app.core import database
from app.core.config import settings
from app.api.routers import transcription, teams, auth

# Initialize Database
database.init_db()


# ---------------------------
# Lifespan (Modern Startup)
# ---------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Handles startup and shutdown events safely.
    Prevents scheduler from starting twice when using --reload.
    """
    try:
        # Prevent scheduler from running in the reloader process
        if os.environ.get("RUN_MAIN") == "true" or not os.environ.get("UVICORN_RELOAD"):
            from app.scheduler_main import start_scheduler
            start_scheduler()
            print("[+] Scheduler started successfully.")

    except Exception as e:
        print(f"[ERROR] Failed to start scheduler: {e}")
        raise

    yield

    print("[+] Application shutdown.")


# ---------------------------
# FastAPI App
# ---------------------------
app = FastAPI(
    title="Audio Transcription API",
    description="Transcribe audio with diarization using OpenAI gpt-4o-transcribe-diarize",
    version="4.0.0",
    lifespan=lifespan
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


# ---------------------------
# Run Directly (Optional)
# ---------------------------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=50104, reload=False)
