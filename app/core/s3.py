"""S3 파일 업로드 유틸리티"""

from __future__ import annotations

import uuid

import boto3

from app.core.config import settings


def _get_client():
    """S3 클라이언트 반환"""
    return boto3.client(
        "s3",
        region_name=settings.AWS_REGION,
        aws_access_key_id=settings.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=settings.AWS_SECRET_ACCESS_KEY,
    )


def upload_image(
    data: bytes,
    user_id: str,
    *,
    content_type: str = "image/png",
    folder: str = "custom-characters",
) -> str:
    """이미지를 S3에 업로드하고 URL 반환"""
    ext_map = {
        "image/png": "png",
        "image/webp": "webp",
        "image/jpeg": "jpg",
        "audio/mpeg": "mp3",
        "audio/wav": "wav",
    }
    ext = ext_map.get(content_type, "jpg")
    key = f"{folder}/{user_id}/{uuid.uuid4().hex}.{ext}"

    client = _get_client()
    client.put_object(
        Bucket=settings.S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    return f"https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"


def upload_video(
    data: bytes,
    user_id: str,
    *,
    content_type: str = "video/mp4",
    folder: str = "storyboard-videos",
) -> str:
    """영상을 S3에 업로드하고 URL 반환"""
    key = f"{folder}/{user_id}/{uuid.uuid4().hex}.mp4"

    client = _get_client()
    client.put_object(
        Bucket=settings.S3_BUCKET,
        Key=key,
        Body=data,
        ContentType=content_type,
    )

    return f"https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"
