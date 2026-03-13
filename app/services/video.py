"""영상 생성 서비스 (placeholder)"""

from __future__ import annotations

from abc import ABC, abstractmethod


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


def get_generator(provider: str = "default") -> VideoGenerator:
    """제공자에 따라 적절한 VideoGenerator 반환"""
    raise NotImplementedError(f"영상 생성 provider '{provider}'는 아직 구현되지 않았습니다.")
