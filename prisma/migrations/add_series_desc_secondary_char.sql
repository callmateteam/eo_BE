-- 1. characters.art_style 200 → 1000
ALTER TABLE characters ALTER COLUMN art_style TYPE VARCHAR(1000);

-- 2. characters.world_context 500 → 2000
ALTER TABLE characters ALTER COLUMN world_context TYPE VARCHAR(2000);

-- 3. characters.series_description 신규
ALTER TABLE characters ADD COLUMN IF NOT EXISTS series_description VARCHAR(1000) DEFAULT '';

-- 4. storyboard_scenes.secondary_character 신규
ALTER TABLE storyboard_scenes ADD COLUMN IF NOT EXISTS secondary_character VARCHAR(100);

-- 5. storyboard_scenes.secondary_character_desc 신규
ALTER TABLE storyboard_scenes ADD COLUMN IF NOT EXISTS secondary_character_desc VARCHAR(1000);
