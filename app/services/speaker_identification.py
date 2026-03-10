import os
import torch
import torchaudio
from pyannote.audio.pipelines.speaker_verification import PretrainedSpeakerEmbedding
from sklearn.metrics.pairwise import cosine_similarity

embedding_model = PretrainedSpeakerEmbedding(
    "speechbrain/spkrec-ecapa-voxceleb",
    device="cpu"
)

TARGET_SAMPLE_RATE = 16000


def get_embedding(audio_path):
    waveform, sr = torchaudio.load(audio_path)

    # convert to mono
    if waveform.shape[0] > 1:
        waveform = waveform.mean(dim=0, keepdim=True)

    # add batch dimension
    waveform = waveform.unsqueeze(0)

    emb = embedding_model(waveform)

    if isinstance(emb, torch.Tensor):
        emb = emb.detach().cpu().numpy()

    return emb


def load_speaker_samples(folder):

    speaker_embeddings = {}

    for file in os.listdir(folder):
        if file.endswith(".wav"):
            name = os.path.splitext(file)[0]
            path = os.path.join(folder, file)

            speaker_embeddings[name] = get_embedding(path)

    return speaker_embeddings


def match_speaker(embedding, speaker_db, threshold=0.65):

    best_match = "Unknown"
    best_score = -1

    for name, ref_embedding in speaker_db.items():

        score = cosine_similarity(
            embedding.reshape(1, -1),
            ref_embedding.reshape(1, -1)
        )[0][0]

        if score > best_score:
            best_score = score
            best_match = name

        print("Speaker match score:", name, score)

    if best_score < threshold:
        return "Unknown"

    return best_match