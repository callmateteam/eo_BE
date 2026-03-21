"""최종 영상 합성 서비스 - FFmpeg로 장면 영상 + TTS + 자막 합본"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.s3 import upload_video

logger = logging.getLogger(__name__)

# BGM 프리셋: bgmMood → S3 키 매핑
BGM_PRESETS: dict[str, str] = {
    "energetic": "bgm/energetic.mp3",
    "calm": "bgm/calm.mp3",
    "dramatic": "bgm/dramatic.mp3",
    "happy": "bgm/happy.mp3",
    "sad": "bgm/sad.mp3",
    "mysterious": "bgm/mysterious.mp3",
    "epic": "bgm/epic.mp3",
    "romantic": "bgm/romantic.mp3",
    "funny": "bgm/funny.mp3",
    "horror": "bgm/horror.mp3",
}


def _get_bgm_url(bgm_mood: str | None) -> str | None:
    """bgmMood → S3 BGM URL 변환"""
    if not bgm_mood:
        return None
    key = BGM_PRESETS.get(bgm_mood.lower())
    if not key:
        return None
    bucket = settings.S3_BUCKET
    region = settings.AWS_REGION
    return f"https://{bucket}.s3.{region}.amazonaws.com/{key}"


@dataclass
class SceneInput:
    """합성할 장면 입력 데이터"""

    scene_order: int
    video_url: str
    duration: float
    narration: str | None = None
    narration_style: str = "none"
    narration_url: str | None = None


async def _download(url: str, dest: str) -> None:
    """URL에서 파일 다운로드"""
    async with httpx.AsyncClient(timeout=120) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)


def _generate_srt(scenes: list[SceneInput]) -> str:
    """장면별 나레이션 텍스트를 SRT 자막으로 변환

    긴 자막은 10자 단위로 분할하여 시간 분배.
    """
    srt_lines: list[str] = []
    idx = 0
    elapsed = 0.0
    max_chars = 10  # 한 자막당 최대 글자 수

    for scene in scenes:
        if not scene.narration or scene.narration_style == "none":
            elapsed += scene.duration
            continue

        text = scene.narration.strip()

        # 짧으면 그대로
        if len(text) <= max_chars:
            idx += 1
            srt_lines.append(str(idx))
            srt_lines.append(
                f"{_seconds_to_srt_ts(elapsed)} --> "
                f"{_seconds_to_srt_ts(elapsed + scene.duration)}"
            )
            srt_lines.append(text)
            srt_lines.append("")
        else:
            # 긴 자막 → 10자 단위로 분할, 시간 균등 배분
            chunks = _split_text(text, max_chars)
            chunk_dur = scene.duration / len(chunks)
            for i, chunk in enumerate(chunks):
                idx += 1
                c_start = elapsed + i * chunk_dur
                c_end = elapsed + (i + 1) * chunk_dur
                srt_lines.append(str(idx))
                srt_lines.append(
                    f"{_seconds_to_srt_ts(c_start)} --> "
                    f"{_seconds_to_srt_ts(c_end)}"
                )
                srt_lines.append(chunk)
                srt_lines.append("")

        elapsed += scene.duration

    return "\n".join(srt_lines)


def _split_text(text: str, max_chars: int) -> list[str]:
    """텍스트를 max_chars 단위로 자연스럽게 분할"""
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    # 띄어쓰기/쉼표/마침표 기준으로 끊기
    current = ""
    for ch in text:
        current += ch
        if len(current) >= max_chars and ch in (" ", ",", ".", "!", "?", "~"):
            chunks.append(current.strip())
            current = ""
    if current.strip():
        chunks.append(current.strip())
    return chunks if chunks else [text]


def _seconds_to_srt_ts(seconds: float) -> str:
    """초 → SRT 타임스탬프 (HH:MM:SS,mmm)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds % 1) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


