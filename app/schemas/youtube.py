"""YouTube 연동 관련 스키마"""

from __future__ import annotations

from pydantic import BaseModel, field_validator


class YoutubeConnectRequest(BaseModel):
    """YouTube 연동 요청 - 프론트에서 받은 authorization code"""

    code: str
    redirect_uri: str

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("인증 코드가 필요합니다.")
        return v


class YoutubeConnectResponse(BaseModel):
    """YouTube 연동 응답"""

    channel_title: str
    message: str


class YoutubeDisconnectResponse(BaseModel):
    """YouTube 연동 해제 응답"""

    message: str


class YoutubeUploadRequest(BaseModel):
    """YouTube 업로드 요청"""

    title: str
    description: str = ""
    tags: list[str] = []
    privacy_status: str = "private"

    @field_validator("title")
    @classmethod
    def validate_title(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("영상 제목을 입력해주세요.")
        if len(v) > 100:
            raise ValueError("제목은 100자 이내여야 합니다.")
        return v

    @field_validator("privacy_status")
    @classmethod
    def validate_privacy(cls, v: str) -> str:
        allowed = {"public", "private", "unlisted"}
        if v not in allowed:
            raise ValueError(f"공개 상태는 {allowed} 중 하나여야 합니다.")
        return v


class YoutubeUploadResponse(BaseModel):
    """YouTube 업로드 응답"""

    youtube_video_id: str
    youtube_url: str
    message: str


class YoutubeStatusResponse(BaseModel):
    """YouTube 업로드 상태 응답"""

    status: str
    youtube_video_id: str | None = None
    youtube_url: str | None = None
    error: str | None = None
