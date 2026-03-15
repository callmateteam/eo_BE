"""영상 생성 서비스 (Kling AI via kie.ai + Veo fallback + Mock)"""

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


class KlingVideoGenerator(VideoGenerator):
    """Kling AI 영상 생성기 (kling3api.com 경유)

    API 구조:
    - 생성: POST /api/generate
    - 상태: GET /api/status?task_id=xxx
    - type: elements-text-to-video / elements-image-to-video
    - 응답: data.response[] 배열에 영상 URL
    """

    def __init__(self) -> None:
        self._api_key = settings.KLING_API_KEY
        self._base = settings.KLING_BASE_URL  # https://kling3api.com
        self._t2v_type = settings.KLING_MODEL  # elements-text-to-video
        self._i2v_type = settings.KLING_I2V_MODEL  # elements-image-to-video
        self._poll_interval = settings.KLING_POLL_INTERVAL
        self._max_wait = settings.KLING_MAX_WAIT

    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        aspect_ratio: str = "9:16",
    ) -> str:
        """Kling API로 영상 생성 → 폴링 → 결과 URL 반환"""
        url = f"{self._base}/api/generate"

        # image_url 있으면 Image-to-Video, 없으면 Text-to-Video
        task_type = self._i2v_type if image_url else self._t2v_type

        body: dict = {
            "type": task_type,
            "prompt": prompt,
            "duration": min(duration, 10),
            "aspect_ratio": aspect_ratio,
        }

        if image_url:
            body["image_url"] = image_url

        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body, headers=headers)
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 200:
            raise RuntimeError(
                f"Kling 작업 생성 실패: {data.get('message', data)}"
            )

        task_id = data["data"]["task_id"]
        logger.info(
            "Kling 작업 생성: type=%s, task_id=%s", task_type, task_id
        )

        # 폴링으로 완료 대기
        video_url = await self._poll_task(task_id)
        return video_url

    async def _poll_task(self, task_id: str) -> str:
        """작업 완료까지 폴링 → 영상 URL 반환"""
        url = f"{self._base}/api/status"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        elapsed = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while elapsed < self._max_wait:
                await asyncio.sleep(self._poll_interval)
                elapsed += self._poll_interval

                resp = await client.get(
                    url,
                    params={"task_id": task_id},
                    headers=headers,
                )
                resp.raise_for_status()
                data = resp.json()

                if data.get("code") != 200:
                    raise RuntimeError(
                        f"Kling 상태 조회 실패: {data.get('message', data)}"
                    )

                task_data = data.get("data", {})
                status = task_data.get("status", "")

                if status in ("COMPLETED", "SUCCESS"):
                    return self._extract_video_url(task_data)
                if status == "FAILED":
                    err = task_data.get("error_message", "알 수 없는 오류")
                    raise RuntimeError(f"Kling 영상 생성 실패: {err}")

                logger.info(
                    "Kling 폴링 중: %s status=%s (%.0f초 경과)",
                    task_id, status, elapsed,
                )

        raise TimeoutError(
            f"Kling 영상 생성 타임아웃 ({self._max_wait}초): {task_id}"
        )

    def _extract_video_url(self, task_data: dict) -> str:
        """완료된 task에서 영상 URL 추출

        response 형식:
        - dict: {"resultUrls": ["https://..."]}
        - list: ["https://..."]
        - str: "https://..."
        """
        response = task_data.get("response")
        if not response:
            raise RuntimeError("Kling 응답에 response가 없습니다")

        # dict: {resultUrls: [...]}
        if isinstance(response, dict):
            urls = response.get("resultUrls", [])
            if not urls:
                raise RuntimeError("Kling resultUrls가 비어있습니다")
            video_url = urls[0]
        elif isinstance(response, list):
            if not response:
                raise RuntimeError("Kling response 배열이 비어있습니다")
            video_url = response[0]
        elif isinstance(response, str):
            video_url = response
        else:
            raise RuntimeError(f"Kling response 형식 오류: {type(response)}")

        logger.info("Kling 영상 생성 완료: %s", video_url[:80])
        return video_url

    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회"""
        url = f"{self._base}/api/status"
        headers = {"Authorization": f"Bearer {self._api_key}"}

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                url,
                params={"task_id": task_id},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()

        task_data = data.get("data", {})
        status = task_data.get("status", "IN_PROGRESS")

        video_url = None
        if status in ("COMPLETED", "SUCCESS"):
            try:
                video_url = self._extract_video_url(task_data)
            except RuntimeError:
                pass

        return {
            "status": status,
            "video_url": video_url,
            "duration": 5,
            "error": task_data.get("error_message"),
        }

    @property
    def provider_name(self) -> str:
        return "Kling"


class VeoVideoGenerator(VideoGenerator):
    """Google Veo API 영상 생성기 (레거시 — Kling 전환 후 대체)"""

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
            f":predictLongRunning?key={self._api_key}"
        )

        instances: list[dict] = [{"prompt": prompt}]
        if image_url:
            instances[0]["image"] = {"imageUrl": image_url}

        body = {
            "instances": instances,
            "parameters": {
                "aspectRatio": aspect_ratio,
                "durationSeconds": min(duration, 8),
                "numberOfVideos": 1,
            },
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(url, json=body)
            resp.raise_for_status()
            data = resp.json()

        op_name = data.get("name")
        if not op_name:
            raise RuntimeError(f"Veo 응답에 operation name 없음: {data}")

        video_url = await self._poll_operation(op_name)
        return video_url

    async def _poll_operation(self, op_name: str) -> str:
        """작업 완료까지 폴링"""
        url = f"{self._base}/v1beta/{op_name}?key={self._api_key}"
        elapsed = 0
        async with httpx.AsyncClient(timeout=30) as client:
            while elapsed < _MAX_WAIT:
                await asyncio.sleep(_POLL_INTERVAL)
                elapsed += _POLL_INTERVAL

                resp = await client.get(url)
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
            raise RuntimeError("Veo 응답에 영상이 없습니다")

        video = videos[0].get("video", {})
        uri = video.get("uri")
        if not uri:
            raise RuntimeError("Veo 영상 URI가 없습니다")

        return uri

    async def get_status(self, task_id: str) -> dict:
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

    우선순위: Kling > Veo > Mock
    provider가 None이면 API 키 유무로 자동 선택.
    """
    if provider == "mock":
        return MockVideoGenerator(delay_seconds=5)
    if provider == "kling":
        return KlingVideoGenerator()
    if provider == "veo":
        return VeoVideoGenerator()

    # 자동 선택: Kling 키 있으면 Kling, 없으면 Veo, 없으면 Mock
    if settings.KLING_API_KEY:
        return KlingVideoGenerator()
    if settings.GOOGLE_API_KEY:
        return VeoVideoGenerator()
    return MockVideoGenerator(delay_seconds=5)
