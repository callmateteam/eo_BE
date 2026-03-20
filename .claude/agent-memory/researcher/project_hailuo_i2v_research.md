---
name: MiniMax Hailuo I2V Prompt Engineering for Anime Characters
description: Research on Hailuo video-01-live prompt best practices, camera syntax, prompt_optimizer parameter, character consistency techniques, and model comparisons (Kling v2.0, Wan 2.1) for 2D anime character short-form video generation
type: project
---

Research completed 2026-03-20.

## Critical Findings

### prompt_optimizer parameter — Most Important API Setting
- Set `prompt_optimizer: false` for anime/2D illustration characters
- When `true` (default), the optimizer rewrites prompts toward photorealism, desaturates anime colors, and overrides 2D art style
- This is the highest-leverage fix if character color drift is occurring

**Why:** MiniMax's optimizer is trained on photorealistic content. Anime characters need raw prompt passthrough.
**How to apply:** Audit the fal.ai API call site (not `prompt_optimizer.py` — that builds text only). Find where `minimax/video-01-live` is called and verify this boolean parameter is `false`.

---

### Optimal Prompt Structure for Hailuo I2V
1. Camera bracket command first: `[Static shot]`, `[Push in]`, `[Pan right]`, etc.
2. Character preservation prefix: "Preserve exact character colors and design from reference image."
3. Motion description only (do NOT describe appearance — image handles that)
4. Brief environment/atmosphere
5. Quality anchor: "smooth animation, consistent character appearance"

Target: 40-80 words. Max: 150 words. Under 100 is better for I2V.

---

### Bracket Camera Syntax — Confirmed Working
Place at START of prompt. Title Case.
- `[Static shot]` — best for character preservation
- `[Push in]` — emotional close-ups
- `[Pull out]` — reveal shots
- `[Pan left]` / `[Pan right]` — following movement
- `[Truck left]` / `[Truck right]` — lateral tracking
- `[Arc shot]` — circular movement
- `[Handheld]` — subtle shake
- `[Crane up]` / `[Crane down]` — vertical movement

---

### Negative Prompts
Hailuo API does NOT support `negative_prompt` parameter. Do not inject "Avoid: ..." into the positive prompt — wastes token budget with no benefit.

---

### Character Consistency — Keyword Effectiveness
High effectiveness: `preserve exact character colors and design`, `maintain consistent character appearance`, `character design unchanged throughout`
Medium: `same art style as reference image`, `consistent character proportions`
Low: `character appearance locked`, `CRITICAL:` all-caps prefix (tokenizer ignores case)

Root causes of color shift:
1. `prompt_optimizer: true` (critical)
2. Including color/appearance words in prompt (model treats as T2V instructions)
3. High-motion prompts force per-frame redraw
4. Franchise/IP character names trigger hallucination toward canonical design

---

### Motion Intensity Levels
- Level 0 (ambient): breathing, blinking, hair sway — max fidelity
- Level 1 (minimal): head turn, hand raise — high fidelity
- Level 2 (moderate): walking, cooking, sitting — medium fidelity
- Level 3 (high): running, fighting — use [Static shot] camera to compensate

Current `MOTION_ENHANCERS` in prompt_optimizer.py uses "subtle", "gentle", "minimal" language — this is well-calibrated.

---

### Model Comparison for Anime I2V (fal.ai)

| Model | Anime Fidelity | Motion | Speed | Cost/5s |
|-------|---------------|--------|-------|---------|
| MiniMax Hailuo video-01-live | Good | Good | 3-5 min | ~$0.06 |
| Kling v2.0 | Very Good | Excellent | 4-7 min | ~$0.10 |
| Wan 2.1 | Excellent | Good | 5-10 min | ~$0.04 |

- **Kling v2.0**: Best character lock-in for complex/intricate designs. Best for protagonist/recurring characters.
- **Wan 2.1**: Best native 2D/anime fidelity (open-source, anime-biased training). Best for stylistically extreme characters.
- **Hailuo**: Best camera control (bracket syntax). Best balanced choice.

Recommendation: Use Kling for main character scenes, Hailuo for scenes where camera movement matters. Wan 2.1 if latency is acceptable.

---

### Prompt Examples (production-ready)

**Talking/reaction (level 0-1 motion):**
```
[Static shot] Preserve exact character colors and design from reference image.
Character smiles warmly and nods slightly, gentle hair movement,
soft indoor lighting. Smooth animation, consistent character appearance.
```

**Walking (level 2 motion):**
```
[Pan right] Maintain consistent character colors and art style.
Character walks forward at a relaxed pace, subtle arm swing,
gentle weight shift. Smooth fluid motion, character design unchanged.
```

**Cooking (level 2 motion):**
```
[Static shot] Preserve character design from reference image.
Character stirs a pot with slow rhythmic arm movement,
gentle wrist rotation, minimal body movement, warm kitchen lighting.
Character appearance consistent throughout.
```

**Action (level 3 motion — higher risk):**
```
[Truck right] Maintain character colors and proportions.
Character draws sword with controlled motion, determined expression,
wind effects on hair and clothing. Smooth animation, character design preserved.
```

**Emotional close-up:**
```
[Push in] Preserve exact character colors, eyes, and facial features.
Character looks up with a gentle expression, slight eye movement,
soft natural lighting. Smooth animation, consistent face throughout.
```

---

## Pending Audit Items
1. Verify `prompt_optimizer: false` in fal.ai call site (file location unknown — not `fal_client.py`)
2. Consider Kling v2.0 as primary for main character scenes
3. Camera bracket commands should appear at start, not end (verify current ordering in build_hailuo_prompt)
