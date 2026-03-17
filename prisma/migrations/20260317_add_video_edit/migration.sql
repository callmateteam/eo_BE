-- CreateTable
CREATE TABLE "video_edits" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "storyboard_id" UUID NOT NULL,
    "edit_data" JSONB NOT NULL,
    "version" INTEGER NOT NULL DEFAULT 1,
    "user_id" UUID NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,
    "updated_at" TIMESTAMP(3) NOT NULL,

    CONSTRAINT "video_edits_pkey" PRIMARY KEY ("id")
);

-- CreateTable
CREATE TABLE "video_edit_histories" (
    "id" UUID NOT NULL DEFAULT gen_random_uuid(),
    "edit_id" UUID NOT NULL,
    "version" INTEGER NOT NULL,
    "edit_data" JSONB NOT NULL,
    "created_at" TIMESTAMP(3) NOT NULL DEFAULT CURRENT_TIMESTAMP,

    CONSTRAINT "video_edit_histories_pkey" PRIMARY KEY ("id")
);

-- CreateIndex
CREATE UNIQUE INDEX "video_edits_storyboard_id_key" ON "video_edits"("storyboard_id");

-- CreateIndex
CREATE INDEX "video_edits_user_id_idx" ON "video_edits"("user_id");

-- CreateIndex
CREATE INDEX "video_edit_histories_edit_id_version_idx" ON "video_edit_histories"("edit_id", "version");

-- AddForeignKey
ALTER TABLE "video_edits" ADD CONSTRAINT "video_edits_storyboard_id_fkey" FOREIGN KEY ("storyboard_id") REFERENCES "storyboards"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "video_edits" ADD CONSTRAINT "video_edits_user_id_fkey" FOREIGN KEY ("user_id") REFERENCES "users"("id") ON DELETE CASCADE ON UPDATE CASCADE;

-- AddForeignKey
ALTER TABLE "video_edit_histories" ADD CONSTRAINT "video_edit_histories_edit_id_fkey" FOREIGN KEY ("edit_id") REFERENCES "video_edits"("id") ON DELETE CASCADE ON UPDATE CASCADE;
