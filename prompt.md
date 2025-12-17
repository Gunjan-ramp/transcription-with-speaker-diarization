# Transcript Translation and Formatting Prompt

## CRITICAL OUTPUT REQUIREMENTS

**1. OUTPUT FORMAT: Output ONLY raw markdown. DO NOT wrap your response in ```markdown code fences or any other code block formatting. Output the plain markdown text directly.**

**2. COMPLETENESS: You MUST complete ALL sections before finishing your response. Do not stop mid-sentence or mid-section. Every section listed in the Output Format must be completed.**

## CRITICAL REQUIREMENT: 100% ENGLISH OUTPUT ONLY

**ABSOLUTE RULE: The final output MUST contain ZERO words in Hindi, Urdu, or any other non-English language. Every single word must be translated to English.**

## Objective
Transform a multilingual meeting transcript into a professional, **ENGLISH-ONLY** formatted document suitable for email distribution and business communication.

## Input Format
You will receive a JSON object containing transcript segments with the following structure:
- **segments**: Array of conversation segments
- **id**: Unique segment identifier
- **start**: Start timestamp (seconds)
- **end**: End timestamp (seconds)
- **speaker**: Speaker identifier (e.g., "A", "B", "C")
- **text**: Spoken content (may contain multiple languages: English, Hindi, Urdu, or mixed)
- **type**: Segment type (typically "transcript.text.segment")

## Core Requirements

### 1. Language Translation - MANDATORY 100% ENGLISH

**CRITICAL INSTRUCTIONS:**
- **Translate EVERY SINGLE WORD that is not in English to English**
- **NO EXCEPTIONS**: Hindi words, Urdu words, transliterated words - ALL must be translated
- **Double-check**: Before outputting, verify that ZERO non-English words remain
- Maintain the original meaning and context while translating
- Preserve technical terms, product names, and proper nouns (but translate surrounding text)
- Handle code-switching naturally (when speakers mix languages mid-sentence)
- Ensure idiomatic English rather than literal translations
- **If you see words like "hai", "hain", "ka", "ki", "ko", "se", "me", "aur", etc. - these are Hindi/Urdu and MUST be translated**

**Examples of what MUST be translated:**
- "Meeting start kar rahe hain" → "We are starting the meeting"
- "Yeh task complete hai" → "This task is complete"
- "Aaj ka standup" → "Today's standup"
- "Koi issue hai kya?" → "Are there any issues?"

### 2. Speaker Identification - Extract Real Names from Context

**PRIMARY GOAL: Identify actual participant names from the conversation**

#### **Name Extraction Strategy**

**Priority 1: Direct Name Mentions**
Listen for when speakers address each other by name:
- "Ankit, can you update us?"
- "Shalini, what's your status?"
- "Prakar, did you complete that?"
- "Thanks, Vivek"
- "Akhil was asking me..."

**Priority 2: Self-Introductions**
- "This is Ankit speaking"
- "I'm Shalini, and I..."
- "My name is..."

**Priority 3: Third-Person References**
- "Ankit mentioned that..."
- "I spoke with Shalini yesterday"
- "Prakar will handle this"

#### **Name Mapping Process**

1. **Scan the entire transcript** for name mentions
2. **Map names to speaker labels** based on context:
   - If Speaker A says "Ankit, your task..." and Speaker B responds, Speaker B is likely Ankit
   - If Speaker A says "I'm working on..." after being called "Shalini", Speaker A is Shalini
   - Track who responds when a name is called

3. **Maintain consistency**: Once a speaker is identified, use that name throughout

4. **Handle ambiguity carefully**:
   - If multiple people could be the same name, use context clues
   - If uncertain about mapping, keep generic "Speaker A" label

#### **Confidence Levels**

- **High Confidence** (Use real name): Name is clearly mentioned and speaker responds, or self-introduces
  - Example: "Ankit" when Speaker B responds after "Ankit, can you..."
  
- **Medium Confidence** (Use real name with caution): Name mentioned but mapping is somewhat unclear
  - Example: Name mentioned but multiple speakers could match
  
- **Low Confidence** (Use generic label): No clear name mentions or cannot determine mapping
  - Use: "Speaker A", "Speaker B", "Speaker C"

#### **Critical Rules**

- ✅ **DO** use real names when clearly identifiable from conversation
- ✅ **DO** maintain consistency once a name is assigned
- ❌ **DON'T** guess names - if unsure, use "Speaker A/B/C"
- ❌ **DON'T** use role-based labels like "Manager", "Team Lead", "Developer"
- ❌ **DON'T** assign incorrect names - generic labels are better than mistakes

### 3. Professional Formatting

#### Document Structure
```
# Meeting Transcript
**Date:** [Extract from context or use "Not Specified"]
**Duration:** [Calculate from timestamps]
**Participants:** [List all identified speakers]

---

## Conversation

[Formatted transcript content]

---

## Summary
[Optional: Brief meeting summary if context is clear]

## Action Items
[Optional: Extract clear action items mentioned]

## Key Decisions
[Optional: Highlight important decisions made]
```

#### Conversation Formatting Rules

**Speaker Lines:**
- Format: `**[Speaker Name]** ([HH:MM:SS])`
- Include timestamp at the start of each speaker's turn
- Use bold for speaker names

**Content:**
- Group consecutive segments from the same speaker into paragraphs
- Add line breaks between different speakers
- Preserve natural conversation flow

**Timestamps:**
- Convert decimal seconds to HH:MM:SS format
- Show timestamp when speaker changes or after significant pauses (>30 seconds)

**Example:**
```
**Manager** (00:02:11)
Hello? Okay, let's start guys.

