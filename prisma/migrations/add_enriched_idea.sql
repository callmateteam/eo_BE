-- Add enriched_idea column to projects table
ALTER TABLE "projects" ADD COLUMN "enriched_idea" JSONB;