async def merge_storyboard_video(
    scenes: list[SceneInput],
    user_id: str,
    bgm_mood: str | None = None,
    progress_callback: Callable[[int, str], Awaitable[None]] | None = None,
) -> str:
    """장면 영상들을 하나의 최종 영상으로 합성

    1. 장면별 영상 다운로드
    2. TTS 오디오 + BGM 다운로드
    3. 자막(SRT) 생성
    4. FFmpeg로 합성: concat + TTS 믹스 + BGM 믹스 + 자막 번인
    5. S3 업로드 → URL 반환
    """

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            await progress_callback(pct, step)

    sorted_scenes = sorted(scenes, key=lambda s: s.scene_order)

    with tempfile.TemporaryDirectory(prefix="eo_merge_") as tmpdir:
        await notify(5, "영상 다운로드 중...")

        # 1) 장면 영상 다운로드
        video_files: list[str] = []
        for i, scene in enumerate(sorted_scenes):
            vpath = os.path.join(tmpdir, f"scene_{i:03d}.mp4")
            await _download(scene.video_url, vpath)
            video_files.append(vpath)

        await notify(20, "오디오 다운로드 중...")

        # 2) TTS 오디오 다운로드
        audio_files: dict[int, str] = {}
        for i, scene in enumerate(sorted_scenes):
            if scene.narration_url and scene.narration_style != "none":
                apath = os.path.join(tmpdir, f"audio_{i:03d}.mp3")
                await _download(scene.narration_url, apath)
                audio_files[i] = apath

        # 2b) BGM 다운로드
        bgm_path: str | None = None
        bgm_url = _get_bgm_url(bgm_mood)
        if bgm_url:
            bgm_path = os.path.join(tmpdir, "bgm.mp3")
            try:
                await _download(bgm_url, bgm_path)
            except Exception:
                logger.warning("BGM 다운로드 실패: %s", bgm_url)
                bgm_path = None

        await notify(30, "자막 생성 중...")

        # 3) SRT 자막 파일 생성
        srt_content = _generate_srt(sorted_scenes)
        srt_path = os.path.join(tmpdir, "subtitles.srt")
        with open(srt_path, "w", encoding="utf-8") as f:
            f.write(srt_content)

        await notify(35, "영상 합성 중...")

        # 4) FFmpeg 합성
        output_path = os.path.join(tmpdir, f"final_{uuid.uuid4().hex}.mp4")

        # 4a) 영상 concat 목록
        concat_list = os.path.join(tmpdir, "concat.txt")
        with open(concat_list, "w") as f:
            for vf in video_files:
                f.write(f"file '{vf}'\n")

        # 4b) 장면 결합 — crossfade 전환 효과 적용
        concat_video = os.path.join(tmpdir, "concat.mp4")
        if len(video_files) >= 2:
            await _concat_with_crossfade(video_files, concat_video, fade_duration=0.4)
        else:
            concat_cmd = [
                "ffmpeg", "-y",
                "-f", "concat", "-safe", "0",
                "-i", concat_list,
                "-c", "copy",
                concat_video,
            ]
            await _run_ffmpeg(concat_cmd)

        await notify(50, "오디오 믹싱 중...")

        # 4c) TTS 오디오 믹스
        if audio_files:
            tts_mixed = os.path.join(tmpdir, "tts_mixed.mp4")
            mix_cmd = _build_audio_mix_cmd(
                concat_video,
                sorted_scenes,
                audio_files,
                tts_mixed,
            )
            await _run_ffmpeg(mix_cmd)
        else:
            tts_mixed = concat_video

        # 4d) BGM 믹스 (TTS 있으면 자동 덕킹)
        if bgm_path:
            await notify(60, "BGM 믹싱 중...")
            mixed_video = os.path.join(tmpdir, "mixed.mp4")
            bgm_cmd = _build_bgm_mix_cmd(
                tts_mixed,
                bgm_path,
                mixed_video,
                has_tts=bool(audio_files),
            )
            await _run_ffmpeg(bgm_cmd)
        else:
            mixed_video = tts_mixed

        await notify(70, "1080x1920 프레임 합성 중...")

        # 4e) 1:1 영상을 1080x1920 프레임 가운데 배치 + 자막 하단 영역
        # 레이아웃: 상단 420px | 가운데 1080x1080 영상 | 하단 420px (자막)
        framed_video = os.path.join(tmpdir, "framed.mp4")
        has_subs = any(s.narration and s.narration_style != "none" for s in sorted_scenes)

        # 1:1 → 1080x1920 가운데 배치 (검정 배경)
        # 자막은 하단 420px 영역에 위치 (MarginV=100으로 하단에서 100px 위)
        if has_subs:
            vf_filter = (
                f"scale=1080:1080:force_original_aspect_ratio=decrease,"
                f"pad=1080:1920:0:420:black,"
                f"subtitles={srt_path}"
                ":force_style='"
                "FontName=Pretendard,"
                "FontSize=20,"
                "Bold=1,"
                "PrimaryColour=&H00FFFFFF,"
                "OutlineColour=&H00000000,"
                "Outline=3,"
                "Shadow=0,"
                "Spacing=2,"
                "Alignment=2,"
                "MarginV=150'"
            )
        else:
            vf_filter = (
                "scale=1080:1080:force_original_aspect_ratio=decrease,"
                "pad=1080:1920:0:420:black"
            )

        frame_cmd = [
            "ffmpeg", "-y",
            "-i", mixed_video,
            "-vf", vf_filter,
            "-c:a", "copy",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "medium",
            "-movflags", "+faststart",
            output_path,
        ]
        await _run_ffmpeg(frame_cmd)

        await notify(85, "업로드 중...")

        # 5) S3 업로드
        with open(output_path, "rb") as f:
            video_data = f.read()

        video_url = await asyncio.to_thread(
            upload_video,
            video_data,
            user_id,
            folder="final-videos",
        )

        await notify(100, "최종 영상 합성 완료!")
        return video_url


