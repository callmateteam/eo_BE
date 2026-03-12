from __future__ import annotations

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

from app.core.security import create_access_token

# ──────────────────────────────────────────────
# 아이디 검증 API 테스트
# ──────────────────────────────────────────────


class TestValidateUsername:
    """POST /api/auth/validate-username"""

    async def test_valid_username(self, client, mock_db):
        """정상 아이디 검증 성공"""
        mock_db.user.find_unique = AsyncMock(return_value=None)

        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "testuser"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["available"] is True
        assert data["verification_token"] is not None
        assert data["message"] == "사용 가능한 아이디입니다."

    async def test_username_with_numbers(self, client, mock_db):
        """영문+숫자 조합 아이디"""
        mock_db.user.find_unique = AsyncMock(return_value=None)

        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "user123"},
        )
        assert response.status_code == 200
        assert response.json()["available"] is True

    async def test_username_only_numbers_rejected(self, client):
        """숫자만으로 된 아이디 거부"""
        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "123456"},
        )
        assert response.status_code == 422
        body = response.json()
        assert any(
            "영문" in str(e.get("msg", "")) or "영문" in str(e) for e in body.get("detail", [{}])
        )

    async def test_username_too_short(self, client):
        """4자 미만 아이디 거부"""
        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "ab"},
        )
        assert response.status_code == 422

    async def test_username_too_long(self, client):
        """20자 초과 아이디 거부"""
        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "a" * 21},
        )
        assert response.status_code == 422

    async def test_username_special_chars_rejected(self, client):
        """특수문자 포함 아이디 거부"""
        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "user@name"},
        )
        assert response.status_code == 422

    async def test_username_already_taken(self, client, mock_db):
        """이미 사용 중인 아이디"""
        existing_user = MagicMock()
        existing_user.username = "taken"
        mock_db.user.find_unique = AsyncMock(return_value=existing_user)

        response = await client.post(
            "/api/auth/validate-username",
            json={"username": "taken"},
        )
        assert response.status_code == 409
        data = response.json()
        assert "이미 사용 중" in data["detail"]["detail"]

    async def test_username_empty(self, client):
        """빈 아이디 거부"""
        response = await client.post(
            "/api/auth/validate-username",
            json={"username": ""},
        )
        assert response.status_code == 422


# ──────────────────────────────────────────────
# 회원가입 API 테스트
# ──────────────────────────────────────────────


