"""YouTube OAuth 연동 및 영상 업로드 서비스"""

from __future__ import annotations

import logging
import tempfile
from pathlib import Path

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from app.core.config import settings
from app.core.database import db
from app.core.http_client import get_download_client

logger = logging.getLogger(__name__)

YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]

YOUTUBE_TOKEN_URI = "https://oauth2.googleapis.com/token"


async def exchange_code_for_tokens(code: str, redirect_uri: str) -> dict:
    """Authorization code를 access_token + refresh_token으로 교환

    Returns:
        {"access_token": str, "refresh_token": str, "expires_in": int}

    Raises:
        ValueError: 토큰 교환 실패
    """
    client = get_download_client()
    resp = await client.post(
        YOUTUBE_TOKEN_URI,
        data={
            "code": code,
            "client_id": settings.GOOGLE_CLIENT_ID,
            "client_secret": settings.GOOGLE_CLIENT_SECRET,
            "redirect_uri": redirect_uri,
            "grant_type": "authorization_code",
        },
    )

    if resp.status_code != 200:
        logger.error("YouTube 토큰 교환 실패: %s %s", resp.status_code, resp.text)
        raise ValueError("YouTube 인증에 실패했습니다. 다시 시도해주세요.")

    data = resp.json()
    if "refresh_token" not in data:
        raise ValueError(
            "YouTube refresh_token을 받지 못했습니다. "
            "Google 계정 설정에서 앱 액세스를 해제한 후 다시 연동해주세요."
        )

    return {
        "access_token": data["access_token"],
        "refresh_token": data["refresh_token"],
        "expires_in": data.get("expires_in", 3600),
    }


async def get_channel_info(access_token: str) -> dict:
    """YouTube 채널 정보 조회

    Returns:
        {"channel_id": str, "channel_title": str}
    """
    creds = Credentials(token=access_token)
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)
    resp = youtube.channels().list(part="snippet", mine=True).execute()

    items = resp.get("items", [])
    if not items:
        raise ValueError("YouTube 채널을 찾을 수 없습니다.")

    channel = items[0]
    return {
        "channel_id": channel["id"],
        "channel_title": channel["snippet"]["title"],
    }


async def connect_youtube(user_id: str, code: str, redirect_uri: str) -> dict:
    """YouTube 연동: code 교환 → refresh_token 저장 → 채널 정보 반환

    Returns:
        {"channel_title": str}
    """
    tokens = await exchange_code_for_tokens(code, redirect_uri)

    channel_info = await get_channel_info(tokens["access_token"])

    await db.user.update(
        where={"id": user_id},
        data={"googleRefreshToken": tokens["refresh_token"]},
    )

    logger.info(
        "YouTube 연동 완료: user=%s channel=%s",
        user_id,
        channel_info["channel_title"],
    )
    return {"channel_title": channel_info["channel_title"]}


async def disconnect_youtube(user_id: str) -> None:
    """YouTube 연동 해제: refresh_token 삭제"""
    await db.user.update(
        where={"id": user_id},
        data={"googleRefreshToken": None},
    )
    logger.info("YouTube 연동 해제: user=%s", user_id)


def _build_youtube_client(refresh_token: str):
    """refresh_token으로 YouTube API 클라이언트 생성"""
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri=YOUTUBE_TOKEN_URI,
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=YOUTUBE_SCOPES,
    )
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


async def _download_video_from_s3(video_url: str) -> str:
    """S3 URL에서 영상 다운로드 → 임시 파일 경로 반환"""
    client = get_download_client()
    resp = await client.get(video_url)
    resp.raise_for_status()

    tmp = tempfile.NamedTemporaryFile(suffix=".mp4", delete=False)
    tmp.write(resp.content)
    tmp.close()
    return tmp.name


async def upload_to_youtube(
    user_id: str,
    project_id: str,
    *,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    privacy_status: str = "private",
) -> dict:
    """프로젝트 최종 영상을 YouTube에 업로드

    Returns:
        {"youtube_video_id": str, "youtube_url": str}

    Raises:
        ValueError: 업로드 조건 불충족
    """
    user = await db.user.find_unique(where={"id": user_id})
    if not user or not user.googleRefreshToken:
        raise ValueError("YouTube 연동이 필요합니다. 먼저 YouTube 계정을 연동해주세요.")

    project = await db.project.find_unique(
        where={"id": project_id},
        include={"storyboard": True},
    )
    if not project:
        raise ValueError("프로젝트를 찾을 수 없습니다.")

    if project.userId != user_id:
        raise ValueError("본인의 프로젝트만 업로드할 수 있습니다.")

    if not project.storyboard or not project.storyboard.finalVideoUrl:
        raise ValueError("최종 영상이 아직 생성되지 않았습니다.")

    # 업로드 상태 → UPLOADING
    await db.project.update(
        where={"id": project_id},
        data={
            "youtubeUploadStatus": "UPLOADING",
            "youtubeError": None,
        },
    )

    tmp_path = None
    try:
        # S3에서 영상 다운로드
        tmp_path = await _download_video_from_s3(project.storyboard.finalVideoUrl)

        # YouTube 업로드
        youtube = _build_youtube_client(user.googleRefreshToken)

        body = {
            "snippet": {
                "title": title,
                "description": description,
                "tags": tags or [],
                "categoryId": "22",  # People & Blogs
            },
            "status": {
                "privacyStatus": privacy_status,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(
            tmp_path,
            mimetype="video/mp4",
            resumable=True,
            chunksize=10 * 1024 * 1024,  # 10MB 청크
        )

        request = youtube.videos().insert(
            part="snippet,status",
            body=body,
            media_body=media,
        )

        response = None
        while response is None:
            _, response = request.next_chunk()

        video_id = response["id"]
        youtube_url = f"https://www.youtube.com/watch?v={video_id}"

        # 업로드 성공 → DB 업데이트
        await db.project.update(
            where={"id": project_id},
            data={
                "youtubeVideoId": video_id,
                "youtubeUrl": youtube_url,
                "youtubeUploadStatus": "COMPLETED",
                "youtubeError": None,
            },
        )

        logger.info(
            "YouTube 업로드 완료: project=%s video_id=%s",
            project_id,
            video_id,
        )
        return {"youtube_video_id": video_id, "youtube_url": youtube_url}

    except Exception as e:
        error_msg = str(e)[:500]
        await db.project.update(
            where={"id": project_id},
            data={
                "youtubeUploadStatus": "FAILED",
                "youtubeError": error_msg,
            },
        )
        logger.exception("YouTube 업로드 실패: project=%s", project_id)
        raise ValueError(f"YouTube 업로드에 실패했습니다: {error_msg}") from e

    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)
