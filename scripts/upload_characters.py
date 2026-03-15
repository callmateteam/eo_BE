"""캐릭터 실제 이미지 → 배경 제거 → 리사이즈 → S3 업로드 스크립트"""

from __future__ import annotations

import io
import os
import sys
from pathlib import Path

import boto3
from dotenv import load_dotenv
from PIL import Image
from rembg import remove

load_dotenv()

S3_BUCKET = "eo-character-assets"
S3_REGION = "ap-northeast-2"
S3_BASE_URL = f"https://{S3_BUCKET}.s3.{S3_REGION}.amazonaws.com"

ASSETS_DIR = Path(__file__).parent.parent / "assets" / "characters"

# VILLAIN 카테고리 제외한 20캐릭터
CHARACTERS = [
    "anya-forger",
    "monkey-d-luffy",
    "uzumaki-naruto",
    "denji",
    "itadori-yuji",
    "gojo-satoru",
    "levi-ackerman",
    "eren-yeager",
    "kamado-tanjiro",
    "kurosaki-ichigo",
    "pikachu",
    "kamado-nezuko",
    "totoro",
    "doraemon",
    "tony-tony-chopper",
    "rem",
    "asuna-yuuki",
    "mikasa-ackerman",
    "power",
    "killua-zoldyck",
]


def find_image(key: str) -> Path | None:
    """assets/characters/ 에서 key에 매칭되는 이미지 파일 찾기"""
    for ext in ("png", "jpg", "jpeg", "webp"):
        path = ASSETS_DIR / f"{key}.{ext}"
        if path.exists():
            return path
    return None


def process_image(path: Path, size: tuple[int, int]) -> bytes:
    """배경 제거 → 정사각형 패딩 → 리사이즈 → PNG 바이트"""
    with open(path, "rb") as f:
        raw = f.read()

    # 배경 제거 (투명 배경)
    removed = remove(raw)
    img = Image.open(io.BytesIO(removed)).convert("RGBA")

    # 정사각형으로 패딩 (긴 쪽 기준)
    max_side = max(img.width, img.height)
    square = Image.new("RGBA", (max_side, max_side), (0, 0, 0, 0))
    offset_x = (max_side - img.width) // 2
    offset_y = (max_side - img.height) // 2
    square.paste(img, (offset_x, offset_y), img)

    # 리사이즈
    resized = square.resize(size, Image.LANCZOS)

    buf = io.BytesIO()
    resized.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def upload_to_s3(s3_client, key: str, data: bytes):
    """S3에 파일 업로드"""
    s3_client.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=data,
        ContentType="image/png",
    )


def main():
    s3 = boto3.client(
        "s3",
        region_name=S3_REGION,
        aws_access_key_id=os.environ.get("AWS_ACCESS_KEY_ID"),
        aws_secret_access_key=os.environ.get("AWS_SECRET_ACCESS_KEY"),
    )

    print(f"S3 버킷: {S3_BUCKET}")
    print(f"에셋 폴더: {ASSETS_DIR}")
    print(f"캐릭터 수: {len(CHARACTERS)}\n")

    success = 0
    errors = []

    for key in CHARACTERS:
        path = find_image(key)
        if not path:
            errors.append(f"  ✗ {key} - 이미지 파일 없음")
            continue

        try:
            print(f"  처리 중: {key} ({path.name})...", end=" ", flush=True)

            # 원본 (512x512)
            img_data = process_image(path, (512, 512))
            img_key = f"characters/{key}/image.png"
            upload_to_s3(s3, img_key, img_data)

            # 썸네일 (128x128)
            thumb_data = process_image(path, (128, 128))
            thumb_key = f"characters/{key}/thumbnail.png"
            upload_to_s3(s3, thumb_key, thumb_data)

            print("✓")
            success += 1

        except Exception as e:
            print(f"✗ ({e})")
            errors.append(f"  ✗ {key} - {e}")

    print(f"\n완료: {success}/{len(CHARACTERS)} 성공")
    if errors:
        print("실패:")
        for err in errors:
            print(err)

    return success


if __name__ == "__main__":
    if not os.environ.get("AWS_ACCESS_KEY_ID"):
        print("AWS_ACCESS_KEY_ID 환경변수를 설정해주세요")
        sys.exit(1)
    main()
