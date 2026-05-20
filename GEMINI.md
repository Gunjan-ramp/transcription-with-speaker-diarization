# GEMINI.md - Instructional Context

## Project Overview
This is a **FastAPI-based Audio Transcription & Diarization Service**. It is designed to capture, transcribe, and summarize audio recordings, with a specialized focus on **Microsoft Teams** meetings.

### Core Capabilities
1.  **Diarized Transcription:** Uses OpenAI's `gpt-4o-transcribe-diarize` to convert audio into speaker-labeled transcripts.
2.  **Autonomous Meeting Bot:** A Playwright-driven bot that joins Teams meetings as a guest, records audio using FFmpeg, and saves it for processing.
3.  **Professional Formatting:** An LLM-based post-processing step that transforms raw transcripts into clean, structured Minutes of Meeting (MoM) in Markdown format.
4.  **Teams Webhook Integration:** Handles incoming webhooks from Microsoft Teams for automated recording capture.
5.  **Chunking Logic:** Automatically splits long audio files (>20 mins) to stay within OpenAI API limits and reconstructs them post-transcription.

### Tech Stack
-   **Backend:** FastAPI, Uvicorn, Pydantic (Settings & Schemas)
-   **Automation:** Playwright, Playwright-Stealth
-   **Audio/Video:** FFmpeg (`static-ffmpeg`), PyDub
-   **AI:** OpenAI API (Whisper/GPT-4o)
-   **Database:** SQL Server (via SQLAlchemy & PyODBC)
-   **Deployment:** Docker, Docker Compose

---

## Architecture & Flow

### 1. API Layers (`app/api/routers/`)
-   `transcription.py`: Main endpoints for file upload and streaming transcription.
-   `bot.py`: Control interface for the autonomous Teams bot (`/join`, `/stop`).
-   `teams.py`: Integration with Microsoft Graph/Teams webhooks.
-   `auth.py`: Authentication and identity management.

### 2. Services (`app/services/`)
-   `meeting_bot.py`: The browser automation logic for joining and recording meetings.
-   `transcription_workflow.py`: Orchestrates the chunking, transcription, and merging process.
-   `audio.py`: Utilities for splitting and manipulating audio files.
-   `llm.py`: Interaction with GPT models for formatting and summarization.

### 3. Core (`app/core/`)
-   `config.py`: Centralized configuration using Pydantic `BaseSettings`.
-   `database.py`: Database connection and session management.

---

## Building and Running

### Prerequisites
-   Python 3.10+
-   FFmpeg installed (managed via `static-ffmpeg` in the app)
-   Playwright browsers installed (`playwright install chromium`)
-   SQL Server (configured in `.env`)

### Local Setup
```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Start the application
python -m app.main
```

### Docker Deployment
```bash
# Build and run with Docker Compose
docker-compose up --build
```

### Key Configuration (`.env`)
The application requires several environment variables to function correctly:
-   `OPENAI_API_KEY`: Required for transcription and formatting.
-   `DB_SERVER`, `DB_NAME`, `DB_USER`, `DB_PASSWORD`: Database credentials.
-   `WINDOWS_AUDIO_DEVICE`: (Optional) Specifically for Windows audio recording setup.

---

## Development Conventions

-   **Asynchronous Patterns:** Use `async/await` for all I/O bound operations (FastAPI endpoints, database calls, API requests).
-   **Playwright Stability:** When running on Windows, the application uses `asyncio.WindowsProactorEventLoopPolicy()` to support Playwright subprocesses.
-   **Error Handling:** Use diagnostic screenshots and HTML dumps (saved in `output/bot_recordings/`) when debugging bot automation failures.
-   **Surgical Updates:** When modifying the bot's UI logic, prioritize robust CSS/Aria selectors and retry mechanisms to handle Microsoft Teams' dynamic UI.
-   **Logging:** Logs are typically found in the `logs/` directory.

---

## Important Files
-   `app/main.py`: Entry point and lifespan management (starts scheduler).
-   `app/services/meeting_bot.py`: Critical logic for meeting automation.
-   `app/services/transcription_workflow.py`: Orchestrates the AI pipeline.
-   `requirements.txt`: Project dependencies.
-   `Project_Documentation.md`: Comprehensive guide to the system architecture.
