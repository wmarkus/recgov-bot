"""
Tests for API authentication (src/legacy/api/auth.py)
"""
import pytest
import json
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from src.legacy.api.auth import RecGovAuth, AuthenticationError
from src.common.models import SessionState


class TestAuthenticationError:
    def test_exception_message(self):
        error = AuthenticationError("Test error message")
        assert str(error) == "Test error message"


class TestRecGovAuth:
    def test_init_without_session_file(self):
        auth = RecGovAuth()
        assert auth.session_file is None
        assert isinstance(auth.session, SessionState)
        assert auth.session.logged_in is False

    def test_init_with_session_file(self):
        auth = RecGovAuth(session_file="/tmp/session.json")
        assert auth.session_file == Path("/tmp/session.json")

    def test_is_logged_in_false_initially(self):
        auth = RecGovAuth()
        assert auth.is_logged_in is False

    def test_is_logged_in_true_when_logged_in(self):
        auth = RecGovAuth()
        auth.session.logged_in = True
        auth.session.last_refresh = datetime.now()
        assert auth.is_logged_in is True

    def test_is_logged_in_false_when_expired(self):
        auth = RecGovAuth()
        auth.session.logged_in = True
        auth.session.last_refresh = datetime.now() - timedelta(hours=2)
        assert auth.is_logged_in is False

    def test_get_cookies_empty(self):
        auth = RecGovAuth()
        assert auth.get_cookies() == {}

    def test_get_cookies_returns_copy(self):
        auth = RecGovAuth()
        auth.session.cookies = {"session_id": "abc123"}
        
        cookies = auth.get_cookies()
        cookies["new_cookie"] = "value"
        
        # Original should not be modified
        assert "new_cookie" not in auth.session.cookies

    def test_get_auth_headers_basic(self):
        auth = RecGovAuth()
        headers = auth.get_auth_headers()
        
        assert "Accept" in headers
        assert "Content-Type" in headers
        assert "User-Agent" in headers

    def test_get_auth_headers_with_auth_token(self):
        auth = RecGovAuth()
        auth.session.auth_token = "test_token_123"
        
        headers = auth.get_auth_headers()
        
        assert headers["Authorization"] == "Bearer test_token_123"

    def test_get_auth_headers_with_csrf_token(self):
        auth = RecGovAuth()
        auth.session.csrf_token = "csrf_xyz"
        
        headers = auth.get_auth_headers()
        
        assert headers["X-CSRF-Token"] == "csrf_xyz"

    def test_get_auth_headers_with_both_tokens(self):
        auth = RecGovAuth()
        auth.session.auth_token = "test_token_123"
        auth.session.csrf_token = "csrf_xyz"
        
        headers = auth.get_auth_headers()
        
        assert headers["Authorization"] == "Bearer test_token_123"
        assert headers["X-CSRF-Token"] == "csrf_xyz"

    def test_load_session_no_file(self):
        auth = RecGovAuth()
        result = auth.load_session()
        assert result is None

    def test_load_session_file_not_exists(self):
        auth = RecGovAuth(session_file="/nonexistent/session.json")
        result = auth.load_session()
        assert result is None

    def test_load_session_success(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                data = {
                    "cookies": {"session_id": "abc123"},
                    "local_storage": {},
                    "csrf_token": "csrf_xyz",
                    "auth_token": "token_123",
                    "logged_in": True,
                    "last_refresh": "2030-08-01T10:00:00"
                }
                json.dump(data, f)
                f.flush()
                
                auth = RecGovAuth(session_file=f.name)
                result = auth.load_session()
                
                assert result is not None
                assert result.cookies == {"session_id": "abc123"}
                assert result.csrf_token == "csrf_xyz"
                assert result.logged_in is True
            finally:
                os.unlink(f.name)

    def test_load_session_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                f.write("not valid json")
                f.flush()
                
                auth = RecGovAuth(session_file=f.name)
                result = auth.load_session()
                
                assert result is None
            finally:
                os.unlink(f.name)

    @pytest.mark.asyncio
    async def test_login_success(self):
        auth = RecGovAuth()
        
        # Mock HTTP responses
        mock_home_response = MagicMock()
        mock_home_response.cookies = {}
        
        mock_csrf_response = MagicMock()
        mock_csrf_response.status_code = 200
        mock_csrf_response.json = MagicMock(return_value={"csrf": "test_csrf"})
        
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.cookies = {"session_id": "abc123"}
        mock_login_response.json = MagicMock(return_value={"token": "auth_token_123"})
        
        mock_account_response = MagicMock()
        mock_account_response.status_code = 200
        
        auth.client.get = AsyncMock(side_effect=[
            mock_home_response,    # _init_session home
            mock_csrf_response,    # _init_session csrf
            mock_account_response, # _verify_login
        ])
        auth.client.post = AsyncMock(return_value=mock_login_response)
        
        result = await auth.login("test@example.com", "password123")
        
        assert result.logged_in is True
        assert result.auth_token == "auth_token_123"

    @pytest.mark.asyncio
    async def test_login_invalid_credentials(self):
        auth = RecGovAuth()
        
        mock_home_response = MagicMock()
        mock_home_response.cookies = {}
        
        mock_csrf_response = MagicMock()
        mock_csrf_response.status_code = 200
        mock_csrf_response.json = MagicMock(return_value={})
        
        mock_login_response = MagicMock()
        mock_login_response.status_code = 401
        
        auth.client.get = AsyncMock(side_effect=[mock_home_response, mock_csrf_response])
        auth.client.post = AsyncMock(return_value=mock_login_response)
        
        with pytest.raises(AuthenticationError, match="Invalid email or password"):
            await auth.login("test@example.com", "wrong_password")

    @pytest.mark.asyncio
    async def test_login_rate_limited(self):
        auth = RecGovAuth()
        
        mock_home_response = MagicMock()
        mock_home_response.cookies = {}
        
        mock_csrf_response = MagicMock()
        mock_csrf_response.status_code = 200
        mock_csrf_response.json = MagicMock(return_value={})
        
        mock_login_response = MagicMock()
        mock_login_response.status_code = 429
        
        auth.client.get = AsyncMock(side_effect=[mock_home_response, mock_csrf_response])
        auth.client.post = AsyncMock(return_value=mock_login_response)
        
        with pytest.raises(AuthenticationError, match="Rate limited"):
            await auth.login("test@example.com", "password")

    @pytest.mark.asyncio
    async def test_login_other_error(self):
        auth = RecGovAuth()
        
        mock_home_response = MagicMock()
        mock_home_response.cookies = {}
        
        mock_csrf_response = MagicMock()
        mock_csrf_response.status_code = 200
        mock_csrf_response.json = MagicMock(return_value={})
        
        mock_login_response = MagicMock()
        mock_login_response.status_code = 500
        mock_login_response.text = "Internal Server Error"
        
        auth.client.get = AsyncMock(side_effect=[mock_home_response, mock_csrf_response])
        auth.client.post = AsyncMock(return_value=mock_login_response)
        
        with pytest.raises(AuthenticationError, match="500"):
            await auth.login("test@example.com", "password")

    @pytest.mark.asyncio
    async def test_login_verification_failed(self):
        auth = RecGovAuth()
        
        mock_home_response = MagicMock()
        mock_home_response.cookies = {}
        
        mock_csrf_response = MagicMock()
        mock_csrf_response.status_code = 200
        mock_csrf_response.json = MagicMock(return_value={})
        
        mock_login_response = MagicMock()
        mock_login_response.status_code = 200
        mock_login_response.cookies = {"session_id": "abc123"}
        mock_login_response.json = MagicMock(return_value={})
        
        mock_account_response = MagicMock()
        mock_account_response.status_code = 401  # Verification fails
        
        auth.client.get = AsyncMock(side_effect=[
            mock_home_response,
            mock_csrf_response,
            mock_account_response,
        ])
        auth.client.post = AsyncMock(return_value=mock_login_response)
        
        with pytest.raises(AuthenticationError, match="verification failed"):
            await auth.login("test@example.com", "password")

    @pytest.mark.asyncio
    async def test_refresh_session_success(self):
        auth = RecGovAuth()
        auth.session.cookies = {"session_id": "abc123"}
        
        mock_response = MagicMock()
        mock_response.cookies = {"session_id": "refreshed123"}
        
        auth.client.get = AsyncMock(return_value=mock_response)
        
        result = await auth.refresh_session()
        
        assert result is True
        assert auth.session.cookies["session_id"] == "refreshed123"
        assert auth.session.last_refresh is not None

    @pytest.mark.asyncio
    async def test_refresh_session_failure(self):
        auth = RecGovAuth()
        auth.session.cookies = {"session_id": "abc123"}
        
        auth.client.get = AsyncMock(side_effect=Exception("Network error"))
        
        result = await auth.refresh_session()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_logout(self):
        auth = RecGovAuth()
        auth.session.cookies = {"session_id": "abc123"}
        auth.session.logged_in = True
        
        auth.client.post = AsyncMock()
        
        await auth.logout()
        
        assert auth.session.logged_in is False
        assert auth.session.cookies == {}

    @pytest.mark.asyncio
    async def test_logout_deletes_session_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                f.write("{}")
                f.flush()
                
                auth = RecGovAuth(session_file=f.name)
                auth.session.logged_in = True
                auth.client.post = AsyncMock()
                
                await auth.logout()
                
                assert not Path(f.name).exists()
            except FileNotFoundError:
                pass  # File was deleted as expected

    @pytest.mark.asyncio
    async def test_context_manager(self):
        async with RecGovAuth() as auth:
            assert isinstance(auth, RecGovAuth)

    @pytest.mark.asyncio
    async def test_verify_login_success(self):
        auth = RecGovAuth()
        auth.session.cookies = {"session_id": "abc123"}
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        auth.client.get = AsyncMock(return_value=mock_response)
        
        result = await auth._verify_login()
        
        assert result is True

    @pytest.mark.asyncio
    async def test_verify_login_failure(self):
        auth = RecGovAuth()
        auth.session.cookies = {"session_id": "abc123"}
        
        mock_response = MagicMock()
        mock_response.status_code = 401
        
        auth.client.get = AsyncMock(return_value=mock_response)
        
        result = await auth._verify_login()
        
        assert result is False

    @pytest.mark.asyncio
    async def test_verify_login_exception(self):
        auth = RecGovAuth()
        
        auth.client.get = AsyncMock(side_effect=Exception("Network error"))
        
        result = await auth._verify_login()
        
        assert result is False
