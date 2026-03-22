# Project Documentation: Audio Transcription & Diarization API

## 1. Project Overview
The project is a FastAPI-based service designed to process audio files for transcription, perform speaker diarization, automatically format transcripts using LLMs, and autonomously join Microsoft Teams meetings to record and transcribe them. The primary goal is to provide end-to-end automation from capturing a live meeting to generating professional Minutes of Meeting (MoM) documents.

---

## 2. System Architecture & Workflow

### 2.1. API & Routing Layer (`app.main.py` & `app.api.routers`)
- The application exposes a REST API via **FastAPI**.
- The endpoints are divided into routers for transcription (`/transcribe-with-diarization`), bot control (`/bot`), Microsoft Teams webhook integrations (`/teams`), and authentication (`/auth`).
- **Streaming Endpoints**: Provides Server-Sent Events (SSE) to update the client in real-time on long transcription progress.

### 2.2. Autonomous Meeting Bot (`app.services.meeting_bot.py`)
- **Purpose**: Acts as a virtual participant that joins Microsoft Teams meetings to record the audio.
- **Operation**: Bootstraps a headless Chromium browser using **Playwright**. It navigates to the provided Teams web meeting link, bypasses cookie consent screens, and attempts to join the meeting via the browser interface.
- **Authentication/Identity**: Automatically fills in a guest name (e.g., "AI Assistant") and simulates keyboard shortcuts (`Ctrl+Shift+M`/`O`) to mute its own microphone and camera before joining.
- **Recording Mechanism**: Once admitted from the lobby, the bot relies on **FFmpeg** to capture system audio. On Windows, it uses the "Stereo Mix" DirectShow (`dshow`) device, and on Linux, a PulseAudio virtual sink monitor.
- **Meeting State Monitoring**: The script continuously polls the DOM (checking text visibility like "The meeting has ended" or "Someone removed you") to decide when to cleanly terminate the FFmpeg process and close the browser.

### 2.3. Transcription Workflow (`app.services.transcription_workflow.py`)
- **Purpose**: Converts recorded or uploaded audio into structured, diarized Markdown and JSON.
- **Chunking Logic**: To handle long recordings cleanly, `app.services.audio.py` splits audio files greater than a specific duration (usually 20 minutes) into chunks.
- **Transcription Engine**: Each chunk is forwarded to OpenAI's Whisper API (specifically `gpt-4o-transcribe-diarize`), passing custom prompts with known speaker vocabulary to assist model accuracy.
- **Post-Processing**: The individual chunks are stitched back together by recalculating the timestamp offsets (`time_offset`). 
- **LLM Formatting**: The raw transcription is passed to a GPT model in `app.services.llm.py` to be structured into an easy-to-read Markdown file containing:
  - Header & Participants
  - Action Items
  - Meeting Summary

---

## 3. Frameworks, Libraries & Technologies Used

### Backend & API
- **FastAPI / Uvicorn**: The core framework for high-performance, asynchronous REST API serving.
- **Python-Multipart**: Used for parsing `multipart/form-data` during audio file uploads.

### Browser Automation & Bot
- **Playwright**: For launching the headless browser to interact with the MS Teams web app.
- **Playwright-Stealth**: Modifies the Chromium instance to prevent Microsoft from detecting and blocking the bot as an automated script.

### AI & Machine Learning
- **OpenAI (Python SDK)**: Used for transcribing audio via the `gpt-4o-transcribe-diarize` model, and for transforming raw transcripts into formatted markdown summaries.

### Audio Processing
- **Static-FFmpeg**: A cross-platform FFmpeg wrapper used to record system audio directly from the Playwright session, and for splitting audio files.
- **PyDub / Mutagen**: For audio format manipulation, checking durations, and extracting metadata.
- **WebVTT-Py**: To parse native Microsoft Teams transcript subtitle files.

### Infrastructure & Utilities
- **Pydantic-Settings / Python-DotEnv**: Managing configuration securely through environment variables.
- **SQLAlchemy / PyODBC**: Database Object Relational Mapping (ORM) setup to keep track of bot task states and transcript records.
- **APScheduler / Schedule**: Background task schedulers for kicking off bot joins asynchronously at the correct meeting times.
- **Python-Docx / Markdown**: For generating final output documents in different formats.

---

## 4. Known Limitations & Defects

