"""프롬프트 최적화 엔진 테스트"""

from __future__ import annotations

from app.services.prompt_optimizer import (
    _clean_prompt,
    _enforce_limit,
    _extract_action,
    _select_camera,
    optimize_scene_prompt,
)


class TestOptimizeScenePrompt:
    """optimize_scene_prompt() 통합 테스트"""

    def test_basic_prompt_structure(self):
        """기본 프롬프트에 캐릭터 + 장면 + 품질 부스터 포함"""
        result = optimize_scene_prompt(
            scene_content="캐릭터가 거리를 걷는다",
            character_desc="small reindeer with pink hat",
            has_character=True,
        )
        assert "same character throughout: small reindeer with pink hat" in result
        assert "cinematic lighting" in result
        assert "professional quality" in result

    def test_no_character(self):
        """캐릭터 미등장 장면 → 캐릭터 설명 없음"""
        result = optimize_scene_prompt(
            scene_content="도시 전경이 펼쳐진다",
            character_desc="small reindeer with pink hat",
            has_character=False,
        )
        assert "same character throughout" not in result

    def test_image_prompt_priority(self):
        """image_prompt가 있으면 scene_content보다 우선"""
        result = optimize_scene_prompt(
            scene_content="한글 장면 설명",
            character_desc="a cat",
            image_prompt="a cute cat walking in the park, sunny day",
        )
        assert "walking in the park" in result
        assert "한글 장면 설명" not in result

    def test_bgm_mood_lighting(self):
        """bgm_mood에 따른 조명 키워드 삽입"""
        result = optimize_scene_prompt(
            scene_content="전투 장면",
            character_desc="warrior",
            bgm_mood="epic",
        )
        assert "golden hour" in result

    def test_camera_first_scene_wide(self):
        """첫 장면 → wide establishing shot"""
        result = optimize_scene_prompt(
            scene_content="오프닝",
            character_desc="hero",
            scene_order=1,
            total_scenes=5,
        )
        assert "wide establishing shot" in result

    def test_camera_last_scene_close(self):
        """마지막 장면 → close-up shot"""
        result = optimize_scene_prompt(
            scene_content="클로징",
            character_desc="hero",
            scene_order=5,
            total_scenes=5,
        )
        assert "close-up shot" in result

    def test_camera_middle_scene_medium(self):
        """중간 장면 → medium shot"""
        result = optimize_scene_prompt(
            scene_content="대화 장면",
            character_desc="hero",
            scene_order=3,
            total_scenes=5,
        )
        assert "medium shot" in result

    def test_character_desc_preserved_when_long(self):
        """긴 프롬프트에서도 캐릭터 설명은 잘리지 않음"""
        long_char = "a " + "very detailed " * 30 + "character"
        result = optimize_scene_prompt(
            scene_content="장면 설명 " * 50,
            character_desc=long_char,
        )
        assert long_char in result

    def test_max_length_950(self):
        """프롬프트 길이가 950자를 초과하지 않음"""
        result = optimize_scene_prompt(
            scene_content="very long scene " * 100,
            character_desc="short desc",
            image_prompt="detailed image prompt " * 50,
            bgm_mood="epic",
        )
        assert len(result) <= 950


class TestCleanPrompt:
    """_clean_prompt() 단위 테스트"""

    def test_removes_filler_words(self):
        result = _clean_prompt("very beautiful stunning landscape")
        assert "very" not in result
        assert "beautiful" not in result
        assert "stunning" not in result
        assert "landscape" in result

    def test_preserves_meaningful_words(self):
        result = _clean_prompt("a cat walking in the park")
        assert result == "a cat walking in the park"

    def test_removes_hyper_realistic(self):
        result = _clean_prompt("hyper realistic cat photo")
        assert "hyper realistic" not in result
        assert "cat photo" in result


class TestExtractAction:
    """_extract_action() 단위 테스트"""

    def test_truncates_long_content(self):
        long_content = "가" * 300
        result = _extract_action(long_content)
        assert len(result) == 200

    def test_preserves_short_content(self):
        result = _extract_action("짧은 내용")
        assert result == "짧은 내용"


class TestSelectCamera:
    """_select_camera() 단위 테스트"""

    def test_first_scene_wide(self):
        assert "wide" in _select_camera(1, 5, 5)

    def test_last_scene_close(self):
        assert "close" in _select_camera(5, 5, 5)

    def test_long_scene_dynamic(self):
        assert "dynamic" in _select_camera(3, 5, 8)

    def test_middle_scene_medium(self):
        assert "medium" in _select_camera(3, 5, 5)


class TestEnforceLimit:
    """_enforce_limit() 단위 테스트"""

    def test_short_prompt_unchanged(self):
        prompt = "short prompt"
        assert _enforce_limit(prompt) == prompt

    def test_long_prompt_truncated(self):
        prompt = ", ".join(f"part{i}" * 10 for i in range(100))
        result = _enforce_limit(prompt, max_chars=100)
        assert len(result) <= 100

    def test_comma_boundary_trimming(self):
        """콤마 단위로 잘라서 문장이 깨지지 않음"""
        prompt = "first part, second part, third part, fourth part"
        result = _enforce_limit(prompt, max_chars=30)
        assert result.endswith("part")
        assert len(result) <= 30
