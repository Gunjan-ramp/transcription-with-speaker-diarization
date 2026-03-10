import subprocess
import os

def convert_video_to_wav(video_path):
    wav_path = video_path.replace(".mp4", ".wav")

    cmd = [
        "ffmpeg",
        "-y",
        "-i", video_path,
        "-ac", "1",
        "-ar", "16000",
        wav_path
    ]

    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return wav_path