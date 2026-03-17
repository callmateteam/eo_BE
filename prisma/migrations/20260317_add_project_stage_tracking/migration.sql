-- AlterTable: Project에 4단계 트래킹 필드 추가
-- characterId를 nullable로 변경 (커스텀 캐릭터만 선택 가능하도록)

-- 1. characterId를 nullable로 변경
ALTER TABLE "projects" ALTER COLUMN "character_id" DROP NOT NULL;

-- 2. 새 컬럼 추가
ALTER TABLE "projects" ADD COLUMN "current_stage" INTEGER NOT NULL DEFAULT 1;
ALTER TABLE "projects" ADD COLUMN "custom_character_id" UUID;
ALTER TABLE "projects" ADD COLUMN "storyboard_id" UUID;
ALTER TABLE "projects" ADD COLUMN "idea" VARCHAR(2000);

-- 3. storyboard_id에 unique 제약조건
ALTER TABLE "projects" ADD CONSTRAINT "projects_storyboard_id_key" UNIQUE ("storyboard_id");

-- 4. 외래키 제약조건
ALTER TABLE "projects" ADD CONSTRAINT "projects_custom_character_id_fkey"
    FOREIGN KEY ("custom_character_id") REFERENCES "custom_characters"("id")
    ON DELETE SET NULL ON UPDATE CASCADE;

ALTER TABLE "projects" ADD CONSTRAINT "projects_storyboard_id_fkey"
    FOREIGN KEY ("storyboard_id") REFERENCES "storyboards"("id")
    ON DELETE SET NULL ON UPDATE CASCADE;

-- 5. 인덱스
CREATE INDEX "projects_custom_character_id_idx" ON "projects"("custom_character_id");
