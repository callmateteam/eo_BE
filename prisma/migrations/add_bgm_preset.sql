-- CreateTable: bgm_presets
CREATE TABLE IF NOT EXISTS "bgm_presets" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "name" VARCHAR(50) NOT NULL,
    "display_name" VARCHAR(50) NOT NULL,
    "s3_key" VARCHAR(200) NOT NULL,
    "duration" DOUBLE PRECISION NOT NULL,
    "integrated_lufs" DOUBLE PRECISION NOT NULL,
    "energy_profile" JSONB NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "bgm_presets_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX IF NOT EXISTS "bgm_presets_name_key" ON "bgm_presets"("name");