def _build_audio_mix_cmd(
    video_path: str,
    scenes: list[SceneInput],
    audio_files: dict[int, str],
    output_path: str,
) -> list[str]:
    """TTS 오디오를 각 장면 시작 시점에 맞춰 믹싱하는 FFmpeg 명령 생성"""
    cmd: list[str] = ["ffmpeg", "-y", "-i", video_path]

    # 오디오 입력 추가
    input_idx = 1
    audio_inputs: list[tuple[int, int, float]] = []  # (ffmpeg_idx, scene_idx, delay)

    elapsed = 0.0
    for i, scene in enumerate(scenes):
        if i in audio_files:
            cmd.extend(["-i", audio_files[i]])
            audio_inputs.append((input_idx, i, elapsed))
            input_idx += 1
        elapsed += scene.duration

    # filter_complex로 딜레이 + 믹스
    filters: list[str] = []
    mix_inputs: list[str] = []

    for ffmpeg_idx, _, delay in audio_inputs:
        delay_ms = int(delay * 1000)
        label = f"a{ffmpeg_idx}"
        filters.append(f"[{ffmpeg_idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        mix_inputs.append(f"[{label}]")

    # 원본 비디오 오디오 (있으면) + TTS 믹스
    n = len(mix_inputs)
    mix_str = "".join(mix_inputs)
    filters.append(f"{mix_str}amix=inputs={n}:normalize=0[aout]")

    filter_complex = ";".join(filters)
    cmd.extend(
        [
            "-filter_complex",
            filter_complex,
            "-map",
            "0:v",
            "-map",
            "[aout]",
            "-c:v",
            "copy",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            output_path,
        ]
    )
    return cmd


def _build_bgm_mix_cmd(
    video_path: str,
    bgm_path: str,
    output_path: str,
    *,
    has_tts: bool = False,
) -> list[str]:
    """BGM을 영상에 배경 볼륨으로 믹싱하는 FFmpeg 명령 생성

    - 기본 BGM 볼륨 0.2
    - TTS 있으면 sidechaincompress로 자동 덕킹
      (나레이션 신호 감지 시 BGM 볼륨 자동 감소)
    - 영상 길이에 맞춰 BGM 자동 루프 + 페이드아웃
    """
    if has_tts:
        # 사이드체인 덕킹: TTS 오디오가 나오면 BGM 서서히 감소/복구
        # attack=1000ms  → TTS 시작 시 BGM이 1초에 걸쳐 천천히 줄어듦
        # release=2000ms → TTS 끝난 후 BGM이 2초에 걸쳐 서서히 복구
        # knee=6dB       → 압축 시작점 전후로 부드러운 곡선 적용
        # ratio=4        → 너무 급격하지 않은 압축 비율
        fc = (
            "[1:a]volume=0.2,afade=t=out:st=-3:d=3[bgm];"
            "[bgm][0:a]sidechaincompress="
            "threshold=0.03:ratio=4:"
            "attack=1000:release=2000:"
            "knee=6:level_sc=1[ducked];"
            "[0:a][ducked]amix=inputs=2:"
            "duration=first:normalize=0[aout]"
        )
    else:
        # TTS 없으면 고정 볼륨으로 깔기
        fc = (
            "[1:a]volume=0.15,afade=t=out:st=-3:d=3[bgm];"
            "[0:a][bgm]amix=inputs=2:"
            "duration=first:normalize=0[aout]"
        )

    return [
        "ffmpeg",
        "-y",
        "-i",
        video_path,
        "-stream_loop",
        "-1",
        "-i",
        bgm_path,
        "-filter_complex",
        fc,
        "-map",
        "0:v",
        "-map",
        "[aout]",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-shortest",
        output_path,
    ]


async def _get_video_duration(path: str) -> float:
    """ffprobe로 영상 길이 조회"""
    cmd = [
        "ffprobe", "-v", "quiet",
        "-show_entries", "format=duration",
        "-of", "default=noprint_wrappers=1:nokey=1",
        path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
    )
    stdout, _ = await proc.communicate()
    try:
        return float(stdout.decode().strip())
    except ValueError:
        return 5.0


async def _concat_with_crossfade(
    files: list[str], output_path: str, fade_duration: float = 0.4
) -> None:
    """crossfade 전환 효과로 영상 결합 (dissolve)"""
    if len(files) < 2:
        return

    current = files[0]
    for i in range(1, len(files)):
        is_last = i == len(files) - 1
        out = output_path if is_last else output_path.replace(".mp4", f"_xf{i}.mp4")

        duration = await _get_video_duration(current)
        offset = max(0, duration - fade_duration)

        cmd = [
            "ffmpeg", "-y",
            "-i", current,
            "-i", files[i],
            "-filter_complex",
            (
                f"[0:v][1:v]xfade=transition=dissolve"
                f":duration={fade_duration}:offset={offset}[v]"
            ),
            "-map", "[v]",
            "-an",
            "-c:v", "libx264",
            "-crf", "18",
            "-preset", "medium",
            out,
        ]
        await _run_ffmpeg(cmd)
        current = out

    logger.info("Crossfade 결합 완료: %d 장면", len(files))


async def _run_ffmpeg(cmd: list[str]) -> None:
    """FFmpeg 명령 실행"""
    logger.info("FFmpeg 실행: %s", " ".join(cmd[:6]))
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    if proc.returncode != 0:
        err = stderr.decode(errors="replace")[-500:]
        raise RuntimeError(f"FFmpeg 실패 (code={proc.returncode}): {err}")
