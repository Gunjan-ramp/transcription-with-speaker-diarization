import os
import torch
import torchaudio
from pydub import AudioSegment
from speechbrain.inference.speaker import EncoderClassifier
from speechbrain.utils.fetching import LocalStrategy

# Pretrained model from SpeechBrain (HuggingFace)
CLASSIFIER_MODEL = "speechbrain/spkrec-ecapa-voxceleb"

class SpeakerIdentifier:
    def __init__(self, savedir="tmp_speechbrain"):
        print(f"Loading SpeechBrain model: {CLASSIFIER_MODEL}...")
        self.classifier = EncoderClassifier.from_hparams(
            source=CLASSIFIER_MODEL, 
            run_opts={"device": "cuda" if torch.cuda.is_available() else "cpu"},
            savedir=savedir,
            local_strategy=LocalStrategy.COPY
        )
        print("SpeechBrain model loaded successfully.")

    def get_embedding(self, audio_path):
        """Extracts the speaker embedding from an audio file."""
        signal, fs = torchaudio.load(audio_path)
        
        # SpeechBrain models typically expect 16kHz audio
        if fs != 16000:
            resampler = torchaudio.transforms.Resample(orig_freq=fs, new_freq=16000)
            signal = resampler(signal)
            
        # Ensure mono
        if signal.shape[0] > 1:
            signal = torch.mean(signal, dim=0, keepdim=True)
            
        with torch.no_grad():
            embeddings = self.classifier.encode_batch(signal)
            
        return embeddings.squeeze()

    def compare_embeddings(self, emb1, emb2):
        """Computes cosine similarity between two embeddings."""
        cos = torch.nn.CosineSimilarity(dim=-1, eps=1e-6)
        return cos(emb1, emb2).item()

    def process_sample_audio_folder(self, folder_path):
        """
        Reads all audio files in a folder and generates speaker embeddings.
        Assumes the filename (without extension) is the speaker's name.
        """
        speaker_profiles = {}
        if not os.path.exists(folder_path):
            print(f"Warning: Sample audio folder not found at {folder_path}")
            return speaker_profiles

        for filename in os.listdir(folder_path):
            if filename.endswith((".wav", ".mp3", ".m4a", ".flac", ".ogg")):
                speaker_name = os.path.splitext(filename)[0]
                file_path = os.path.join(folder_path, filename)
                try:
                    emb = self.get_embedding(file_path)
                    speaker_profiles[speaker_name] = emb
                    print(f"Loaded embedding for speaker: {speaker_name}")
                except Exception as e:
                    print(f"Failed to load embedding for {filename}: {e}")
                    
        return speaker_profiles

    def extract_utterance_audio(self, main_audio_path, start_time, end_time, temp_out_path):
        """
        Extracts a segment of audio between start_time and end_time (in seconds)
        and saves it to temp_out_path.
        """
        audio = AudioSegment.from_file(main_audio_path)
        start_ms = int(start_time * 1000)
        end_ms = int(end_time * 1000)
        segment = audio[start_ms:end_ms]
        segment.export(temp_out_path, format="wav")
        return temp_out_path

    def identify_speakers(self, utterances, main_audio_path, sample_audio_folder, similarity_threshold=0.4):
        """
        Maps generic speaker labels in utterances to known participant names based on voice embeddings.
        """
        # 1. Load known speaker profiles
        speaker_profiles = self.process_sample_audio_folder(sample_audio_folder)
        if not speaker_profiles:
            print("No known speaker profiles found. Skipping speaker identification.")
            return utterances

        # 2. Extract embeddings for each generic speaker found in the diarization
        generic_speaker_embeddings = {}
        temp_dir = "temp_segments"
        os.makedirs(temp_dir, exist_ok=True)

        # 2.a. Group continuous utterances by speaker and sort by duration
        from collections import defaultdict
        speaker_utterances = defaultdict(list)
        for utterance in utterances:
            duration = utterance["end"] - utterance["start"]
            if duration > 1.5:
                speaker_utterances[utterance.get("speaker")].append((duration, utterance))

        # 2.b. Compute average embedding up to the top 5 longest speaker utterances
        for speaker_label, utts in speaker_utterances.items():
            # Sort by duration descending to get the longest/best quality segments
            utts.sort(key=lambda x: x[0], reverse=True)
            top_utts = utts[:5]
            
            embeddings = []
            for i, (duration, utterance) in enumerate(top_utts):
                temp_wav = os.path.join(temp_dir, f"temp_{speaker_label}_{i}.wav")
                try:
                    self.extract_utterance_audio(
                        main_audio_path, 
                        utterance["start"], 
                        utterance["end"], 
                        temp_wav
                    )
                    emb = self.get_embedding(temp_wav)
                    embeddings.append(emb)
                    
                    # Clean up temp file
                    if os.path.exists(temp_wav):
                        os.remove(temp_wav)
                except Exception as e:
                    print(f"Failed to extract embedding for {speaker_label} (segment {i}): {e}")
            
            if embeddings:
                # Average all collected embeddings to create a more robust speaker profile
                avg_embedding = torch.mean(torch.stack(embeddings), dim=0)
                generic_speaker_embeddings[speaker_label] = avg_embedding
                print(f"Calculated base embedding for {speaker_label} by averaging {len(embeddings)} segments.")
            else:
                print(f"Could not calculate any embedding for {speaker_label}.")

        # 3. Map generic speakers to known participants
        speaker_mapping = {}
        for generic_label, unknown_emb in generic_speaker_embeddings.items():
            best_match = None
            best_score = -1.0
            
            for known_name, known_emb in speaker_profiles.items():
                score = self.compare_embeddings(unknown_emb, known_emb)
                if score > best_score:
                    best_score = score
                    best_match = known_name
                    
            if best_match and best_score >= similarity_threshold:
                print(f"Match found! {generic_label} -> {best_match} (Score: {best_score:.3f})")
                speaker_mapping[generic_label] = best_match
            else:
                print(f"No strong match for {generic_label}. Best score was {best_score:.3f} for {best_match}.")
                speaker_mapping[generic_label] = generic_label # Keep the original label

        # 4. Update utterances with new speaker names
        identified_utterances = []
        for utterance in utterances:
            new_utt = utterance.copy()
            generic_label = new_utt.get("speaker")
            if generic_label in speaker_mapping:
                new_utt["speaker"] = speaker_mapping[generic_label]
            identified_utterances.append(new_utt)

        return identified_utterances

# Initialize a global instance so we don't reload the model on every request
speaker_identifier = None

def get_speaker_identifier():
    global speaker_identifier
    if speaker_identifier is None:
        speaker_identifier = SpeakerIdentifier()
    return speaker_identifier
