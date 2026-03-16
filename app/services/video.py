"""영상 생성 서비스 (Hailuo + Pika + Veo + Mock)"""

from __future__ import annotations

import asyncio
import logging
import uuid
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings

logger = logging.getLogger(__name__)

# Pika 폴링 설정
_PIKA_POLL_INTERVAL = 10
_PIKA_MAX_WAIT = 300

# Hailuo 폴링 설정
_HAILUO_POLL_INTERVAL = 8
_HAILUO_MAX_WAIT = 360  # 최대 6분 (Standard 평균 4분)

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


class PikaVideoGenerator(VideoGenerator):
    """Pika v2.2 image-to-video (fal.ai 경유)"""

    def __init__(self) -> None:
        self._api_key = settings.FAL_KEY
        self._base = "https://queue.fal.run/fal-ai/pika/v2.2/image-to-video"

    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "9:16",
        negative_prompt: str = "",
        guidance_scale: float = 16,
        motion: float = 1.5,
    ) -> str:
        """Pika API로 영상 생성 → 폴링 → 영상 URL 반환"""
        headers = {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }

        body: dict = {
            "prompt": prompt,
            "duration": min(duration, 5),
            "resolution": "720p",
        }

        if image_url:
            body["image_url"] = image_url
        if negative_prompt:
            body["negative_prompt"] = negative_prompt

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._base, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError(f"Pika 응답에 request_id 없음: {data}")

        logger.info("Pika 요청 시작: request_id=%s", request_id)

        video_url = await self._poll_result(request_id)
        return video_url

    async def _poll_result(self, request_id: str) -> str:
        """Pika 작업 완료까지 폴링"""
        status_url = f"https://queue.fal.run/fal-ai/pika/requests/{request_id}/status"
        result_url = f"https://queue.fal.run/fal-ai/pika/requests/{request_id}"
        headers = {"Authorization": f"Key {self._api_key}"}

        elapsed = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while elapsed < _PIKA_MAX_WAIT:
                await asyncio.sleep(_PIKA_POLL_INTERVAL)
                elapsed += _PIKA_POLL_INTERVAL

                resp = await client.get(status_url, headers=headers)
                resp.raise_for_status()
                status_data = resp.json()
                status = status_data.get("status", "")

                logger.info("Pika 폴링: %s (%ds)", status, elapsed)

                if status == "COMPLETED":
                    result_resp = await client.get(result_url, headers=headers)
                    result_resp.raise_for_status()
                    result = result_resp.json()
                    video = result.get("video", {})
                    url = video.get("url", "")
                    if not url:
                        raise RuntimeError(f"Pika 영상 URL 없음: {result}")
                    return url

                if status == "FAILED":
                    raise RuntimeError(f"Pika 영상 생성 실패: {status_data}")

        raise TimeoutError(f"Pika 영상 생성 타임아웃 ({_PIKA_MAX_WAIT}초)")

    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회"""
        return {"status": "completed", "video_url": None, "duration": 5, "error": None}

    @property
    def provider_name(self) -> str:
        return "Pika"


class HailuoVideoGenerator(VideoGenerator):
    """MiniMax Hailuo image-to-video (fal.ai 경유)

    - I2V-01-Live: 2D 애니 캐릭터 전용 (캐릭터 변형 최소)
    - Hailuo-02 Standard: 범용 고품질
    """

    def __init__(self, model: str = "live") -> None:
        self._api_key = settings.FAL_KEY
        # live = 2D 애니 전용, 02 = 범용
        if model == "live":
            self._base = "https://queue.fal.run/fal-ai/minimax/video-01-live/image-to-video"
            self._result_base = "https://queue.fal.run/fal-ai/minimax/video-01-live/image-to-video"
        else:
            self._base = "https://queue.fal.run/fal-ai/minimax/hailuo-02/standard/image-to-video"
            self._result_base = "https://queue.fal.run/fal-ai/minimax/hailuo-02/standard/image-to-video"
        self._model = model

    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Hailuo API로 영상 생성 → 폴링 → 영상 URL 반환"""
        headers = {
            "Authorization": f"Key {self._api_key}",
            "Content-Type": "application/json",
        }

        body: dict = {
            "prompt": prompt,
            "prompt_optimizer": True,
        }

        if image_url:
            body["image_url"] = image_url

        # Hailuo-02는 duration, resolution 지원
        if self._model != "live":
            body["duration"] = min(duration, 6)
            body["resolution"] = "768P"

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._base, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError(f"Hailuo 응답에 request_id 없음: {data}")

        logger.info("Hailuo(%s) 요청 시작: request_id=%s", self._model, request_id)

        video_url = await self._poll_result(request_id)
        return video_url

    async def _poll_result(self, request_id: str) -> str:
        """Hailuo 작업 완료까지 폴링"""
        status_url = f"{self._result_base}/requests/{request_id}/status"
        result_url = f"{self._result_base}/requests/{request_id}"
        headers = {"Authorization": f"Key {self._api_key}"}

        elapsed = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while elapsed < _HAILUO_MAX_WAIT:
                await asyncio.sleep(_HAILUO_POLL_INTERVAL)
                elapsed += _HAILUO_POLL_INTERVAL

                resp = await client.get(status_url, headers=headers)
                resp.raise_for_status()
                status_data = resp.json()
                status = status_data.get("status", "")

                logger.info("Hailuo 폴링: %s (%ds)", status, elapsed)

                if status == "COMPLETED":
                    result_resp = await client.get(result_url, headers=headers)
                    result_resp.raise_for_status()
                    result = result_resp.json()
                    video = result.get("video", {})
                    url = video.get("url", "")
                    if not url:
                        raise RuntimeError(f"Hailuo 영상 URL 없음: {result}")
                    return url

                if status == "FAILED":
                    raise RuntimeError(f"Hailuo 영상 생성 실패: {status_data}")

        raise TimeoutError(f"Hailuo 영상 생성 타임아웃 ({_HAILUO_MAX_WAIT}초)")

    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회"""
        return {"status": "completed", "video_url": None, "duration": 5, "error": None}

    @property
    def provider_name(self) -> str:
        return f"Hailuo-{self._model}"


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

    우선순위: Hailuo-live (2D 애니 전용) > Pika > Mock
    provider가 None이면 API 키 유무로 자동 선택.
    """
    if provider == "mock":
        return MockVideoGenerator(delay_seconds=5)
    if provider == "hailuo" or provider == "hailuo-live":
        return HailuoVideoGenerator(model="live")
    if provider == "hailuo-02":
        return HailuoVideoGenerator(model="02")
    if provider == "pika":
        return PikaVideoGenerator()

    # 자동 선택: Hailuo-live > Pika > Mock
    if settings.FAL_KEY:
        return HailuoVideoGenerator(model="live")
    return MockVideoGenerator(delay_seconds=5)
