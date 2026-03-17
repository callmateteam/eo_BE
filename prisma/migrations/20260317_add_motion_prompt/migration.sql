-- AlterTable: Add motionPrompt column to storyboard_scenes
ALTER TABLE "storyboard_scenes" ADD COLUMN "motion_prompt" VARCHAR(500) NOT NULL DEFAULT '';
