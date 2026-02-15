from pydub import AudioSegment
import math

# Max duration for chunking (20 minutes recommended < 23 min)
MAX_CHUNK_DURATION_MS = 20 * 60 * 1000

def split_audio(file_path: str):
    audio = AudioSegment.from_file(file_path)
    duration_ms = len(audio)

    if duration_ms <= MAX_CHUNK_DURATION_MS:
        return [(file_path, 0)]

    chunks = []
    num_chunks = math.ceil(duration_ms / MAX_CHUNK_DURATION_MS)

    for i in range(num_chunks):
        start = i * MAX_CHUNK_DURATION_MS
        end = min((i + 1) * MAX_CHUNK_DURATION_MS, duration_ms)

        chunk = audio[start:end]
        chunk_path = f"{file_path}_chunk_{i+1}.mp3"
        chunk.export(chunk_path, format="mp3")

        chunks.append((chunk_path, start / 1000))

    return chunks
