import torchaudio


def extract_segment(source_audio, start, end, out_path):

    waveform, sr = torchaudio.load(source_audio)

    start_sample = int(start * sr)
    end_sample = int(end * sr)

    segment = waveform[:, start_sample:end_sample]

    torchaudio.save(out_path, segment, sr)

    return out_path