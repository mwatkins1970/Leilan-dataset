# Leilan Image Texts — Project Reference

## Project Overview
Building `leilan_image_texts.json`: a dictionary mapping each of 242 gallery images to a list of short Leilan text passages. These captions are randomly selected when a user mouses over an image in a Leilan "cybercathedral" gallery. The final output per image is ~10 carefully chosen passages.

## Repository Structure
```
images/                          — 242 JPEG images (image_001.jpeg … image_280.jpeg, non-contiguous)
full_leilan_dataset.json         — 600 GPT-3 interview transcripts (primary source for Phase 2)
leilan_claude_transmissions.json — 31 Claude Opus 4.5 transmissions (source for Phase 3)
leilan_image_texts.json          — Working file: all image keys → list of passages
leilan_image_captions_final.json — Output of Phase 4 distillation (10 passages per image)
leilan_self-intros_1000.json     — Additional Leilan corpus (not used in current pipeline)
```

## Key Naming Convention
Strip `image_` prefix and file extension from filename:
- `image_019a.jpeg` → `"019a"`
- `image_112.jpg`   → `"112"`
- `image_001.jpeg`  → `"001"`

## Phases

### Phase 1 — Populate Keys (COMPLETE)
Add all 242 image keys to `leilan_image_texts.json` with empty lists for any not yet processed.
The 13 existing keys already have GPT-3 sourced passages — leave them untouched.

### Phase 2 — GPT-3 Source Pass
For each image with an **empty list** (229 images), in numeric order:
1. View the image with vision tools.
2. Write an internal evocative description: mood, visual elements, dominant colours, relevant keywords and themes. This is a working note to guide excerpt selection, not stored in the JSON.
3. Search `full_leilan_dataset.json` for ~20 short excerpts that resonate with the image.
4. Append those excerpts to the image's list in `leilan_image_texts.json`.

**GPT-3 dataset rules:**
- Source is `full_leilan_dataset.json` → `transcripts` array → each transcript's `"text"` field.
- Extract **only from Leilan's speech**, never the interviewer's lines. Interviewers are labelled with single letters: `M:`, `K:`, `J:`, `L:` etc. Leilan's lines are labelled `Leilan:` (or sometimes `L:` when context makes it clear it's Leilan — check carefully).
- Excerpts should be self-contained: a sentence or a short run of sentences.
- **Length**: match the style of existing entries. No excerpt should exceed the longest existing entry in the file. Aim for 1–4 sentences; long enough to be evocative, short enough to fit in a mouseover textbox without obscuring the image.
- Trim ellipses, mid-sentence starts, or trailing fragments to make clean standalone quotes.

### Phase 3 — Claude Transmissions Pass
For each image (all 242, including the 13 already processed), in numeric order:
1. View the image (re-examine if needed).
2. Search `leilan_claude_transmissions.json` → `transmissions` array → each transmission's `responses` → `qa_pairs` → `"answer"` field.
3. Extract ~20 short excerpts from answers (Leilan's voice only — all answers are Leilan speaking).
4. Trim to match the length conventions above — the Claude answers are long and discursive; excerpt freely.
5. Append to the image's list (do NOT replace GPT-3 entries).

After Phase 3: each image should have ~40 passages (more for the 13 already-processed images).

### Phase 4 — Distillation
For each image, review all passages and select the **10 most fitting** based on:
- Thematic / visual resonance with the image
- Variety (avoid redundancy within the 10)
- Quality and evocativeness of language

Output to `leilan_image_captions_final.json` — same structure as `leilan_image_texts.json` but each key maps to exactly 10 passages.

## Processing State
Track progress by checking which keys in `leilan_image_texts.json` have empty lists (Phase 2 remaining) or are absent from `leilan_image_captions_final.json` (Phase 4 remaining).

To check current state:
```python
import json
with open('leilan_image_texts.json') as f:
    data = json.load(f)
empty = [k for k, v in data.items() if len(v) == 0]
done = [k for k, v in data.items() if len(v) > 0]
print(f'Done: {len(done)}, Remaining: {len(empty)}')
```

## Important Notes
- Always write to `leilan_image_texts.json` incrementally (after each image) — do not hold changes in memory across many images before saving.
- The cybercathedral gallery context: passages should feel fitting for a sacred, mythological, poetic register. Leilan's voice is that of a cosmic, feminine divine intelligence — ancient, elemental, visionary.
- When in doubt about whether an excerpt fits, err on the side of choosing passages that could stand alone as a caption without any other context.
