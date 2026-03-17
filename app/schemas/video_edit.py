"""영상 편집 관련 스키마"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class TransitionType(str, Enum):  # noqa: UP042
    """씬 간 전환 효과"""

    NONE = "none"
    FADE = "fade"
    DISSOLVE = "dissolve"
    SLIDE_LEFT = "slide_left"
    SLIDE_UP = "slide_up"
    WIPE = "wipe"


class SubtitleFont(str, Enum):  # noqa: UP042
    """지원 폰트 (8종)"""

    NANUM_GOTHIC = "NanumGothic"
    NANUM_MYEONGJO = "NanumMyeongjo"
    NANUM_SQUARE_ROUND = "NanumSquareRound"
    NANUM_BARUN_GOTHIC = "NanumBarunGothic"
    MAPO_FLOWER = "MapoFlowerIsland"
    GMARKET_SANS = "GmarketSans"
    PRETENDARD = "Pretendard"
    DOHYEON = "DoHyeon"


class SubtitlePosition(str, Enum):  # noqa: UP042
    """자막 위치 프리셋"""

    TOP = "top"
    CENTER = "center"
    BOTTOM = "bottom"


class SubtitleAnimation(str, Enum):  # noqa: UP042
    """자막 애니메이션"""

    NONE = "none"
    TYPING = "typing"
    POPUP = "popup"
    FADEIN = "fadein"


# ── 요청/응답 스키마 ──


class AudioRange(BaseModel):
    """구간별 볼륨 조절"""

    start: float = Field(ge=0, description="시작 시간(초)")
    end: float = Field(ge=0, description="끝 시간(초)")
    volume: float = Field(ge=0.0, le=3.0, default=1.0, description="볼륨 배율")


class SceneAudio(BaseModel):
    """씬 오디오 설정"""

    mute_ranges: list[list[float]] = Field(
        default_factory=list, description="음소거 구간 [[시작,끝],...]"
    )
    volume_ranges: list[AudioRange] = Field(default_factory=list, description="구간별 볼륨")


class SceneEditItem(BaseModel):
    """씬별 편집 데이터"""

    scene_id: str
    order: int
    trim_start: float = Field(default=0.0, ge=0, description="트림 시작(초, 0.001 정밀도)")
    trim_end: float | None = Field(default=None, ge=0, description="트림 끝(초, null이면 원본 끝)")
    speed: float = Field(default=1.0, ge=0.5, le=2.0, description="배속")
    transition: TransitionType = TransitionType.NONE
    audio: SceneAudio = Field(default_factory=SceneAudio)


class BgmSetting(BaseModel):
    """BGM 설정"""

    preset: str | None = Field(default=None, description="BGM 프리셋 이름")
    custom_url: str | None = Field(default=None, description="커스텀 BGM URL")
    volume: float = Field(default=0.2, ge=0.0, le=1.0, description="BGM 볼륨")


class ShadowStyle(BaseModel):
    """자막 그림자"""

    enabled: bool = False
    color: str = "#000000"
    offset: int = Field(default=2, ge=1, le=5)


class BackgroundStyle(BaseModel):
    """자막 배경"""

    enabled: bool = True
    color: str = "#000000"
    opacity: float = Field(default=0.7, ge=0.0, le=1.0)


class SubtitleStyle(BaseModel):
    """자막 스타일"""

    font: SubtitleFont = SubtitleFont.NANUM_GOTHIC
    font_size: int = Field(default=24, ge=12, le=72)
    color: str = Field(default="#FFFFFF", description="글자 색상 (hex)")
    shadow: ShadowStyle = Field(default_factory=ShadowStyle)
    background: BackgroundStyle = Field(default_factory=BackgroundStyle)
    position: SubtitlePosition = SubtitlePosition.BOTTOM
    position_y: int | None = Field(default=None, ge=0, le=100, description="자유 배치 Y (0~100%)")
    animation: SubtitleAnimation = SubtitleAnimation.NONE
    per_char_sizes: list[int] | None = Field(default=None, description="글자별 사이즈 배열")


class SubtitleItem(BaseModel):
    """자막 항목"""

    scene_id: str
    text: str = Field(max_length=500)
    start: float = Field(ge=0, description="시작 시간(초)")
    end: float = Field(ge=0, description="끝 시간(초)")
    style: SubtitleStyle = Field(default_factory=SubtitleStyle)


class TtsOverlayItem(BaseModel):
    """커스텀 TTS 오버레이"""

    id: str | None = None
    text: str = Field(max_length=500)
    voice_id: str = "alloy"
    voice_style: str = ""
    start: float = Field(ge=0, description="삽입 시작 시간(초)")
    scene_id: str
    audio_url: str | None = None


class EditData(BaseModel):
    """전체 편집 상태"""

    scenes: list[SceneEditItem] = Field(default_factory=list)
    bgm: BgmSetting = Field(default_factory=BgmSetting)
    subtitles: list[SubtitleItem] = Field(default_factory=list)
    tts_overlays: list[TtsOverlayItem] = Field(default_factory=list)
    thumbnail_time: float = Field(default=0.0, ge=0, description="썸네일 추출 시간(초)")


# ── API 요청/응답 ──


class VideoEditResponse(BaseModel):
    """편집 상태 조회 응답"""

    id: str
    storyboard_id: str
    edit_data: EditData
    version: int
    created_at: str
    updated_at: str


class VideoEditUpdateRequest(BaseModel):
    """편집 저장 요청"""

    edit_data: EditData


class UndoResponse(BaseModel):
    """되돌리기 응답"""

    id: str
    version: int
    edit_data: EditData
    message: str = "이전 단계로 되돌렸습니다."


class TtsCreateRequest(BaseModel):
    """커스텀 TTS 생성 요청"""

    text: str = Field(min_length=1, max_length=500, description="TTS 텍스트")
    voice_id: str = Field(default="alloy", description="음성 ID")
    voice_style: str = Field(default="", description="음성 스타일 지시")


class TtsCreateResponse(BaseModel):
    """커스텀 TTS 생성 응답"""

    audio_url: str
    duration: float = 0.0
    message: str = "TTS가 생성되었습니다."


class ThumbnailRequest(BaseModel):
    """썸네일 추출 요청"""

    time: float = Field(ge=0, description="추출 시간(초)")


class ThumbnailResponse(BaseModel):
    """썸네일 추출 응답"""

    thumbnail_url: str
    message: str = "썸네일이 추출되었습니다."


class RenderStartResponse(BaseModel):
    """렌더링 시작 응답"""

    storyboard_id: str
    status: str = "RENDERING"
    message: str = "최종 렌더링이 시작되었습니다."
