import re
from app.utils.common import timestamp_to_seconds

def parse_vtt_transcript(vtt_content: str) -> list:
    """
    Robust parser for Microsoft Teams VTT transcripts.
    Supports <v Speaker>text</v> and ignores cue IDs.
    """
    utterances = []
    lines = vtt_content.splitlines()
    i = 0

    # Regex to extract speakers in <v Name> format
    speaker_tag = re.compile(r"<v\s+([^>]+)>(.*?)</v>", re.DOTALL)

    while i < len(lines):
        line = lines[i].strip()

        # Skip cue ID lines (Teams uses GUID/NN)
        if re.match(r'^[A-Za-z0-9\-]+\/\d+-\d+$', line):
            i += 1
            continue

        # Timestamp line
        if "-->" in line:
            try:
                start_ts, end_ts = line.split("-->")
                start_seconds = timestamp_to_seconds(start_ts.strip())
                end_seconds = timestamp_to_seconds(end_ts.strip())
            except:
                i += 1
                continue

            # Next line should contain <v Speaker> text
            if i + 1 < len(lines):
                next_line = lines[i+1].strip()

                # Match <v Speaker>sentence</v>
                m = speaker_tag.search(next_line)
                if m:
                    speaker = m.group(1).strip()
                    text = m.group(2).strip()

                    utterances.append({
                        "speaker": speaker,
                        "text": text,
                        "start": start_seconds,
                        "end": end_seconds
                    })

                    i += 2
                    continue

        i += 1

    return utterances
