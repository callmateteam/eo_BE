"""영상 생성 서비스 테스트 (Kling AI + Mock + 팩토리)"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services.video import (
    KlingVideoGenerator,
    MockVideoGenerator,
    VeoVideoGenerator,
    get_generator,
)

# ── get_generator 팩토리 ──


class TestGetGenerator:
    """get_generator() 팩토리 함수 테스트"""

    def test_explicit_mock(self):
        gen = get_generator("mock")
        assert isinstance(gen, MockVideoGenerator)

    def test_explicit_kling(self):
        gen = get_generator("kling")
        assert isinstance(gen, KlingVideoGenerator)

    def test_explicit_veo(self):
        gen = get_generator("veo")
        assert isinstance(gen, VeoVideoGenerator)

    def test_auto_select_kling_when_key_exists(self):
        with patch("app.services.video.settings") as mock_settings:
            mock_settings.KLING_API_KEY = "test-key"
            mock_settings.GOOGLE_API_KEY = ""
            mock_settings.KLING_BASE_URL = "https://kling3api.com"
            mock_settings.KLING_MODEL = "pro-text-to-video"
            mock_settings.KLING_I2V_MODEL = "pro-image-to-video"
            mock_settings.KLING_POLL_INTERVAL = 5
            mock_settings.KLING_MAX_WAIT = 300
            gen = get_generator()
            assert isinstance(gen, KlingVideoGenerator)

    def test_auto_select_veo_when_no_kling_key(self):
        with patch("app.services.video.settings") as mock_settings:
            mock_settings.KLING_API_KEY = ""
            mock_settings.GOOGLE_API_KEY = "google-key"
            mock_settings.VEO_MODEL = "veo-2.0-generate-001"
            gen = get_generator()
            assert isinstance(gen, VeoVideoGenerator)

    def test_auto_select_mock_when_no_keys(self):
        with patch("app.services.video.settings") as mock_settings:
            mock_settings.KLING_API_KEY = ""
            mock_settings.GOOGLE_API_KEY = ""
            gen = get_generator()
            assert isinstance(gen, MockVideoGenerator)


# ── MockVideoGenerator ──


class TestMockVideoGenerator:
    """Mock 영상 생성기 테스트"""

    @pytest.mark.asyncio
    async def test_generate_returns_task_id(self):
        gen = MockVideoGenerator(delay_seconds=0)
        result = await gen.generate("test prompt")
        assert isinstance(result, str)
        assert len(result) == 32  # uuid hex

    @pytest.mark.asyncio
    async def test_get_status_returns_completed(self):
        gen = MockVideoGenerator(delay_seconds=0)
        status = await gen.get_status("any-task-id")
        assert status["status"] == "completed"
        assert status["video_url"] is None

    def test_provider_name(self):
        gen = MockVideoGenerator()
        assert gen.provider_name == "Mock"


# ── KlingVideoGenerator ──


class TestKlingVideoGenerator:
    """Kling AI 영상 생성기 테스트"""

    def _make_generator(self) -> KlingVideoGenerator:
        with patch("app.services.video.settings") as mock_settings:
            mock_settings.KLING_API_KEY = "test-key"
            mock_settings.KLING_BASE_URL = "https://kling3api.com"
            mock_settings.KLING_MODEL = "pro-text-to-video"
            mock_settings.KLING_I2V_MODEL = "pro-image-to-video"
            mock_settings.KLING_POLL_INTERVAL = 0.01
            mock_settings.KLING_MAX_WAIT = 1
            return KlingVideoGenerator()

    def test_provider_name(self):
        gen = self._make_generator()
        assert gen.provider_name == "Kling"

    def test_extract_video_url_dict_format(self):
        """resultUrls dict 형식 추출"""
        gen = self._make_generator()
        task_data = {"response": {"resultUrls": ["https://example.com/video.mp4"]}}
        url = gen._extract_video_url(task_data)
        assert url == "https://example.com/video.mp4"

    def test_extract_video_url_list_format(self):
        """response가 list인 경우"""
        gen = self._make_generator()
        task_data = {"response": ["https://example.com/video.mp4"]}
        url = gen._extract_video_url(task_data)
        assert url == "https://example.com/video.mp4"

    def test_extract_video_url_string_format(self):
        """response가 string인 경우"""
        gen = self._make_generator()
        task_data = {"response": "https://example.com/video.mp4"}
        url = gen._extract_video_url(task_data)
        assert url == "https://example.com/video.mp4"

    def test_extract_video_url_empty_response_raises(self):
        gen = self._make_generator()
        with pytest.raises(RuntimeError, match="response가 없습니다"):
            gen._extract_video_url({"response": None})

    def test_extract_video_url_empty_result_urls_raises(self):
        gen = self._make_generator()
        with pytest.raises(RuntimeError, match="resultUrls가 비어있습니다"):
            gen._extract_video_url({"response": {"resultUrls": []}})

    def test_extract_video_url_empty_list_raises(self):
        """빈 리스트는 falsy → response 없음 에러"""
        gen = self._make_generator()
        with pytest.raises(RuntimeError, match="response가 없습니다"):
            gen._extract_video_url({"response": []})

    @pytest.mark.asyncio
    async def test_generate_text_to_video(self):
        """텍스트 프롬프트만 → pro-text-to-video 사용"""
        gen = self._make_generator()

        mock_generate_resp = MagicMock()
        mock_generate_resp.json.return_value = {
            "code": 200,
            "data": {"task_id": "test-task-123"},
        }
        mock_generate_resp.raise_for_status = MagicMock()

        mock_status_resp = MagicMock()
        mock_status_resp.json.return_value = {
            "code": 200,
            "data": {
                "status": "SUCCESS",
                "response": {"resultUrls": ["https://example.com/video.mp4"]},
            },
        }
        mock_status_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_generate_resp
        mock_client.get.return_value = mock_status_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.video.httpx.AsyncClient", return_value=mock_client):
            result = await gen.generate("test prompt", duration=5)

        assert result == "https://example.com/video.mp4"
        # POST body에 type이 text-to-video인지 확인
        call_args = mock_client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body["type"] == "pro-text-to-video"
        assert "image_url" not in body

    @pytest.mark.asyncio
    async def test_generate_image_to_video(self):
        """이미지 URL 제공 → pro-image-to-video 사용"""
        gen = self._make_generator()

        mock_generate_resp = MagicMock()
        mock_generate_resp.json.return_value = {
            "code": 200,
            "data": {"task_id": "test-task-456"},
        }
        mock_generate_resp.raise_for_status = MagicMock()

        mock_status_resp = MagicMock()
        mock_status_resp.json.return_value = {
            "code": 200,
            "data": {
                "status": "SUCCESS",
                "response": {"resultUrls": ["https://example.com/i2v.mp4"]},
            },
        }
        mock_status_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_generate_resp
        mock_client.get.return_value = mock_status_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.video.httpx.AsyncClient", return_value=mock_client):
            result = await gen.generate(
                "test prompt",
                image_url="https://example.com/char.png",
                duration=5,
            )

        assert result == "https://example.com/i2v.mp4"
        call_args = mock_client.post.call_args
        body = call_args.kwargs.get("json") or call_args[1].get("json")
        assert body["type"] == "pro-image-to-video"
        assert body["image_url"] == "https://example.com/char.png"

    @pytest.mark.asyncio
    async def test_generate_api_error_raises(self):
        """API가 code != 200 반환 시 RuntimeError"""
        gen = self._make_generator()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 402,
            "message": "No available credits",
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.video.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(RuntimeError, match="작업 생성 실패"),
        ):
            await gen.generate("test")

    @pytest.mark.asyncio
    async def test_poll_task_failed_raises(self):
        """폴링 중 FAILED 상태 → RuntimeError"""
        gen = self._make_generator()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 200,
            "data": {
                "status": "FAILED",
                "error_message": "content policy violation",
            },
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("app.services.video.httpx.AsyncClient", return_value=mock_client),
            pytest.raises(RuntimeError, match="영상 생성 실패"),
        ):
            await gen._poll_task("test-task")

    @pytest.mark.asyncio
    async def test_get_status_completed(self):
        """완료된 작업 상태 조회"""
        gen = self._make_generator()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 200,
            "data": {
                "status": "SUCCESS",
                "response": {"resultUrls": ["https://example.com/done.mp4"]},
            },
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.video.httpx.AsyncClient", return_value=mock_client):
            result = await gen.get_status("test-task")

        assert result["status"] == "SUCCESS"
        assert result["video_url"] == "https://example.com/done.mp4"

    @pytest.mark.asyncio
    async def test_get_status_in_progress(self):
        """진행 중 작업 상태 조회"""
        gen = self._make_generator()

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "code": 200,
            "data": {"status": "IN_PROGRESS"},
        }
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.services.video.httpx.AsyncClient", return_value=mock_client):
            result = await gen.get_status("test-task")

        assert result["status"] == "IN_PROGRESS"
        assert result["video_url"] is None
