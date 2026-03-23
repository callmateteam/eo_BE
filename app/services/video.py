"""영상 생성 서비스 (Hailuo + Pika + Veo + Mock)"""

from __future__ import annotations

import asyncio
import io
import logging
import uuid
from abc import ABC, abstractmethod

import httpx

from app.core.config import settings
from app.core.s3 import upload_image

logger = logging.getLogger(__name__)

# 이미지 최소 크기 (Hailuo API 요구사항)
_MIN_IMAGE_SIZE = 300


async def ensure_min_image_size(image_url: str, user_id: str = "system") -> str:
    """이미지가 300x300 미만이면 업스케일 후 S3에 재업로드, 새 URL 반환"""
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url)
            resp.raise_for_status()
            img_data = resp.content

        # PIL로 크기 확인
        from PIL import Image

        img = Image.open(io.BytesIO(img_data))
        w, h = img.size

        if w >= _MIN_IMAGE_SIZE and h >= _MIN_IMAGE_SIZE:
            return image_url  # 크기 충분

        # 업스케일: 최소 300x300 이상으로
        scale = max(_MIN_IMAGE_SIZE / w, _MIN_IMAGE_SIZE / h, 1.0)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

        logger.warning(
            "이미지 업스케일: %dx%d → %dx%d (%s)",
            w, h, new_w, new_h, image_url.split("/")[-1],
        )

        # S3에 재업로드
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        new_url = await asyncio.to_thread(
            upload_image,
            buf.getvalue(),
            user_id,
            content_type="image/png",
            folder="upscaled-images",
        )
        return new_url
    except Exception:
        logger.exception("이미지 크기 검증/업스케일 실패: %s", image_url)
        return image_url  # 실패 시 원본 그대로 반환

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

        # fal.ai 응답에서 제공하는 URL 사용
        status_url = data.get(
            "status_url",
            f"https://queue.fal.run/fal-ai/pika/requests/{request_id}/status",
        )
        response_url = data.get(
            "response_url",
            f"https://queue.fal.run/fal-ai/pika/requests/{request_id}",
        )

        logger.info("Pika 요청 시작: request_id=%s", request_id)

        video_url = await self._poll_result(request_id, status_url, response_url)
        return video_url

    async def _poll_result(self, request_id: str, status_url: str, result_url: str) -> str:
        """Pika 작업 완료까지 폴링"""
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
            self._result_base = (
                "https://queue.fal.run/fal-ai/minimax/hailuo-02/standard/image-to-video"
            )
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

        # 이미지 크기 검증 + 자동 업스케일 (300x300 미만 방지)
        if image_url:
            image_url = await ensure_min_image_size(image_url)

        body: dict = {
            "prompt": prompt,
            "prompt_optimizer": False,
            "aspect_ratio": aspect_ratio,
        }

        if image_url:
            body["image_url"] = image_url

        # Hailuo-02는 duration, resolution 지원
        if self._model != "live":
            body["duration"] = min(duration, 6)
            body["resolution"] = "768P"

        logger.info(
            "[디버그] Hailuo API 요청: model=%s, aspect_ratio=%s, "
            "prompt_optimizer=%s, has_image=%s, prompt_words=%d",
            self._model, body.get("aspect_ratio"), body.get("prompt_optimizer"),
            bool(body.get("image_url")), len(body.get("prompt", "").split()),
        )

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(self._base, json=body, headers=headers)
            if resp.status_code != 200:
                error_text = resp.text[:500]
                logger.error(
                    "Hailuo 요청 실패 (%d): %s", resp.status_code, error_text,
                )
                # 이미지 크기 관련 에러 감지
                if "dimensions" in error_text.lower() or "small" in error_text.lower():
                    raise RuntimeError(
                        f"이미지 크기가 너무 작습니다 (최소 300x300). "
                        f"이미지 URL: {image_url}"
                    )
                resp.raise_for_status()
            data = resp.json()

        request_id = data.get("request_id")
        if not request_id:
            raise RuntimeError(f"Hailuo 응답에 request_id 없음: {data}")

        # fal.ai 응답에서 제공하는 URL 사용 (앱별로 경로가 다를 수 있음)
        status_url = data.get("status_url", f"{self._result_base}/requests/{request_id}/status")
        response_url = data.get("response_url", f"{self._result_base}/requests/{request_id}")

        logger.info("Hailuo(%s) 요청 시작: request_id=%s", self._model, request_id)

        video_url = await self._poll_result(request_id, status_url, response_url)
        return video_url

    async def _poll_result(self, request_id: str, status_url: str, result_url: str) -> str:
        """Hailuo 작업 완료까지 폴링"""
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
                    if result_resp.status_code != 200:
                        body_text = result_resp.text[:500]
                        logger.error(
                            "Hailuo 결과 조회 실패: %d %s",
                            result_resp.status_code,
                            body_text,
                        )
                        raise RuntimeError(
                            f"Hailuo 결과 조회 실패 ({result_resp.status_code}): {body_text}"
                        )
                    result = result_resp.json()

                    # ── 디버그 로깅: Hailuo 응답 전체 구조 ──
                    video = result.get("video", {})
                    logger.info(
                        "[디버그] Hailuo 응답 키: %s, video 키: %s",
                        list(result.keys()),
                        list(video.keys()) if isinstance(video, dict) else type(video),
                    )
                    # 해상도 정보가 응답에 포함될 경우 로깅
                    v_width = video.get("width") or result.get("width")
                    v_height = video.get("height") or result.get("height")
                    v_duration = video.get("duration") or result.get("duration")
                    logger.info(
                        "[디버그] Hailuo 출력: width=%s, height=%s, "
                        "duration=%s, request_id=%s",
                        v_width, v_height, v_duration, request_id,
                    )

                    url = video.get("url", "")
                    if not url:
                        raise RuntimeError(f"Hailuo 영상 URL 없음: {result}")
                    return url

                if status == "FAILED":
                    error_detail = status_data.get("error", status_data)
                    logger.error("Hailuo 영상 생성 실패: %s", error_detail)
                    raise RuntimeError(f"Hailuo 영상 생성 실패: {error_detail}")

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
