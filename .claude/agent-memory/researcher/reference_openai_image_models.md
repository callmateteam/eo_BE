---
name: OpenAI Image Generation API Models
description: Model availability, pricing, resolutions, and quality notes for DALL-E 2, DALL-E 3, gpt-image-1 — researched for EO project storyboard image generation feature
type: reference
---

# OpenAI Image Generation API Models (as of ~August 2025)

## Models Available via API

### DALL-E 2
- Endpoint: POST /v1/images/generations (model: "dall-e-2")
- Also: /v1/images/edits, /v1/images/variations
- Resolutions: 256x256, 512x512, 1024x1024 (square only)
- Pricing: $0.016 / $0.018 / $0.020 per image

### DALL-E 3
- Endpoint: POST /v1/images/generations (model: "dall-e-3")
- Resolutions: 1024x1024, 1024x1792, 1792x1024
- Quality: standard | hd
- Style param: vivid | natural
- No inpainting/variations support
- Pricing (standard): $0.040 / $0.080 per image; (hd): $0.080 / $0.120 per image

### gpt-image-1 (new as of Spring 2025)
- Endpoint: POST /v1/images/generations AND /v1/images/edits
- Resolutions: 1024x1024, 1024x1536, 1536x1024, auto
- Quality: low | medium | high | auto
- Token-based pricing: low ~$0.011, medium ~$0.042, high ~$0.167 per image
- Accepts image input (reference images for character consistency)
- Best instruction-following and text rendering of all three models
- May require org verification/allowlisting

## Quality Ranking for Anime/Illustration Style
1. gpt-image-1 (high) — best style fidelity, accepts reference images
2. DALL-E 3 (hd, vivid) — good fallback, no reference image support
3. DALL-E 2 — not recommended for high-quality anime work

## Key Notes for EO Project
- gpt-image-1's /v1/images/edits supports passing existing character imageUrl as reference
- This is critical for CustomCharacter consistency across storyboard scenes
- fal.ai (already used in project) may offer better anime LoRA models at lower cost — worth benchmarking
- Check platform.openai.com/docs/models for post-August 2025 additions

## Knowledge Cutoff Warning
- Researched: August 2025 cutoff
- Models/pricing released after August 2025 are UNKNOWN
- Always verify at: https://platform.openai.com/docs/models and https://openai.com/api/pricing/
