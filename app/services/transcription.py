import time
from openai import InternalServerError, APITimeoutError

def safe_transcribe(client, **kwargs):
    """
    Retry wrapper for OpenAI transcription API.
    Retries on InternalServerError or connection resets.
    """
    max_retries = 5
    base_delay = 3  # seconds

    for attempt in range(1, max_retries + 1):
        try:
            return client.audio.transcriptions.create(**kwargs)

        except (InternalServerError, APITimeoutError) as e:
            print(f"[OpenAI ERROR] Attempt {attempt}/{max_retries} failed: {e}")
            if attempt == max_retries:
                raise
            time.sleep(base_delay * attempt)  # exponential backoff

        except Exception as e:
            # If it's a connection reset or upstream disconnect
            msg = str(e).lower()
            if "connect error" in msg or "disconnect" in msg or "reset" in msg:
                print(f"[NETWORK ERROR] Attempt {attempt}/{max_retries} failed: {e}")
                if attempt == max_retries:
                    raise
                time.sleep(base_delay * attempt)
            else:
                raise  # real fatal error → do not retry


def group_speaker_transcript(response_json):
    speaker_transcripts = []
    last_speaker = None

    words = response_json["results"]["channels"][0]["alternatives"][0]["words"]

    for word in words:
        speaker = word["speaker"]
        text = word["word"]

        if speaker != last_speaker:
            speaker_transcripts.append({
                "speaker": speaker,
                "text": text
            })
        else:
            speaker_transcripts[-1]["text"] += " " + text

        last_speaker = speaker

    return speaker_transcripts
