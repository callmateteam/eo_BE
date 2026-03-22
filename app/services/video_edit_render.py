"""편집 기반 최종 렌더링 파이프라인 (ffmpeg)"""

from __future__ import annotations

import asyncio
import logging
import os
import tempfile
import uuid
from collections.abc import Awaitable, Callable

import httpx

from app.core.config import settings
from app.core.database import db
from app.core.s3 import upload_image, upload_video
from app.schemas.video_edit import EditData, SubtitleAnimation, TransitionType
from app.services.video_merge import BGM_PRESETS, _run_ffmpeg

logger = logging.getLogger(__name__)


async def _has_audio_stream(path: str) -> bool:
    """ffprobe로 오디오 스트림 존재 여부 확인"""
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "a",
        "-show_entries", "stream=index", "-of", "csv=p=0", path,
    ]
    proc = await asyncio.create_subprocess_exec(
        *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    out, _ = await proc.communicate()
    return bool(out.strip())


async def _ensure_audio_stream(input_path: str, output_path: str) -> None:
    """오디오 스트림이 없으면 무음 오디오 트랙 추가"""
    if await _has_audio_stream(input_path):
        if input_path != output_path:
            cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
            await _run_ffmpeg(cmd)
        return

    cmd = [
        "ffmpeg", "-y", "-i", input_path,
        "-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
        "-c:v", "copy", "-c:a", "aac", "-shortest", output_path,
    ]
    await _run_ffmpeg(cmd)


async def render_with_edits(
    storyboard_id: str,
    user_id: str,
    edit_data: EditData,
    progress_callback: Callable[[dict], Awaitable[None]] | None = None,
) -> str | None:
    """editData 기반 최종 영상 렌더링

    1. 씬별 트림 + 배속
    2. 전환 효과 적용하며 concat
    3. 구간별 오디오 조절
    4. TTS 오버레이 믹스
    5. BGM 믹스
    6. ASS 자막 번인
    7. 썸네일 추출
    8. S3 업로드
    """

    final_url_holder: list[str | None] = [None]

    async def notify(pct: int, step: str) -> None:
        if progress_callback:
            status = "FAILED" if pct < 0 else ("RENDER_READY" if pct >= 100 else "RENDERING")
            msg: dict = {
                "storyboard_id": storyboard_id,
                "status": status,
                "progress": max(pct, 0),
                "step": step,
            }
            if status == "RENDER_READY" and final_url_holder[0]:
                msg["final_video_url"] = final_url_holder[0]
            await progress_callback(msg)

    try:
        # 씬 영상 URL 조회
        scenes_db = await db.storyboardscene.find_many(
            where={"storyboardId": storyboard_id},
            order={"sceneOrder": "asc"},
        )
        scene_map = {s.id: s for s in scenes_db}

        # editData의 order 기준으로 정렬
        sorted_edits = sorted(edit_data.scenes, key=lambda s: s.order)

        with tempfile.TemporaryDirectory(prefix="eo_render_") as tmpdir:
            await notify(5, "영상 다운로드 중...")

            # Step 1: 씬별 다운로드 + 트림 + 배속
            processed_files: list[str] = []
            for i, se in enumerate(sorted_edits):
                scene = scene_map.get(se.scene_id)
                if not scene or not scene.videoUrl:
                    continue

                raw_path = os.path.join(tmpdir, f"raw_{i:03d}.mp4")
                await _download(scene.videoUrl, raw_path)

                out_path = os.path.join(tmpdir, f"proc_{i:03d}.mp4")
                await _trim_and_speed(raw_path, out_path, se.trim_start, se.trim_end, se.speed)
                processed_files.append(out_path)

            if not processed_files:
                await notify(-1, "처리할 영상이 없습니다")
                return None

            await notify(20, "씬 결합 중...")

            # Step 2: 전환 효과 + concat
            transitions = [se.transition for se in sorted_edits[: len(processed_files)]]
            concat_path = os.path.join(tmpdir, "concat.mp4")
            await _concat_with_transitions(processed_files, transitions, concat_path)

            # concat 후 오디오 스트림이 없으면 무음 트랙 추가
            concat_with_audio = os.path.join(tmpdir, "concat_audio.mp4")
            await _ensure_audio_stream(concat_path, concat_with_audio)
            concat_path = concat_with_audio

            await notify(35, "오디오 조절 중...")

            # Step 3: 구간별 오디오 조절 (음소거/볼륨)
            audio_adjusted = os.path.join(tmpdir, "audio_adj.mp4")
            await _apply_audio_adjustments(concat_path, sorted_edits, audio_adjusted)

            await notify(45, "TTS 오버레이 믹싱 중...")

            # Step 4: TTS 오버레이 믹스
            tts_mixed = os.path.join(tmpdir, "tts_mix.mp4")
            await _mix_tts_overlays(audio_adjusted, edit_data.tts_overlays, tts_mixed, tmpdir)

            await notify(55, "BGM 믹싱 중...")

            # Step 5: BGM 시작지점 추천 + 믹스
            bgm_mixed = os.path.join(tmpdir, "bgm_mix.mp4")
            has_tts = bool(edit_data.tts_overlays)

            bgm_start = 0.0
            if edit_data.bgm.preset:
                try:
                    from app.services.bgm_matcher import recommend_bgm_start

                    scene_descs = []
                    for se in sorted_edits:
                        scene = scene_map.get(se.scene_id)
                        if scene:
                            scene_descs.append({
                                "content": scene.content or "",
                                "duration": (se.trim_end or scene.duration or 5.0) - se.trim_start,
                                "narration": scene.narration,
                            })
                    result = await recommend_bgm_start(edit_data.bgm.preset, scene_descs)
                    bgm_start = result.get("start_time", 0.0)
                    logger.info("BGM 시작지점: %.1fs (%s)", bgm_start, result.get("reason", ""))
                except Exception:
                    logger.warning("BGM 매칭 실패, 0초부터 시작", exc_info=True)

            await _mix_bgm(tts_mixed, edit_data.bgm, bgm_mixed, tmpdir, has_tts, bgm_start)

            await notify(65, "자막 입히는 중...")

            # Step 6: ASS 자막 번인
            sub_path = os.path.join(tmpdir, "subtitles.ass")
            _generate_ass(edit_data.subtitles, sub_path)
            final_path = os.path.join(tmpdir, f"final_{uuid.uuid4().hex}.mp4")

            if edit_data.subtitles:
                await _burn_subtitles(bgm_mixed, sub_path, final_path)
            else:
                await _faststart(bgm_mixed, final_path)

            await notify(80, "업로드 중...")

            # Step 7: S3 업로드
            with open(final_path, "rb") as f:
                video_data = f.read()

            video_url = await asyncio.to_thread(
                upload_video, video_data, user_id, folder="final-videos"
            )

            # Step 8: 썸네일 추출
            if edit_data.thumbnail_time > 0:
                thumb_path = os.path.join(tmpdir, "thumb.png")
                await _extract_frame(final_path, edit_data.thumbnail_time, thumb_path)
                if os.path.exists(thumb_path):
                    with open(thumb_path, "rb") as f:
                        thumb_data = f.read()
                    thumb_url = await asyncio.to_thread(
                        upload_image,
                        thumb_data,
                        user_id,
                        content_type="image/png",
                        folder="thumbnails",
                    )
                    await db.storyboard.update(
                        where={"id": storyboard_id},
                        data={"heroFrameUrl": thumb_url},
                    )

            # DB 업데이트
            await db.storyboard.update(
                where={"id": storyboard_id},
                data={"finalVideoUrl": video_url},
            )

            final_url_holder[0] = video_url
            await notify(100, "렌더링 완료!")
            return video_url

    except Exception:
        logger.exception("렌더링 실패: %s", storyboard_id)
        await notify(-1, "렌더링 중 오류가 발생했습니다")
        return None


async def extract_thumbnail_frame(video_url: str, time_seconds: float, user_id: str) -> str:
    """영상에서 특정 시간의 프레임을 추출하여 S3 업로드"""
    with tempfile.TemporaryDirectory(prefix="eo_thumb_") as tmpdir:
        video_path = os.path.join(tmpdir, "video.mp4")
        await _download(video_url, video_path)

        thumb_path = os.path.join(tmpdir, "thumb.png")
        await _extract_frame(video_path, time_seconds, thumb_path)

        if not os.path.exists(thumb_path):
            raise RuntimeError("썸네일 추출 실패")

        with open(thumb_path, "rb") as f:
            data = f.read()

        return await asyncio.to_thread(
            upload_image, data, user_id, content_type="image/png", folder="thumbnails"
        )


# ── ffmpeg 유틸 ──


async def _download(url: str, dest: str) -> None:
    async with httpx.AsyncClient(timeout=120, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        with open(dest, "wb") as f:
            f.write(resp.content)


async def _trim_and_speed(
    input_path: str, output_path: str, trim_start: float, trim_end: float | None, speed: float
) -> None:
    """트림 + 배속 적용"""
    cmd = ["ffmpeg", "-y", "-i", input_path]

    if trim_start > 0:
        cmd.extend(["-ss", f"{trim_start:.3f}"])
    if trim_end is not None:
        cmd.extend(["-to", f"{trim_end:.3f}"])

    if speed != 1.0:
        pts = 1.0 / speed
        # 배속: 0.5~2.0
        atempo = speed
        if atempo < 0.5:
            atempo = 0.5
        elif atempo > 2.0:
            atempo = 2.0
        # 오디오 트랙 존재 여부 확인 (ffprobe)
        probe_cmd = [
            "ffprobe", "-v", "error", "-select_streams", "a",
            "-show_entries", "stream=index", "-of", "csv=p=0", input_path,
        ]
        probe = await asyncio.create_subprocess_exec(
            *probe_cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        probe_out, _ = await probe.communicate()
        has_audio = bool(probe_out.strip())

        if has_audio:
            cmd.extend(["-filter_complex", f"[0:v]setpts={pts}*PTS[v];[0:a]atempo={atempo}[a]"])
            cmd.extend(["-map", "[v]", "-map", "[a]"])
        else:
            cmd.extend(["-filter:v", f"setpts={pts}*PTS", "-an"])
    else:
        cmd.extend(["-c", "copy"])

    cmd.append(output_path)
    await _run_ffmpeg(cmd)


async def _concat_with_transitions(files: list[str], transitions: list, output_path: str) -> None:
    """전환 효과 적용하며 concat"""
    if len(files) == 1:
        await _faststart(files[0], output_path)
        return

    # 전환 효과 없는 경우 단순 concat
    has_transitions = any(
        t != TransitionType.NONE for t in transitions[1:] if isinstance(t, TransitionType)
    )

    if not has_transitions:
        # 단순 concat
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            for path in files:
                f.write(f"file '{path}'\n")
            concat_list = f.name

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            concat_list,
            "-c",
            "copy",
            output_path,
        ]
        await _run_ffmpeg(cmd)
        os.unlink(concat_list)
        return

    # xfade 전환 효과 적용
    # 2개씩 순차 합성
    current = files[0]
    transition_duration = 0.5

    for i in range(1, len(files)):
        t = transitions[i] if i < len(transitions) else TransitionType.NONE
        out = output_path if i == len(files) - 1 else files[0].replace("proc_000", f"xfade_{i:03d}")

        if t == TransitionType.NONE:
            # concat
            with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
                f.write(f"file '{current}'\nfile '{files[i]}'\n")
                cl = f.name
            cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", cl, "-c", "copy", out]
            await _run_ffmpeg(cmd)
            os.unlink(cl)
        else:
            xfade_type = _get_xfade_type(t)
            # 현재 영상 길이 조회
            duration = await _get_duration(current)
            offset = max(0, duration - transition_duration)

            # 오디오 스트림 존재 확인
            has_audio_0 = await _has_audio_stream(current)
            has_audio_1 = await _has_audio_stream(files[i])

            if has_audio_0 and has_audio_1:
                filter_str = (
                    f"[0:v][1:v]xfade=transition={xfade_type}:duration={transition_duration}:offset={offset}[v];"
                    f"[0:a][1:a]acrossfade=d={transition_duration}[a]"
                )
                map_args = ["-map", "[v]", "-map", "[a]"]
            else:
                # 오디오 없는 씬이 있으면 비디오만 xfade
                filter_str = (
                    f"[0:v][1:v]xfade=transition={xfade_type}:duration={transition_duration}:offset={offset}[v]"
                )
                map_args = ["-map", "[v]", "-an"]

            cmd = [
                "ffmpeg",
                "-y",
                "-i",
                current,
                "-i",
                files[i],
                "-filter_complex",
                filter_str,
                *map_args,
                "-c:v",
                "libx264",
                "-crf", "18",
                "-preset",
                "medium",
                out,
            ]
            await _run_ffmpeg(cmd)

        current = out


def _get_xfade_type(t: TransitionType) -> str:
    """TransitionType → ffmpeg xfade 이름"""
    mapping = {
        TransitionType.FADE: "fade",
        TransitionType.DISSOLVE: "dissolve",
        TransitionType.SLIDE_LEFT: "slideleft",
        TransitionType.SLIDE_UP: "slideup",
        TransitionType.WIPE: "wiperight",
    }
    return mapping.get(t, "fade")


async def _get_duration(path: str) -> float:
    """ffprobe로 영상 길이 조회"""
    cmd = [
        "ffprobe",
        "-v",
        "quiet",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
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


async def _apply_audio_adjustments(input_path: str, scene_edits: list, output_path: str) -> None:
    """구간별 음소거/볼륨 조절"""
    filters = []
    elapsed = 0.0

    for se in scene_edits:
        # 음소거 구간
        for mute_range in se.audio.mute_ranges:
            if len(mute_range) == 2:
                start = elapsed + mute_range[0]
                end = elapsed + mute_range[1]
                filters.append(f"volume=0:enable='between(t,{start:.3f},{end:.3f})'")

        # 볼륨 조절 구간
        for vr in se.audio.volume_ranges:
            if vr.volume != 1.0:
                start = elapsed + vr.start
                end = elapsed + vr.end
                filters.append(f"volume={vr.volume}:enable='between(t,{start:.3f},{end:.3f})'")

        duration = (se.trim_end or 5.0) - se.trim_start
        if se.speed != 1.0:
            duration /= se.speed
        elapsed += duration

    if not filters:
        # 변경 없으면 복사
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
    else:
        af = ",".join(filters)
        cmd = ["ffmpeg", "-y", "-i", input_path, "-af", af, "-c:v", "copy", output_path]

    await _run_ffmpeg(cmd)


async def _mix_tts_overlays(
    input_path: str, tts_overlays: list, output_path: str, tmpdir: str
) -> None:
    """커스텀 TTS 오버레이 믹스"""
    valid = [t for t in tts_overlays if t.audio_url]
    if not valid:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
        await _run_ffmpeg(cmd)
        return

    cmd = ["ffmpeg", "-y", "-i", input_path]
    input_idx = 1
    filters = []
    mix_labels = []

    for i, tts in enumerate(valid):
        apath = os.path.join(tmpdir, f"tts_overlay_{i:03d}.mp3")
        await _download(tts.audio_url, apath)
        cmd.extend(["-i", apath])
        delay_ms = int(tts.start * 1000)
        label = f"tts{input_idx}"
        filters.append(f"[{input_idx}:a]adelay={delay_ms}|{delay_ms}[{label}]")
        mix_labels.append(f"[{label}]")
        input_idx += 1

    n = len(mix_labels) + 1  # +1 for original audio
    mix_str = "[0:a]" + "".join(mix_labels)
    filters.append(f"{mix_str}amix=inputs={n}:normalize=0[aout]")

    cmd.extend(
        [
            "-filter_complex",
            ";".join(filters),
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
    await _run_ffmpeg(cmd)


async def _mix_bgm(
    input_path: str,
    bgm_setting,
    output_path: str,
    tmpdir: str,
    has_tts: bool,
    bgm_start_time: float = 0.0,
) -> None:
    """BGM 믹스 (에너지 프로파일 기반 시작지점 지원)"""
    bgm_url = None
    if bgm_setting.custom_url:
        bgm_url = bgm_setting.custom_url
    elif bgm_setting.preset:
        from app.services.bgm_matcher import get_bgm_s3_url

        key = BGM_PRESETS.get(bgm_setting.preset.lower())
        if key:
            bgm_url = get_bgm_s3_url(key)

    if not bgm_url:
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
        await _run_ffmpeg(cmd)
        return

    bgm_path = os.path.join(tmpdir, "bgm.mp3")
    try:
        await _download(bgm_url, bgm_path)
    except Exception:
        logger.warning("BGM 다운로드 실패: %s", bgm_url)
        cmd = ["ffmpeg", "-y", "-i", input_path, "-c", "copy", output_path]
        await _run_ffmpeg(cmd)
        return

    vol = bgm_setting.volume
    fade_in = "afade=t=in:d=1.5,"
    if has_tts:
        fc = (
            f"[1:a]{fade_in}volume={vol},afade=t=out:st=-3:d=3[bgm];"
            f"[bgm][0:a]sidechaincompress="
            f"threshold=0.03:ratio=4:attack=1000:release=2000:knee=6:level_sc=1[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:normalize=0[aout]"
        )
    else:
        fc = (
            f"[1:a]{fade_in}volume={vol},afade=t=out:st=-3:d=3[bgm];"
            f"[0:a][bgm]amix=inputs=2:duration=first:normalize=0[aout]"
        )

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-stream_loop",
        "-1",
    ]

    # BGM 시작 지점 적용
    if bgm_start_time > 0:
        cmd.extend(["-ss", str(bgm_start_time)])

    cmd.extend([
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
    ])
    await _run_ffmpeg(cmd)


def _generate_ass(subtitles: list, output_path: str) -> None:
    """편집 자막 데이터 → ASS 자막 파일 생성"""
    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        "PlayResX: 1080\n"
        "PlayResY: 1920\n\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
    )

    styles = []
    events = []

    for i, sub in enumerate(subtitles):
        s = sub.style
        style_name = f"Sub{i}"

        # 색상 변환 (hex → ASS &HBBGGRR)
        primary = _hex_to_ass_color(s.color)
        outline_color = _hex_to_ass_color(getattr(s, 'outline_color', '#000000'))
        outline_size = getattr(s, 'outline_size', 4)
        shadow_depth = s.shadow.offset if s.shadow.enabled else 0
        is_bold = 1 if getattr(s, 'bold', True) else 0
        is_italic = 1 if getattr(s, 'italic', False) else 0
        is_underline = 1 if getattr(s, 'underline', False) else 0

        # 배경
        if s.background.enabled:
            bg_alpha = int((1 - s.background.opacity) * 255)
            back_color = f"&H{bg_alpha:02X}" + _hex_to_ass_color(s.background.color)[2:]
            border_style = 3  # opaque box
        else:
            back_color = "&H00000000"
            border_style = 1

        # 정렬 (항상 하단 고정)
        text_align = getattr(s, 'align', 'center')
        if hasattr(text_align, 'value'):
            text_align = text_align.value
        align_offset = {"left": 0, "center": 1, "right": 2}.get(text_align, 1)
        alignment = 1 + align_offset  # bottom 기준 (1=left, 2=center, 3=right)

        margin_v = 180

        font_size = s.font_size * 2  # PlayRes 1080x1920 기준 스케일

        styles.append(
            f"Style: {style_name},{s.font.value},{font_size},"
            f"{primary},&H000000FF,{outline_color},{back_color},"
            f"{is_bold},{is_italic},{is_underline},0,100,100,0,0,"
            f"{border_style},{outline_size},{shadow_depth},{alignment},"
            f"20,20,{margin_v},1"
        )

        # 타임스탬프
        start_ts = _seconds_to_ass_ts(sub.start)
        end_ts = _seconds_to_ass_ts(sub.end)

        # 애니메이션 태그
        anim_tag = _get_animation_tag(s.animation, sub.end - sub.start)

        # 글자별 사이즈
        text = sub.text
        if s.per_char_sizes and len(s.per_char_sizes) == len(text):
            parts = []
            for ch, sz in zip(text, s.per_char_sizes, strict=True):
                parts.append(f"{{\\fs{sz * 2}}}{ch}")
            text = "".join(parts)

        events.append(f"Dialogue: 0,{start_ts},{end_ts},{style_name},,0,0,0,,{anim_tag}{text}")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(header)
        f.write("\n".join(styles))
        f.write("\n\n[Events]\n")
        f.write("Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")
        f.write("\n".join(events))
        f.write("\n")


def _hex_to_ass_color(hex_color: str) -> str:
    """#RRGGBB → &H00BBGGRR"""
    h = hex_color.lstrip("#")
    if len(h) == 6:
        r, g, b = h[0:2], h[2:4], h[4:6]
        return f"&H00{b}{g}{r}"
    return "&H00FFFFFF"



def _seconds_to_ass_ts(seconds: float) -> str:
    """초 → ASS 타임스탬프 (H:MM:SS.cc)"""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    cs = int((seconds % 1) * 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _get_animation_tag(animation: SubtitleAnimation, duration: float) -> str:
    """애니메이션 → ASS override 태그"""
    if animation == SubtitleAnimation.FADEIN:
        return "{\\fad(400,200)}"
    if animation == SubtitleAnimation.POPUP:
        # 팝업: 0에서 130%로 커졌다가 100%로 바운스 (트렌디 숏폼 스타일)
        return "{\\fscx0\\fscy0\\t(0,150,\\fscx130\\fscy130)\\t(150,250,\\fscx100\\fscy100)}"
    if animation == SubtitleAnimation.BOUNCE:
        # 바운스: 위에서 떨어지면서 탄성 효과
        return (
            "{\\move(540,800,540,960,0,200)"
            "\\fscx0\\fscy0"
            "\\t(0,120,\\fscx115\\fscy115)"
            "\\t(120,200,\\fscx100\\fscy100)}"
        )
    if animation == SubtitleAnimation.GLOW:
        # 글로우: 페이드인 + 테두리 빛남 효과
        return (
            "{\\fad(300,200)"
            "\\blur6\\t(0,400,\\blur0)"
            "\\bord8\\t(0,400,\\bord4)}"
        )
    if animation == SubtitleAnimation.SLIDE_UP:
        # 아래에서 위로 슬라이드
        return "{\\move(540,1000,540,960,0,250)\\fad(250,150)}"
    if animation == SubtitleAnimation.TYPING:
        # 글자 하나씩 나타나는 효과 (카라오케 스윕)
        ms_per_char = int(duration * 1000 / 20)
        return f"{{\\k{ms_per_char}}}"
    return ""


def _get_fonts_dir() -> str:
    """폰트 디렉토리 경로 반환"""
    base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "assets", "fonts")


async def _burn_subtitles(input_path: str, ass_path: str, output_path: str) -> None:
    """ASS 자막 번인 (커스텀 폰트 디렉토리 포함)"""
    fonts_dir = _get_fonts_dir()
    # fontsdir 옵션으로 커스텀 폰트 참조
    vf = f"ass={ass_path}:fontsdir={fonts_dir}"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-vf",
        vf,
        "-c:a",
        "copy",
        "-c:v",
        "libx264",
        "-crf", "18",
        "-preset",
        "medium",
        "-movflags",
        "+faststart",
        output_path,
    ]
    await _run_ffmpeg(cmd)


async def _faststart(input_path: str, output_path: str) -> None:
    """faststart만 적용"""
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        input_path,
        "-c",
        "copy",
        "-movflags",
        "+faststart",
        output_path,
    ]
    await _run_ffmpeg(cmd)


async def _extract_frame(video_path: str, time_seconds: float, output_path: str) -> None:
    """특정 시간의 프레임 추출"""
    cmd = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{time_seconds:.3f}",
        "-i",
        video_path,
        "-frames:v",
        "1",
        "-q:v",
        "2",
        output_path,
    ]
    await _run_ffmpeg(cmd)
