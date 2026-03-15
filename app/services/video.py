"""영상 생성 서비스 (Google Veo + Mock)"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# 폴링 기본값
_POLL_INTERVAL = 5  # 초
_MAX_WAIT = 300  # 최대 5분


class VideoGenerator(ABC):
    """영상 생성 모델 추상 인터페이스"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "9:16",
    ) -> str:
        """영상 생성 → 완료된 영상 URL 반환"""

    @abstractmethod
    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회 → {status, video_url, duration, error}"""

    @property
    def provider_name(self) -> str:
        """제공자 이름 (로깅/비용 추적용)"""
        return self.__class__.__name__


class VeoVideoGenerator(VideoGenerator):
    """Google Veo API 영상 생성기"""

    def __init__(self) -> None:
        self._api_key = settings.GOOGLE_API_KEY
        self._model = settings.VEO_MODEL
        self._base = "https://generativelanguage.googleapis.com"

    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Veo API로 영상 생성 → 완료 대기 → 영상 URL 반환"""
        url = (
            f"{self._base}/v1beta/models/{self._model}"
            f":predictLongRunning"
        )
        headers = {
            "x-goog-api-key": self._api_key,
            "Content-Type": "application/json",
        }

        instances: list[dict] = [{"prompt": prompt}]
        # Veo API는 현재 text-to-video만 지원 (imageUrl 미지원)

        body = {
            "instances": instances,
            "parameters": {
                "aspectRatio": aspect_ratio,
                "durationSeconds": min(duration, 8),
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        op_name = data.get("name")
        if not op_name:
            raise RuntimeError(f"Veo 응답에 operation name 없음: {data}")

        video_url = await self._poll_operation(op_name)
        return video_url

    async def _poll_operation(self, op_name: str) -> str:
        """작업 완료까지 폴링"""
        url = f"{self._base}/v1beta/{op_name}"
        headers = {"x-goog-api-key": self._api_key}
        elapsed = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while elapsed < _MAX_WAIT:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL

                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

                if data.get("done"):
                    return self._extract_video_url(data)

                logger.info(
                    "Veo 폴링 중: %s (%.0f초 경과)", op_name, elapsed
                )

        raise TimeoutError(
            f"Veo 영상 생성 타임아웃 ({_MAX_WAIT}초): {op_name}"
        )

    def _extract_video_url(self, data: dict) -> str:
        """완료된 operation에서 영상 URL 추출"""
        error = data.get("error")
        if error:
            raise RuntimeError(f"Veo 영상 생성 실패: {error}")

        response = data.get("response", {})
        videos = response.get("generatedVideos", [])
        if not videos:
            logger.error("Veo 응답 구조: %s", data)
            raise RuntimeError(f"Veo 응답에 영상이 없습니다: {data}")

        video = videos[0].get("video", {})
        uri = video.get("uri")
        if not uri:
            raise RuntimeError("Veo 영상 URI가 없습니다")

        return uri

    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회"""
        return {
            "status": "completed",
            "video_url": None,
            "duration": 5,
            "error": None,
        }

    @property
    def provider_name(self) -> str:
        return "Veo"


class MockVideoGenerator(VideoGenerator):
    """개발/테스트용 Mock 영상 생성기 (딜레이 후 성공)"""

    def __init__(self, delay_seconds: int = 5) -> None:
        self._delay = delay_seconds

    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Mock 영상 생성 — 딜레이 후 task_id 반환"""
        task_id = uuid.uuid4().hex
        logger.info(
            "Mock(delay=%ds) 영상 생성: task_id=%s",
            self._delay,
            task_id,
        )
        await asyncio.sleep(self._delay)
        return task_id

    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회"""
        return {
            "status": "completed",
            "video_url": None,
            "duration": 5,
            "error": None,
        }

    @property
    def provider_name(self) -> str:
        return "Mock"


def get_generator(provider: str | None = None) -> VideoGenerator:
    """제공자에 따라 적절한 VideoGenerator 반환

    우선순위: Veo > Mock
    provider가 None이면 API 키 유무로 자동 선택.
    """
    if provider == "mock":
        return MockVideoGenerator(delay_seconds=5)
    if provider == "veo":
        return VeoVideoGenerator()

    # 자동 선택: Veo 키 있으면 Veo, 없으면 Mock
    if settings.GOOGLE_API_KEY:
        return VeoVideoGenerator()
    return MockVideoGenerator(delay_seconds=5)
