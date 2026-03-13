"""영상 생성 관련 스키마"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class VideoMode(str, Enum):  # noqa: UP042
    """생성 품질 모드"""

    STD = "std"
    PRO = "pro"


class AspectRatio(str, Enum):  # noqa: UP042
    """화면 비율"""

    PORTRAIT = "9:16"
    LANDSCAPE = "16:9"
    SQUARE = "1:1"


class VideoGenerateRequest(BaseModel):
    """영상 생성 요청"""

    character_id: str = Field(description="캐릭터 UUID")
    prompt: str = Field(min_length=1, max_length=2000, description="영상 프롬프트")
    mode: VideoMode = Field(default=VideoMode.PRO, description="품질 모드")
    duration: int = Field(default=5, ge=5, le=10, description="영상 길이 (초)")
    aspect_ratio: AspectRatio = Field(default=AspectRatio.PORTRAIT, description="화면 비율")


class VideoTaskResponse(BaseModel):
    """영상 생성 작업 응답"""

    task_id: str
    status: str = "submitted"


class VideoStatusResponse(BaseModel):
    """영상 생성 상태 조회 응답"""

    task_id: str
    status: str
    video_url: str | None = None
    duration: int | None = None
    error: str | None = None
