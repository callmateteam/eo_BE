-- 캐릭터 음성 설정 필드 추가
ALTER TABLE "characters" ADD COLUMN "voice_id" VARCHAR(50) NOT NULL DEFAULT 'alloy';
ALTER TABLE "characters" ADD COLUMN "voice_style" VARCHAR(500) NOT NULL DEFAULT '';

-- 커스텀 캐릭터 음성 설정 필드 추가
ALTER TABLE "custom_characters" ADD COLUMN "voice_id" VARCHAR(50) NOT NULL DEFAULT 'alloy';
ALTER TABLE "custom_characters" ADD COLUMN "voice_style" VARCHAR(500) NOT NULL DEFAULT '';

-- 스토리보드 BGM 무드 필드 추가
ALTER TABLE "storyboards" ADD COLUMN "bgm_mood" VARCHAR(50);

-- 장면 나레이션 필드 추가
ALTER TABLE "storyboard_scenes" ADD COLUMN "narration" VARCHAR(1000);
ALTER TABLE "storyboard_scenes" ADD COLUMN "narration_style" VARCHAR(20) NOT NULL DEFAULT 'none';
ALTER TABLE "storyboard_scenes" ADD COLUMN "narration_url" VARCHAR(500);
