import json
import math
from pathlib import Path
from datetime import datetime
from app.core.config import settings
from app.core.openai_client import client
from app.utils.common import format_timestamp

# Helper: Load prompt from file
def load_prompt() -> str:
    """Load the formatting prompt from prompt.md file."""
    prompt_path = Path(__file__).parent / "prompt.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: prompt.md not found at {prompt_path}")
        return ""
    except Exception as e:
        print(f"Warning: Error loading prompt.md: {e}")
        return ""


# Helper: Load MoM prompt from file
def load_mom_prompt() -> str:
    """Load the MoM formatting prompt from mom_prompt.md file."""
    prompt_path = Path(__file__).parent / "mom_prompt.md"
    try:
        with open(prompt_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        print(f"Warning: mom_prompt.md not found at {prompt_path}")
        return ""
    except Exception as e:
        print(f"Warning: Error loading mom_prompt.md: {e}")
        return ""


def format_transcript_with_llm(utterances: list, participants: str = None) -> str:
    """
    Use LLM to format transcript professionally using instructions from prompt.md.
    Uses chunking to avoid output token limits.
    """
    if not settings.enable_llm_formatting:
        return "\n".join([
            f"[{format_timestamp(u['start'])}] {u['speaker']}: {u['text']}"
            for u in utterances
        ])
    
    # Load base prompt
    prompt_instructions = load_prompt()
    if not prompt_instructions:
        print("Warning: Using simple format due to prompt loading failure")
        fallback = "\n".join([
            f"[{format_timestamp(u['start'])}] {u['speaker']}: {u['text']}"
            for u in utterances
        ])
        return fallback, "", []  # Return empty summary/actions as fallback
    
    # Calculate metadata
    current_date = datetime.now().strftime("%B %d, %Y")
    if utterances:
        total_duration_seconds = max(u['end'] for u in utterances)
        hours = int(total_duration_seconds // 3600)
        minutes = int((total_duration_seconds % 3600) // 60)
        duration_str = f"{hours} hour{'s' if hours != 1 else ''}, {minutes} minute{'s' if minutes != 1 else ''}" if hours > 0 else f"{minutes} minute{'s' if minutes != 1 else ''}"
        unique_speakers = sorted(set(u['speaker'] for u in utterances))
        participants_str = ", ".join(unique_speakers)
    else:
        duration_str, participants_str = "Unknown", "Unknown"

    # --- Phase 1: Format Conversation Chunks ---
    formatted_conversation_parts = []
    chunk_size = 50  # Process 50 segments at a time
    total_chunks = math.ceil(len(utterances) / chunk_size)
    
    print(f"Formatting transcript in {total_chunks} chunks...")

    for i in range(total_chunks):
        start_idx = i * chunk_size
        end_idx = min((i + 1) * chunk_size, len(utterances))
        current_chunk = utterances[start_idx:end_idx]
        
        print(f"Processing chunk {i+1}/{total_chunks}...")

        # Prepare context from previous chunk (last 3 items)
        context_str = ""
        if i > 0:
            prev_chunk = utterances[start_idx-3:start_idx]
            context_items = "\n".join([f"{u['speaker']}: {u['text']}" for u in prev_chunk])
            context_str = f"\n\nCONTEXT FROM PREVIOUS CHUNK (DO NOT REPEAT, JUST FOR CONTEXT):\n{context_items}\n"

        chunk_data = {
            "segments": [
                {"speaker": u['speaker'], "text": u['text'], "start": u['start'], "end": u['end']}
                for u in current_chunk
            ]
        }

        # Specific prompt for this chunk
        chunk_system_prompt = prompt_instructions + "\n\n" + \
            (f"PARTICIPANT LIST PROVIDED BY USER: {participants}\n"
             "INSTRUCTION: Attempt to attribute the diarized labels (Speaker 0, Speaker 1, etc.) to these names based on context clues (e.g., self-introductions, being addressed by name). "
             "If you are unsure, keep the generic Speaker label.\n\n" if participants else "") + \
            "SPECIAL INSTRUCTION: Output ONLY the formatted conversation dialogue for the provided segments. " \
            "Do NOT output the metadata header, summary, or action items yet. " \
            "Do NOT wrap in markdown code blocks. Just the designated speaker dialogue lines.\n" \
            "IMPORTANT: Capture every sentence. Do not summarize or skip content even if repetitive. Translate to English if needed but keep the full meaning."

        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": chunk_system_prompt},
                    {"role": "user", "content": f"{context_str}\n\nTranscript Segment Data to Format:\n{json.dumps(chunk_data, ensure_ascii=False)}"}
                ],
                temperature=0.3,
                frequency_penalty=0.5, # Reduce repetition
                presence_penalty=0.3   # Encourage new topics
            )
            
            part = response.choices[0].message.content.strip()
            # Cleanup potential markdown fences if model ignores instruction
            if part.startswith("```markdown"): part = part.replace("```markdown", "", 1)
            if part.startswith("```"): part = part.replace("```", "", 1)
            if part.endswith("```"): part = part[:-3]
            
            formatted_conversation_parts.append(part.strip())

        except Exception as e:
            print(f"Error formatting chunk {i+1}: {e}")
            # Fallback for chunk
            fallback = "\n\n".join([f"**{u['speaker']}** ({format_timestamp(u['start'])})\n{u['text']}" for u in current_chunk])
            formatted_conversation_parts.append(fallback)
    
    full_conversation_text = "\n\n".join(formatted_conversation_parts)

    # --- Phase 2: Generate Summary/Actions/Decisions ---
    print("Generating meeting summary...")
    
    # We send the RAW text for summary generation to save tokens, formatted text is not needed for understanding
    # If raw text is massive, we might need to truncate, but 128k context usually fits.
    # We'll take a simplified approach: Send the full raw transcript
    
    # Load MoM prompt
    mom_instructions = load_mom_prompt()
    if not mom_instructions:
        mom_instructions = prompt_instructions + "\n\n" + \
            "SPECIAL INSTRUCTION: Based on the transcript designated below, generate ONLY the following sections:\n" \
            "1. ## Meeting Summary\n" \
            "2. ## Key Discussion Points\n" \
            "3. ## Action Items\n" \
            "4. ## Decisions Made\n" \
            "5. ## Follow-up Required\n\n" \
            "Do NOT output the metadata header or the conversation dialogue. Just these summary sections."

    # Convert all utterances to a simple string for the summary model
    full_raw_text = "\n".join([f"{u['speaker']}: {u['text']}" for u in utterances])
    
    action_items = []
    summary_section = "## Meeting Summary\n\n(Summary generation failed)."

    try:
        # We'll ask for JSON to get both the Markdown content AND structured data
        system_instruction = (
            "You are a professional meeting secretary. You need to generate a meeting summary based on the transcript.\n"
            "Output MUST be in JSON format with the following keys:\n"
            "1. 'summary_markdown': The full markdown text containing Meeting Summary, Key Points, Action Items, Decisions, etc. (Formatted as requested)\n"
            "2. 'action_items': A list of objects, each having {'title': str, 'description': str, 'assigned_to': str, 'priority': str}\n"
            "\n"
            f"Here are the specific formatting instructions for the 'summary_markdown':\n{mom_instructions}"
        )

        response = client.chat.completions.create(
            model=settings.llm_model,
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": f"Full Transcript:\n{full_raw_text}"}
            ],
            temperature=0.3,
            response_format={"type": "json_object"}
        )
        
        content = response.choices[0].message.content.strip()
        data = json.loads(content)
        
        summary_section = data.get("summary_markdown", "")
        action_items = data.get("action_items", [])
        
    except Exception as e:
        print(f"Error generating summary/actions: {e}")
        # Fallback to text-only generation if JSON fails
        try:
            response = client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": mom_instructions},
                    {"role": "user", "content": f"Full Transcript:\n{full_raw_text}"}
                ],
                temperature=0.3
            )
            summary_section = response.choices[0].message.content.strip()
            # Cleanup potential markdown fences
            if summary_section.startswith("```markdown"): summary_section = summary_section.replace("```markdown", "", 1)
            if summary_section.startswith("```"): summary_section = summary_section.replace("```", "", 1)
            if summary_section.endswith("```"): summary_section = summary_section[:-3]
        except Exception as e2:
             print(f"Fallback summary generation failed: {e2}")

    # --- Phase 3: Assembly ---
    
    # Fallback: Extraction from Markdown if JSON failed or returned empty list
    if not action_items and summary_section:
        print("Attempting to extract action items from Markdown summary...")
        import re
        try:
            # Find the Action Items section
            # Looking for "# Action Items" or "## Action Items"
            match = re.search(r"#+\s*Action Items\s*\n(.*?)(?=\n#|\Z)", summary_section, re.DOTALL | re.IGNORECASE)
            if match:
                content = match.group(1)
                # Find lines starting with bullet points
                lines = re.findall(r"^[•-]\s*(.*)", content, re.MULTILINE)
                for line in lines:
                    line = line.strip()
                    if not line: continue
                    
                    # Try to extract name
                    # Format: [Name] will [Task] or [Name]: [Task]
                    assigned_to = ""
                    title = line
                    
                    # Naive name extraction: Look for "Name will..." or "Name: ..."
                    name_match = re.match(r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?)\s+(?:will|to|should)\s+(.*)", line, re.IGNORECASE)
                    if not name_match:
                         name_match = re.match(r"^([A-Z][a-z]+(?:\s[A-Z][a-z]+)?):\s+(.*)", line)
                         
                    if name_match:
                        assigned_to = name_match.group(1)
                        title = name_match.group(2)
                    
                    action_items.append({
                        "title": title,
                        "description": line,
                        "assigned_to": assigned_to,
                        "priority": "Medium"
                    })
            print(f"Extracted {len(action_items)} action items from Markdown.")
        except Exception as e:
            print(f"Regex extraction failed: {e}")
    final_output = f"""# Meeting Transcript

**Date:** {current_date}
**Duration:** {duration_str}
**Participants:** {participants_str}

---

## Conversation

{full_conversation_text}

---

{summary_section}
"""
    return final_output, summary_section, action_items
