import os
from app.utils.audio_utils import audio_to_data_url

SAMPLES_DIR = "app/data/speaker_samples"

known_speaker_names = []
known_speaker_references = []

def load_speaker_samples():

    global known_speaker_names, known_speaker_references

    for file in os.listdir(SAMPLES_DIR):

        if file.endswith((".wav",".mp3",".m4a",".ogg")):

            name = os.path.splitext(file)[0]
            path = os.path.join(SAMPLES_DIR,file)

            known_speaker_names.append(name)
            known_speaker_references.append(audio_to_data_url(path))

    print("Speakers:", known_speaker_names)
    print("Samples loaded:", len(known_speaker_references))

load_speaker_samples()