### 4.1. Bot UI Brittleness & Lobby Bugs
- **Defect**: The `TeamsBot` operates by web scraping the Microsoft Teams web app. It relies on finding HTML elements by specific text content (e.g., "Join now", "Leave"). When Microsoft silently updates the UI classes or translates the text in a different region, the bot fails to find the buttons and gets stuck in the lobby or fails to exit when the meeting ends.
- **Defect**: Sometimes the bot times out in the lobby if the host doesn't admit it, which consumes server resources unnecessarily. 

### 4.2. Audio Capture Dependency
- **Limitation**: The bot records system audio (`Stereo Mix` on Windows). This is an extremely fragile setup. It means the server captures **all** audio playing on the machine. You cannot run multiple bots simultaneously on the same Windows session without the audio bleeding into each other's recordings, heavily restricting scalability.

### 4.3. Diarization Across Chunks
- **Defect**: Large meetings are split into chunks. Because the model processes each chunk independently, the labels it generates (e.g., "Speaker 1" and "Speaker 2") can mismatch across chunks. "Speaker 1" in minute 0-20 might become "Speaker 2" in minute 20-40, creating confusion in the final merged transcript.
- **Limitation**: Hard splitting audio files temporally (e.g., exactly at the 20-minute mark) occasionally mid-sentence, causing a few words to be lost or garbled.

### 4.4. Speaker Identification Accuracy
- **Limitation**: While OpenAI's diarization is excellent, cross-talk (multiple people speaking at once), background noise, or users with similar voices frequently cause the model to either merge speakers or attribute speech to the wrong person.

### 4.5. Scalability Issues
- **Limitation**: The architecture of spinning up a full headless Chromium browser + FFmpeg encoding process for every single meeting is computationally heavy. A standard server will hit CPU memory bottlenecks if tasked with monitoring more than a handful of concurrent meetings.

---

## 5. Architectural Improvements: Overcoming Limitations

### 5.1. Replacing Playwright Bots with API-Driven Bots (Solves 4.1, 4.2 & 4.5)
**Solution**: Transition from web-scraping to the **Microsoft Graph Communications API**. 
- **How it works**: Instead of simulating a browser user, you register an Azure Application as a "Media Bot". Microsoft sends the live audio/video streams directly to your backend server over TCP/UDP sockets via the API.
- **Impact**: 
  - Zero UI brittleness: Microsoft updates its frontend daily, but the API remains stable.
  - No Lobby issues: The bot knows programmatically via JSON payloads if it sits in a lobby or is admitted.
  - Zero audio bleeding: Every meeting gets a dedicated, isolated audio socket. No more "Stereo Mix."
  - Massive scalability: You drop the CPU overhead of rendering headless Chrome. A single backend server can handle 10x-50x more concurrent audio streams.

### 5.2. Dockerized Virtual Sinks (Alternative fix for 4.2 & 4.5)
**Solution**: If you must keep the Playwright approach, move the deployment entirely to Linux/Docker. 
- **How it works**: Deploy the application in a scalable Kubernetes or Docker Swarm cluster. For every single meeting join request, spin up an isolated Docker container with `Xvfb` (a virtual display server) and a `PulseAudio` dummy sink. 
- **Impact**: Ensures that when Bot A joins Meeting 1, it captures *only* the audio inside Container A. This completely isolates the audio and allows horizontal background scaling without relying on Windows Host hardware.

### 5.3. Smart Audio Chunking & Speaker Embeddings (Solves 4.3)
**Solution**: Replace strict 20-minute splits with intelligent Voice Activity Detection (VAD).
- **How it works**: 
  - Use a lightweight, open-source VAD library (like `silero-vad` or `pyannote`) to detect exactly where people pause speaking. Split chunks *only* during long silences.
  - To prevent speaker ID swaps ("Speaker 1" becoming "Speaker 2"), compute a universal "Speaker Embedding" (voice fingerprint) for each voice cluster before chunking, and pass the explicit speaker hints into OpenAI on every chunk.

### 5.4. SOTA Dedicated Diarization Pipelines (Solves 4.4)
**Solution**: Decouple the "Who is talking" task from the "What are they saying" task.
- **How it works**: Instead of relying on Whisper to do both simultaneously, run the audio through a dedicated State-of-the-Art (SOTA) Diarization model first (such as **PyAnnote Audio 3.1**). PyAnnote focuses purely on voice separation and is far more resilient to cross-talk. 
- **Impact**: PyAnnote generates precise timestamps for each speaker (down to the millisecond). You then pass *these exact timestamps back into Whisper* to perform basic transcription, removing the burden of speaker guessing from Whisper.
