-- CreateEnum
CREATE TYPE "CharacterCategory" AS ENUM ('MEME', 'ACTION', 'CUTE', 'BEAUTY');

-- CreateEnum
CREATE TYPE "ProjectStatus" AS ENUM ('CREATED', 'SCRIPT_WRITTEN', 'VOICE_GENERATED', 'VIDEO_GENERATED', 'COMPLETED');

-- CreateTable
CREATE TABLE "users" (
    "id" UUID NOT NULL,
    "username" VARCHAR(50) NOT NULL,
    "password" VARCHAR(255) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Seoul'),
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "users_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "characters" (
    "id" UUID NOT NULL,
    "name" VARCHAR(50) NOT NULL,
    "name_en" VARCHAR(100) NOT NULL,
    "series" VARCHAR(100) NOT NULL,
    "category" "CharacterCategory" NOT NULL,
    "image_url" VARCHAR(500) NOT NULL,
    "thumbnail_url" VARCHAR(500) NOT NULL,
    "description" VARCHAR(500) NOT NULL,
    "prompt_features" VARCHAR(1000) NOT NULL,
    "body_type" VARCHAR(50) NOT NULL,
    "primary_color" VARCHAR(30) NOT NULL,
    "sort_order" INTEGER NOT NULL DEFAULT 0,
    "is_active" BOOLEAN NOT NULL DEFAULT true,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Seoul'),

    CONSTRAINT "characters_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "projects" (
    "id" UUID NOT NULL,
    "title" VARCHAR(100) NOT NULL,
    "character_id" UUID NOT NULL,
    "status" "ProjectStatus" NOT NULL DEFAULT 'CREATED',
    "user_id" UUID NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Seoul'),
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "projects_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "refresh_tokens" (
    "id" UUID NOT NULL,
    "token" VARCHAR(255) NOT NULL,
    "user_id" UUID NOT NULL,
    "expires_at" TIMESTAMP(3) NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT (now() AT TIME ZONE 'Asia/Seoul'),

    CONSTRAINT "refresh_tokens_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "users_username_key" ON "users"("username");

-- CreateIndex
CREATE INDEX "characters_category_idx" ON "characters"("category");

-- CreateIndex
CREATE INDEX "characters_is_active_idx" ON "characters"("is_active");

-- CreateIndex
CREATE INDEX "projects_user_id_idx" ON "projects"("user_id");

-- CreateIndex
CREATE INDEX "projects_character_id_idx" ON "projects"("character_id");

-- CreateIndex
CREATE UNIQUE INDEX "refresh_tokens_token_key" ON "refresh_tokens"("token");

-- CreateIndex
CREATE INDEX "refresh_tokens_user_id_idx" ON "refresh_tokens"("user_id");

-- CreateIndex
CREATE INDEX "refresh_tokens_token_idx" ON "refresh_tokens"("token");

-- AddForeignKey
ALTER TABLE "projects" ADD CONSTRAINT "projects_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "projects" ADD CONSTRAINT "projects_character_id_fkey" FOREIGN KEY ("character_id") REFERENCES "characters"("id") ON DELETE RESTRICT ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "refresh_tokens" ADD CONSTRAINT "refresh_tokens_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;
