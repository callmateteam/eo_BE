"""영상 생성 서비스 - Kling AI"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

import httpx
import jwt

from app.core.config import settings


# ---------------------------------------------------------------------------
# 추상 인터페이스 (나중에 다른 모델 추가 시 확장)
# ---------------------------------------------------------------------------
class VideoGenerator(ABC):
    """영상 생성 모델 추상 인터페이스"""

    @abstractmethod
    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        mode: str = "pro",
        aspect_ratio: str = "9:16",
    ) -> str:
        """영상 생성 요청 → task_id 반환"""

    @abstractmethod
    async def get_status(self, task_id: str) -> dict:
        """작업 상태 조회 → {status, video_url, duration, error}"""


# ---------------------------------------------------------------------------
# Kling 구현
# ---------------------------------------------------------------------------
KLING_BASE_URL = "https://api.klingai.com"


class KlingGenerator(VideoGenerator):
    """Kling AI 영상 생성기"""

    def __init__(
        self,
        access_key: str = "",
        secret_key: str = "",
        model: str = "kling-v2-1",
    ) -> None:
        self.access_key = access_key or settings.KLING_ACCESS_KEY
        self.secret_key = secret_key or settings.KLING_SECRET_KEY
        self.model = model

    def _create_jwt(self) -> str:
        """AK/SK로 JWT 토큰 생성 (30분 유효)"""
        now = int(time.time())
        payload = {
            "iss": self.access_key,
            "iat": now,
            "exp": now + 1800,
            "nbf": now - 5,
        }
        return jwt.encode(payload, self.secret_key, algorithm="HS256")

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._create_jwt()}",
            "Content-Type": "application/json",
        }

    async def generate(
        self,
        prompt: str,
        *,
        image_url: str | None = None,
        duration: int = 5,
        mode: str = "pro",
        aspect_ratio: str = "9:16",
    ) -> str:
        """Kling 영상 생성 요청"""
        if image_url:
            endpoint = f"{KLING_BASE_URL}/v1/videos/image2video"
            body: dict = {
                "model_name": self.model,
                "image": image_url,
                "prompt": prompt,
                "mode": mode,
                "duration": str(duration),
                "aspect_ratio": aspect_ratio,
                "cfg_scale": 0.4,
            }
        else:
            endpoint = f"{KLING_BASE_URL}/v1/videos/text2video"
            body = {
                "model_name": self.model,
                "prompt": prompt,
                "negative_prompt": (
                    "blurry, low quality, text, watermark, deformed, extra limbs, bad anatomy"
                ),
                "mode": mode,
                "duration": str(duration),
                "aspect_ratio": aspect_ratio,
            }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(endpoint, json=body, headers=self._headers())
            resp.raise_for_status()
            data = resp.json()

        if data.get("code") != 0:
            raise RuntimeError(f"Kling API 오류: {data.get('message')}")

        return data["data"]["task_id"]

    async def get_status(self, task_id: str) -> dict:
        """Kling 작업 상태 조회"""
        for path in ("text2video", "image2video"):
            url = f"{KLING_BASE_URL}/v1/videos/{path}/{task_id}"
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(url, headers=self._headers())
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("code") == 0:
                        return self._parse_status(data["data"])

        return {"status": "unknown", "video_url": None, "duration": None, "error": "Task not found"}

    @staticmethod
    def _parse_status(data: dict) -> dict:
        """Kling 응답을 통일 포맷으로 변환"""
        status = data.get("task_status", "unknown")
        result: dict = {
            "status": status,
            "video_url": None,
            "duration": None,
            "error": None,
        }

        if status == "succeed":
            videos = data.get("task_result", {}).get("videos", [])
            if videos:
                result["video_url"] = videos[0].get("url")
                result["duration"] = videos[0].get("duration")
        elif status == "failed":
            result["error"] = data.get("task_status_msg", "생성 실패")

        return result


# ---------------------------------------------------------------------------
# 팩토리
# ---------------------------------------------------------------------------
def get_generator(provider: str = "kling") -> VideoGenerator:
    """제공자에 따라 적절한 VideoGenerator 반환"""
    return KlingGenerator()
