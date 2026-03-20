import os
import shutil
import requests
import json
import traceback
from pathlib import Path
from datetime import datetime

from app.core.config import settings
from app.core.openai_client import client
from app.services.llm import format_transcript_with_llm
from app.services.speaker_samples import (
    known_speaker_names,
    known_speaker_references
)

async def process_transcription(audio_url: str, save_files: bool = True):

    from urllib.parse import urlparse
    parsed_url = urlparse(audio_url)
    filename = os.path.basename(parsed_url.path) or "audio.wav"

    temp_path = f"temp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{filename}"

    response_data = {
        "message": "Processing",
        "source_url": audio_url,
        "saved_files": {}
    }

    # Populated after split_audio; needed in finally for cleanup
    chunk_files = []

    try:

        print(f"Downloading: {audio_url}")

        if audio_url.startswith(("http://", "https://")):
            r = requests.get(audio_url, stream=True)
            r.raise_for_status()

            with open(temp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    f.write(chunk)

        else:
            shutil.copy(audio_url, temp_path)

        ext = Path(temp_path).suffix.lower()
        if ext not in settings.allowed_extensions:
            raise ValueError(f"Unsupported file type: {ext}")

        # --- Chunked transcription ---
        # split_audio returns [(path, offset_seconds), ...].
        # For files <= 20 min it returns [(temp_path, 0)] — no splitting overhead.
        from app.services.audio import split_audio
        from app.services.transcription import safe_transcribe

        chunk_files = split_audio(temp_path)
        total_chunks = len(chunk_files)
        print(f"Audio split into {total_chunks} chunk(s). Starting transcription...")

        all_segments = []

        for idx, (chunk_path, time_offset) in enumerate(chunk_files, 1):
            print(f"Transcribing chunk {idx}/{total_chunks} (offset={time_offset:.1f}s)...")

            with open(chunk_path, "rb") as audio_file:
                transcript = safe_transcribe(
                    client,
                    file=audio_file,
                    model="gpt-4o-transcribe-diarize",
                    response_format="diarized_json",
                    chunking_strategy="auto",
                    known_speaker_names=known_speaker_names,
                    known_speaker_references=known_speaker_references,
                )

            # Shift timestamps so they are relative to the full audio, not just this chunk
            for seg in transcript.segments:
                seg.start += time_offset
                seg.end += time_offset
                all_segments.append(seg)

        print(f"Transcription complete. Total segments: {len(all_segments)}")

        utterances = [
            {
                "speaker": seg.speaker,
                "text": seg.text.strip(),
                "start": seg.start,
                "end": seg.end,
            }
            for seg in all_segments
        ]

        print(f"Segments detected: {len(utterances)}")

        formatted_transcript, summary_section, action_items = \
            format_transcript_with_llm(utterances)

        response_data["utterances"] = utterances
        response_data["formatted_transcript"] = formatted_transcript

        if save_files:

            existing = sorted(settings.output_folder.glob("output_*_diarized.json"))
            next_index = len(existing) + 1

            base = f"output_{next_index}"

            diarized_path = settings.output_folder / f"{base}_diarized.json"

            txt_path = settings.output_folder / f"{base}_transcript.txt"
            formatted_path = settings.output_folder / f"{base}_formatted.md"
            mom_path = settings.output_folder / f"{base}_mom.md"

            final_json = {
                "source_url": audio_url,
                "timestamp": datetime.now().isoformat(),
                "chunks": total_chunks,
                "utterances": utterances,
            }

            with open(diarized_path, "w", encoding="utf-8") as f:
                json.dump(final_json, f, indent=2, ensure_ascii=False)

            transcript_text = "\n".join(
                f"{u['speaker']}: {u['text']}" for u in utterances
            )

            with open(txt_path, "w", encoding="utf-8") as f:
                f.write(transcript_text)

            with open(formatted_path, "w", encoding="utf-8") as f:
                f.write(formatted_transcript)

            with open(mom_path, "w", encoding="utf-8") as f:
                f.write(summary_section)

            response_data["saved_files"] = {
                "diarized_json": str(diarized_path),
                "transcript_txt": str(txt_path),
                "formatted_md": str(formatted_path),
                "mom_md": str(mom_path)
            }

            response_data["output_index"] = next_index

        response_data["message"] = "Success"
        return response_data

    except Exception as e:
        traceback.print_exc()
        raise e

    finally:
        # Delete chunk files produced by split_audio (skip original temp file)
        for chunk_path, _ in chunk_files:
            if chunk_path != temp_path and os.path.exists(chunk_path):
                try:
                    os.remove(chunk_path)
                except Exception as cleanup_err:
                    print(f"Warning: Could not delete chunk file {chunk_path}: {cleanup_err}")

        # Delete the downloaded temp file (retry on Windows file-lock)
        if os.path.exists(temp_path):
            import time as _time
            for i in range(3):
                try:
                    os.remove(temp_path)
                    break
                except PermissionError:
                    if i < 2:
                        _time.sleep(1)
                    else:
                        print(f"Warning: Could not delete temp file {temp_path} after retries.")
                except Exception as del_err:
                    print(f"Warning: Could not delete temp file {temp_path}: {del_err}")
                    break