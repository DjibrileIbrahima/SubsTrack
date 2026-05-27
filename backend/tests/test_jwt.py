"""Unit tests for services/jwt.py"""

import time
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from services.jwt import create_access_token, decode_access_token
from fastapi import HTTPException


class TestCreateAccessToken:
    def test_returns_a_string(self):
        token = create_access_token("user-id-123")
        assert isinstance(token, str)
        assert len(token) > 10

    def test_encodes_user_id(self):
        token = create_access_token("my-user-id")
        user_id = decode_access_token(token)
        assert user_id == "my-user-id"

    def test_different_users_get_different_tokens(self):
        t1 = create_access_token("user-1")
        t2 = create_access_token("user-2")
        assert t1 != t2

    def test_token_is_a_valid_jwt(self):
        import jwt as pyjwt
        import os
        token = create_access_token("test-user")
        payload = pyjwt.decode(token, os.environ["JWT_SECRET"], algorithms=["HS256"])
        assert payload["sub"] == "test-user"
        assert "exp" in payload


class TestDecodeAccessToken:
    def test_valid_token_returns_user_id(self):
        token = create_access_token("abc-123")
        assert decode_access_token(token) == "abc-123"

    def test_expired_token_raises_401(self):
        import jwt as pyjwt
        import os
        payload = {
            "sub": "user-id",
            "exp": datetime.now(timezone.utc) - timedelta(seconds=1),
        }
        expired_token = pyjwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(expired_token)
        assert exc_info.value.status_code == 401
        assert "expired" in exc_info.value.detail.lower()

    def test_tampered_token_raises_401(self):
        token = create_access_token("user-id")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(tampered)
        assert exc_info.value.status_code == 401

    def test_completely_invalid_token_raises_401(self):
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token("this.is.garbage")
        assert exc_info.value.status_code == 401

    def test_token_signed_with_wrong_secret_raises_401(self):
        import jwt as pyjwt
        payload = {"sub": "user-id", "exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        token = pyjwt.encode(payload, "wrong-secret", algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401

    def test_token_without_sub_raises_401(self):
        import jwt as pyjwt
        import os
        payload = {"exp": datetime.now(timezone.utc) + timedelta(hours=1)}
        token = pyjwt.encode(payload, os.environ["JWT_SECRET"], algorithm="HS256")
        with pytest.raises(HTTPException) as exc_info:
            decode_access_token(token)
        assert exc_info.value.status_code == 401
