# Audio Transcription & Diarization API

FastAPI-based service for transcribing audio files with speaker diarization using OpenAI's `gpt-4o-transcribe-diarize` model.

## Features

- 🎙️ **Speaker Diarization**: Automatically identifies and labels different speakers
- 🌍 **Multilingual Support**: Handles mixed-language transcripts (English, Hindi, Urdu, etc.)
- 📝 **Professional Formatting**: Uses LLM to format transcripts into business-ready documents
- ⚡ **Streaming Support**: Real-time progress updates for long audio files
- 🔄 **Automatic Chunking**: Handles files longer than 20 minutes by splitting them
- 📊 **Multiple Output Formats**: JSON, TXT, and formatted Markdown

## API Endpoints

### 1. Standard Endpoint (Non-Streaming)
**POST** `/transcribe-with-diarization`

Returns complete results after all processing is done.

**Usage:**
```bash
curl -X POST "http://localhost:8000/transcribe-with-diarization" \
  -F "file=@your_audio.wav"
```

**Response:**
```json
{
  "message": "Success",
  "output_index": 1,
  "utterances": [...],
  "diarized_json_file": "output/output_1_diarized.json",
  "raw_output_file": "output/output_1_raw.json",
  "transcript_txt": "output/output_1_transcript.txt",
  "formatted_transcript": "output/output_1_formatted.md"
}
```

### 2. Teams Transcript Upload
**POST** `/upload-teams-transcript`

Upload a Microsoft Teams VTT transcript file directly (no audio transcription needed).

**Benefits:**
- ⚡ Much faster (skips audio transcription)
- 💰 Cheaper (no OpenAI Whisper API calls)
- 🎯 Still applies professional LLM formatting

**Usage:**
```bash
curl -X POST "http://localhost:8000/upload-teams-transcript" \
  -F "file=@teams_transcript.vtt"
```

**How to get Teams transcripts:**
1. In Teams, go to your meeting recording
2. Click "..." → "Download transcript"
3. Save the `.vtt` file
4. Upload it to this endpoint

**Response:**
```json
{
  "message": "Success",
  "source": "teams_transcript",
  "output_index": 1,
  "total_segments": 42,
  "utterances": [...],
  "diarized_json_file": "output/output_1_diarized.json",
  "transcript_txt": "output/output_1_transcript.txt",
  "formatted_transcript": "output/output_1_formatted.md"
}
```

### 3. Streaming Endpoint (Recommended for Large Files)
**POST** `/transcribe-with-diarization-stream`

Returns Server-Sent Events (SSE) with real-time progress updates.

**Usage with Python:**
```python
import requests

with open('audio.wav', 'rb') as f:
    files = {'file': f}
    with requests.post('http://localhost:8000/transcribe-with-diarization-stream', 
                      files=files, stream=True) as response:
        for line in response.iter_lines():
            if line:
                print(line.decode('utf-8'))
```

**Or use the provided test client:**
```bash
python test_streaming_client.py input/your_audio.wav
```

**Stream Events:**
The streaming endpoint sends JSON events with different statuses:

1. `file_uploaded` - File successfully uploaded
2. `audio_split` - Audio split into chunks (if needed)
3. `transcribing_chunk` - Processing chunk X of Y
4. `chunk_complete` - Chunk transcription done (includes segments)
5. `transcription_complete` - All chunks transcribed
6. `saved_diarized_json` - Diarized JSON saved
7. `saved_raw_output` - Raw output saved
8. `saved_transcript` - Plain transcript saved
9. `formatting_with_llm` - LLM formatting in progress
10. `saved_formatted` - Formatted transcript saved
11. `complete` - All processing finished

**Example Stream Output:**
```
data: {"status": "file_uploaded", "filename": "meeting.wav"}
data: {"status": "audio_split", "total_chunks": 3}
data: {"status": "transcribing_chunk", "chunk": 1, "total": 3}
data: {"status": "chunk_complete", "chunk": 1, "segments_count": 45, "segments": [...]}
data: {"status": "transcribing_chunk", "chunk": 2, "total": 3}
...
data: {"status": "complete", "output_index": 1, "files": {...}}
```

## Output Files

For each transcription, the API generates 4 files:

1. **`output_X_diarized.json`** - Structured JSON with speaker-labeled utterances
2. **`output_X_raw.json`** - Raw API responses from OpenAI
3. **`output_X_transcript.txt`** - Simple plain text transcript
4. **`output_X_formatted.md`** - Professionally formatted Markdown document

## Formatted Output

The formatted Markdown output includes:

- **Meeting header** with date, duration, and participants
- **Conversation** with timestamps and speaker labels
- **Meeting summary**
- **Action items** with assignees
- **Key decisions**
- **Follow-up items**

All non-English content is automatically translated to English.

## Configuration

Edit `config.py` or `.env` file:

```python
OPENAI_API_KEY=your_api_key_here
OUTPUT_FOLDER=output
ALLOWED_EXTENSIONS=[".wav", ".mp3", ".m4a", ".flac"]
ENABLE_LLM_FORMATTING=True
LLM_MODEL=gpt-4o
```

## Installation

```bash
# Install dependencies
pip install -r requirements.txt

# Run the server
python main.py

# Or with uvicorn
uvicorn main:app --reload --host 0.0.0.0 --port 8000
```

## Supported Audio Formats

- WAV
- MP3
- M4A
- FLAC
- And other formats supported by PyDub

## Supported Transcript Formats

- **VTT (WebVTT)** - Microsoft Teams transcript files
- More formats coming soon (DOCX, SRT)

## Performance

- **Small files (<20 min)**: Processed as single chunk
- **Large files (>20 min)**: Automatically split into 20-minute chunks
- **Streaming**: Get real-time updates, perfect for monitoring long transcriptions

## Use Cases

- 📞 Meeting transcriptions
- 🎤 Interview recordings
- 🎓 Lecture notes
- 📻 Podcast transcripts
- 🌐 Multilingual conversations

## API Documentation

Once running, visit:
- **Interactive docs**: http://localhost:8000/docs
- **Alternative docs**: http://localhost:8000/redoc

## Health Check

```bash
curl http://localhost:8000/health
```

## Example Workflow

1. Upload audio file to streaming endpoint
2. Monitor real-time progress updates
3. Receive notifications as each chunk completes
4. Get final formatted transcript in Markdown
5. Use the professional document for meetings/emails

## Notes

- The streaming endpoint is recommended for files >5 minutes
- LLM formatting adds ~30-60 seconds but produces much better output
- All timestamps are in HH:MM:SS format
- Speaker labels are automatically assigned (Speaker A, B, C, etc.)