class TestSignup:
    """POST /api/auth/signup"""

    async def _get_verification_token(self, client, mock_db, username="testuser"):
        """검증 토큰 발급 헬퍼"""
        mock_db.user.find_unique = AsyncMock(return_value=None)
        resp = await client.post(
            "/api/auth/validate-username",
            json={"username": username},
        )
        return resp.json()["verification_token"]

    async def test_signup_success(self, client, mock_db):
        """정상 회원가입"""
        token = await self._get_verification_token(client, mock_db)

        created_user = MagicMock()
        created_user.id = "550e8400-e29b-41d4-a716-446655440000"
        created_user.username = "testuser"
        mock_db.user.create = AsyncMock(return_value=created_user)

        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "MyPass123!",
                "verification_token": token,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["username"] == "testuser"
        assert data["id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["message"] == "회원가입이 완료되었습니다."

    async def test_signup_without_verification_token(self, client, mock_db):
        """검증 토큰 없이 가입 시도"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "MyPass123!",
                "verification_token": "invalid-token",
            },
        )
        assert response.status_code == 400
        data = response.json()
        assert "검증" in data["detail"]["detail"]

    async def test_signup_password_too_short(self, client, mock_db):
        """8자 미만 비밀번호 거부"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "Ab1!",
                "verification_token": "some-token",
            },
        )
        assert response.status_code == 422

    async def test_signup_password_too_long(self, client, mock_db):
        """64자 이상 비밀번호 거부"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "A1!" + "a" * 62,
                "verification_token": "some-token",
            },
        )
        assert response.status_code == 422

    async def test_signup_password_no_special_char(self, client, mock_db):
        """특수문자 없는 비밀번호 거부"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "MyPass1234",
                "verification_token": "some-token",
            },
        )
        assert response.status_code == 422

    async def test_signup_password_no_number(self, client, mock_db):
        """숫자 없는 비밀번호 거부"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "MyPass!!!",
                "verification_token": "some-token",
            },
        )
        assert response.status_code == 422

    async def test_signup_password_no_letter(self, client, mock_db):
        """영문 없는 비밀번호 거부"""
        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "12345678!",
                "verification_token": "some-token",
            },
        )
        assert response.status_code == 422

    async def test_signup_duplicate_username_after_verify(self, client, mock_db):
        """검증 후 다른 사용자가 먼저 가입한 경우"""
        token = await self._get_verification_token(client, mock_db)

        # 가입 시점에는 이미 존재하는 유저
        existing = MagicMock()
        existing.username = "testuser"
        mock_db.user.find_unique = AsyncMock(return_value=existing)

        response = await client.post(
            "/api/auth/signup",
            json={
                "username": "testuser",
                "password": "MyPass123!",
                "verification_token": token,
            },
        )
        assert response.status_code == 409


# ──────────────────────────────────────────────
# 로그인 API 테스트 (쿠키 기반)
# ──────────────────────────────────────────────


class TestLogin:
    """POST /api/auth/login"""

    async def test_login_success_sets_cookies(self, client, mock_db):
        """정상 로그인 시 쿠키에 토큰 설정"""
        from app.core.security import get_password_hash

        hashed = get_password_hash("MyPass123!")
        user = MagicMock()
        user.id = "550e8400-e29b-41d4-a716-446655440000"
        user.username = "testuser"
        user.password = hashed
        mock_db.user.find_unique = AsyncMock(return_value=user)

        response = await client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "MyPass123!"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["user_id"] == "550e8400-e29b-41d4-a716-446655440000"
        assert data["message"] == "로그인에 성공했습니다."

        # 쿠키 확인
        cookies = {c.name: c for c in response.cookies.jar}
        assert "access_token" in cookies
        assert "refresh_token" in cookies

    async def test_login_cookies_are_httponly(self, client, mock_db):
        """쿠키가 HttpOnly로 설정되는지 확인"""
        from app.core.security import get_password_hash

        hashed = get_password_hash("MyPass123!")
        user = MagicMock()
        user.id = "some-uuid"
        user.username = "testuser"
        user.password = hashed
        mock_db.user.find_unique = AsyncMock(return_value=user)

        response = await client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "MyPass123!"},
        )
        # Set-Cookie 헤더에 httponly가 포함되어야 함
        set_cookie_headers = response.headers.get_list("set-cookie")
        for header in set_cookie_headers:
            assert "httponly" in header.lower()

    async def test_login_wrong_password(self, client, mock_db):
        """잘못된 비밀번호"""
        from app.core.security import get_password_hash

        hashed = get_password_hash("MyPass123!")
        user = MagicMock()
        user.id = "some-id"
        user.username = "testuser"
        user.password = hashed
        mock_db.user.find_unique = AsyncMock(return_value=user)

        response = await client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": "WrongPass1!"},
        )
        assert response.status_code == 401
        data = response.json()
        assert "실패" in data["detail"]["detail"]

    async def test_login_nonexistent_user(self, client, mock_db):
        """존재하지 않는 유저"""
        mock_db.user.find_unique = AsyncMock(return_value=None)

        response = await client.post(
            "/api/auth/login",
            json={"username": "nouser", "password": "MyPass123!"},
        )
        assert response.status_code == 401

    async def test_login_empty_username(self, client, mock_db):
        """빈 아이디"""
        response = await client.post(
            "/api/auth/login",
            json={"username": "", "password": "MyPass123!"},
        )
        assert response.status_code == 422

    async def test_login_empty_password(self, client, mock_db):
        """빈 비밀번호"""
        response = await client.post(
            "/api/auth/login",
            json={"username": "testuser", "password": ""},
        )
        assert response.status_code == 422


# ──────────────────────────────────────────────
# 토큰 갱신 API 테스트
# ──────────────────────────────────────────────


class TestRefresh:
    """POST /api/auth/refresh"""

    async def test_refresh_success(self, client, mock_db):
        """리프레시 토큰으로 액세스 토큰 갱신"""
        # 리프레시 토큰 검증 시 반환할 유저+레코드
        mock_record = MagicMock()
        mock_record.id = "token-record-id"
        mock_record.expiresAt = __import__("datetime").datetime(
            2099, 1, 1, tzinfo=__import__("datetime").timezone.utc
        )
        mock_record.user = MagicMock()
        mock_record.user.id = "user-uuid-123"
        mock_record.user.username = "testuser"
        mock_db.refreshtoken.find_unique = AsyncMock(return_value=mock_record)

        response = await client.post(
            "/api/auth/refresh",
            cookies={"refresh_token": "valid-refresh-token"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["username"] == "testuser"
        assert data["message"] == "토큰이 갱신되었습니다."

        # 새 쿠키 발급 확인
        cookies = {c.name: c for c in response.cookies.jar}
        assert "access_token" in cookies

    async def test_refresh_no_token(self, client, mock_db):
        """리프레시 토큰 없이 갱신 시도"""
        response = await client.post("/api/auth/refresh")
        assert response.status_code == 401
        assert "리프레시 토큰이 없습니다" in response.json()["detail"]

    async def test_refresh_expired_token(self, client, mock_db):
        """만료된 리프레시 토큰"""
        mock_db.refreshtoken.find_unique = AsyncMock(return_value=None)

        response = await client.post(
            "/api/auth/refresh",
            cookies={"refresh_token": "expired-token"},
        )
        assert response.status_code == 401


# ──────────────────────────────────────────────
# 로그아웃 API 테스트
# ──────────────────────────────────────────────


class TestLogout:
    """POST /api/auth/logout"""

    async def test_logout_success(self, client, mock_db):
        """정상 로그아웃 - 쿠키 삭제"""
        access_token = create_access_token(subject="user-uuid-123")
        user = MagicMock()
        user.id = "user-uuid-123"
        user.username = "testuser"
        mock_db.user.find_unique = AsyncMock(return_value=user)

        response = await client.post(
            "/api/auth/logout",
            cookies={
                "access_token": access_token,
                "refresh_token": "some-refresh-token",
            },
        )
        assert response.status_code == 200
        assert response.json()["message"] == "로그아웃되었습니다."

    async def test_logout_no_auth(self, client, mock_db):
        """인증 없이 로그아웃 시도"""
        response = await client.post("/api/auth/logout")
        assert response.status_code == 401

    async def test_logout_expired_access_token(self, client, mock_db):
        """만료된 액세스 토큰으로 로그아웃 시도"""
        expired = create_access_token(subject="user-uuid-123", expires_delta=timedelta(minutes=-1))
        response = await client.post(
            "/api/auth/logout",
            cookies={"access_token": expired},
        )
        assert response.status_code == 401