**Developer A** (00:11:44)
Sir, I was waiting for you.

**Manager** (00:13:14)
No, don't wait for me. Sometimes I get late, so you all should start without me. I will check on that Excel later on.
```

### 4. Content Enhancement

#### Clean Up Filler Words (Selectively)
- Remove excessive "uh", "um", "hmm" when they don't add meaning
- Keep them if they indicate hesitation or thinking that's contextually important

#### Improve Readability
- Fix obvious grammatical errors from speech-to-text
- Add punctuation for clarity
- Break long run-on sentences into readable chunks
- Preserve the speaker's intended meaning

#### Technical Terms
- Capitalize proper nouns (Dataverse, WhatsApp, SQL, API, etc.)
- Maintain technical accuracy
- Spell out acronyms on first use if context allows: "GL (General Ledger) code"

### 5. Context Preservation

**Maintain:**
- All technical discussions and details
- Task assignments and responsibilities
- Deadlines and time commitments
- Questions and answers
- Decisions and agreements

**Clarify:**
- Ambiguous references when possible
- Add [context] in brackets if needed for clarity
- Note [inaudible] or [unclear] for problematic segments

## Output Format

### Primary Output: Formatted Markdown

```markdown
# Meeting Transcript

**Date:** [Date if available]  
**Duration:** [Total duration]  
**Participants:** [Comma-separated list]

---

## Conversation

**[Speaker Name]** (00:00:00)
[Translated and formatted content]

**[Speaker Name]** (00:00:00)
[Translated and formatted content]

---

## Meeting Summary

[2-3 sentence overview of the meeting]

## Key Discussion Points

- [Point 1]
- [Point 2]
- [Point 3]

## Action Items

- [ ] **[Assignee]**: [Task description] - [Deadline if mentioned]
- [ ] **[Assignee]**: [Task description]

## Decisions Made

- [Decision 1]
- [Decision 2]

## Follow-up Required

- [Item 1]
- [Item 2]
```

## Special Handling

### Mixed Language Segments
When a segment contains multiple languages:
1. Translate the entire segment to English
2. Maintain the flow and natural speech pattern
3. Ensure the translation reads naturally, not word-for-word

**Example Input:**
```
"नहीं मेरा wait मत किया करो, क्योंकि होता क्या है न कई बार मैं ऐसे late हो जाता हूँ"
```

**Example Output:**
```
"No, don't wait for me, because what happens is that sometimes I get late like this"
```

### Technical Discussions
- Preserve all technical terms exactly as mentioned
- Maintain code references, file names, and system names
- Keep numerical data accurate (counts, IDs, times)

### Cultural Context
- Translate respectful terms appropriately ("sir" → "sir", "ji" → appropriate context)
- Maintain professional tone markers
- Preserve hierarchical relationships evident in speech

## Quality Checklist

Before finalizing output, verify:

- [ ] All text is in English
- [ ] No untranslated content remains
- [ ] Speaker labels are consistent throughout
- [ ] Timestamps are properly formatted (HH:MM:SS)
- [ ] Technical terms are correctly capitalized
- [ ] Conversation flow is natural and readable
- [ ] Action items are clearly identified
- [ ] Document is properly structured with headers
- [ ] Professional tone is maintained
- [ ] No speaker misidentification (use generic labels if uncertain)

## Edge Cases

### Multiple Speakers Talking Simultaneously
- Note as: `**[Speaker A & Speaker B]** (timestamp)`
- Or separate if distinguishable

### Background Noise/Unclear Audio
- Mark as: `[unclear audio]` or `[inaudible]`
- Don't guess at content

### Very Short Interjections
- Can be combined with previous/next segment if from same speaker
- Example: "Okay", "Yes", "Hmm" can be merged

### Long Monologues
- Break into logical paragraphs
- Add intermediate timestamps every 2-3 minutes
- Use subheadings if topic changes within monologue

## Tone and Style

- **Professional**: Suitable for business communication
- **Clear**: Easy to read and understand
- **Concise**: Remove redundancy while preserving meaning
- **Accurate**: Faithful to original content and intent
- **Neutral**: Objective and unbiased presentation

## Final Notes

- Prioritize clarity over literal translation
- When in doubt about speaker identity, use generic labels
- Maintain confidentiality - this is internal business communication
- The output should be immediately usable in email or documentation
- Focus on making the transcript actionable and easy to reference

---

## 🚨 FINAL VERIFICATION CHECKLIST - BEFORE SUBMITTING OUTPUT

**MANDATORY: Before you provide your final output, verify the following:**

1. ✅ **ZERO Hindi words remain** - Check every single word
2. ✅ **ZERO Urdu words remain** - Check every single word  
3. ✅ **ZERO transliterated words remain** (like "hai", "hain", "ka", "ki", "aur", etc.)
4. ✅ **ALL content is in proper English** - No exceptions
5. ✅ **Re-read the entire output** - If you see ANY non-English word, translate it immediately

**REMEMBER: The recipient of this transcript does NOT speak Hindi/Urdu. Every single word must be in English for them to understand.**

**If you find even ONE non-English word in your output, you have FAILED the task. Go back and translate it.**
