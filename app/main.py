import sys
import asyncio

# --- CRITICAL: Windows Proactor Loop Fix ---
# This MUST be the first thing that happens on Windows to support Playwright subprocesses
if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
# -------------------------------------------

from fastapi import FastAPI
from contextlib import asynccontextmanager
import static_ffmpeg
import os

# Initialize ffmpeg
static_ffmpeg.add_paths()

from app.core import database
from app.core.config import settings
from app.api.routers import transcription, teams, auth, bot

# Initialize Database
database.init_db()

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        if os.environ.get("RUN_MAIN") == "true" or not os.environ.get("UVICORN_RELOAD"):
            from app.scheduler_main import start_scheduler
            start_scheduler()
            print("[+] Scheduler started successfully.")
    except Exception as e:
        print(f"[ERROR] Failed to start scheduler: {e}")
        raise
    yield
    print("[+] Application shutdown.")

app = FastAPI(
    title="Audio Transcription API",
    description="Transcribe audio with diarization using OpenAI gpt-4o-transcribe-diarize",
    version="4.0.0",
    lifespan=lifespan
)

settings.output_folder.mkdir(exist_ok=True)

app.include_router(transcription.router)
app.include_router(teams.router)
app.include_router(auth.router)
app.include_router(bot.router)

@app.get("/")
async def root():
    return {
        "message": "Audio Diarization API",
        "version": "4.0.0"
    }

if __name__ == "__main__":
    import uvicorn
    # Explicitly set loop="asyncio" to ensure our policy is respected
    uvicorn.run("app.main:app", host="0.0.0.0", port=50104, reload=False, loop="asyncio")
