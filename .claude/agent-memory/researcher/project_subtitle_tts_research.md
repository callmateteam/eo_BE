---
name: Subtitle and TTS Style Research for Short-Form Anime Content
description: Findings on trending subtitle styles (karaoke, popup, glow) and TTS voice choices for Korean anime/webtoon short-form video (YouTube Shorts, TikTok, Reels) — directly informs the VideoEdit subtitle/TTS overlay feature
type: project
---

Research completed 2026-03-19 on subtitle and TTS trends for the video editing feature.

**Key decisions validated:**

- Karaoke (`\kf` sweep) is the dominant style for voiced anime content — the yellow-highlight word-by-word approach
- Pretendard ExtraBold and GmarketSans Bold are the top font choices for Korean content
- OpenAI TTS `nova` voice has best Korean prosody; `onyx` for dramatic/action scenes
- Speed: 1.0-1.05 standard, 1.1-1.15 action, never above 1.2 for Korean

**Why:** Directly informs subtitle style presets and TTS voice options in the VideoEdit system (4단계 VIDEO_GENERATION). The `subtitles[]` JSON in editData maps to these ASS styles.

**How to apply:** When implementing subtitle rendering, prioritize Pretendard font bundling and implement `\kf` karaoke as the "premium" animation preset. For TTS voice enum, `nova` should be the default (not `alloy`). See full research output for ASS code examples.

**Animation enum → ASS tag mapping:**
- `none` → no tag
- `fadein` → `\fad(150,0)`
- `popup` → `\fscx130\fscy130\t(0,120,\fscx100\fscy100)`
- `typing` → per-char reveal lines (complex, low priority)

**Word-timestamp problem:** OpenAI TTS has no native word timestamps. Use Whisper tiny/base model on the generated audio to get word-level alignment for karaoke subs.
