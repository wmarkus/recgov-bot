"""
Tests for browser session management (src/browser/session.py)
"""
import pytest
import json
import tempfile
import os
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from src.browser.session import BrowserSession, SessionHandoff


class TestBrowserSession:
    def test_init_without_file(self):
        session = BrowserSession()
        assert session.session_file is None
        assert session.cookies == []
        assert session.local_storage == {}
        assert session.session_storage == {}
        assert session.logged_in is False
        assert session.last_refresh is None

    def test_init_with_file(self):
        session = BrowserSession(session_file="/tmp/test_session.json")
        assert session.session_file == Path("/tmp/test_session.json")

    def test_save_without_file(self):
        session = BrowserSession()
        session.cookies = [{"name": "test", "value": "value"}]
        # Should not raise, just return
        session.save()

    def test_save_with_file(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                session = BrowserSession(session_file=f.name)
                session.cookies = [{"name": "test", "value": "value"}]
                session.local_storage = {"key1": "val1"}
                session.logged_in = True
                session.last_refresh = datetime.now()
                
                session.save()
                
                # Verify file was written
                with open(f.name) as rf:
                    data = json.load(rf)
                    assert data["cookies"] == [{"name": "test", "value": "value"}]
                    assert data["local_storage"] == {"key1": "val1"}
                    assert data["logged_in"] is True
                    assert data["last_refresh"] is not None
            finally:
                os.unlink(f.name)

    def test_load_file_not_exists(self):
        session = BrowserSession(session_file="/nonexistent/path.json")
        result = session.load()
        assert result is False

    def test_load_no_file_configured(self):
        session = BrowserSession()
        result = session.load()
        assert result is False

    def test_load_success(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                data = {
                    "cookies": [{"name": "session", "value": "abc123"}],
                    "local_storage": {"key": "value"},
                    "session_storage": {"skey": "svalue"},
                    "logged_in": True,
                    "last_refresh": "2030-08-01T10:00:00"
                }
                json.dump(data, f)
                f.flush()
                
                session = BrowserSession(session_file=f.name)
                result = session.load()
                
                assert result is True
                assert session.cookies == [{"name": "session", "value": "abc123"}]
                assert session.local_storage == {"key": "value"}
                assert session.session_storage == {"skey": "svalue"}
                assert session.logged_in is True
                assert session.last_refresh == datetime(2030, 8, 1, 10, 0, 0)
            finally:
                os.unlink(f.name)

    def test_load_invalid_json(self):
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            try:
                f.write("not valid json")
                f.flush()
                
                session = BrowserSession(session_file=f.name)
                result = session.load()
                
                assert result is False
            finally:
                os.unlink(f.name)

    def test_is_expired_no_refresh(self):
        session = BrowserSession()
        assert session.is_expired() is True

    def test_is_expired_fresh(self):
        session = BrowserSession()
        session.last_refresh = datetime.now()
        assert session.is_expired() is False

    def test_is_expired_old(self):
        session = BrowserSession()
        session.last_refresh = datetime.now() - timedelta(hours=25)
        assert session.is_expired() is True

    def test_is_expired_custom_max_age(self):
        session = BrowserSession()
        session.last_refresh = datetime.now() - timedelta(hours=2)
        
        # Default 24 hours: not expired
        assert session.is_expired(max_age_hours=24) is False
        # 1 hour max: expired
        assert session.is_expired(max_age_hours=1) is True

    def test_to_cookie_string_empty(self):
        session = BrowserSession()
        assert session.to_cookie_string() == ""

    def test_to_cookie_string(self):
        session = BrowserSession()
        session.cookies = [
            {"name": "session_id", "value": "abc123"},
            {"name": "csrf_token", "value": "xyz789"},
        ]
        
        cookie_str = session.to_cookie_string()
        
        assert "session_id=abc123" in cookie_str
        assert "csrf_token=xyz789" in cookie_str
        assert "; " in cookie_str

    def test_to_netscape_format_empty(self):
        session = BrowserSession()
        result = session.to_netscape_format()
        assert "# Netscape HTTP Cookie File" in result

    def test_to_netscape_format(self):
        session = BrowserSession()
        session.cookies = [
            {
                "name": "session_id",
                "value": "abc123",
                "domain": "recreation.gov",
                "path": "/",
                "secure": True,
                "expires": 1893456000,
            },
        ]
        
        result = session.to_netscape_format()
        
        assert "# Netscape HTTP Cookie File" in result
        assert ".recreation.gov" in result
        assert "session_id" in result
        assert "abc123" in result
        assert "TRUE" in result  # secure flag

    def test_to_netscape_format_adds_dot_prefix(self):
        session = BrowserSession()
        session.cookies = [
            {
                "name": "test",
                "value": "value",
                "domain": "example.com",  # No leading dot
                "path": "/",
            },
        ]
        
        result = session.to_netscape_format()
        assert ".example.com" in result

    def test_to_netscape_format_preserves_dot_prefix(self):
        session = BrowserSession()
        session.cookies = [
            {
                "name": "test",
                "value": "value",
                "domain": ".example.com",  # Already has dot
                "path": "/",
            },
        ]
        
        result = session.to_netscape_format()
        # Should still have single dot
        assert ".example.com" in result
        assert "..example.com" not in result

    def test_export_for_requests_empty(self):
        session = BrowserSession()
        assert session.export_for_requests() == {}

    def test_export_for_requests(self):
        session = BrowserSession()
        session.cookies = [
            {"name": "session_id", "value": "abc123"},
            {"name": "csrf_token", "value": "xyz789"},
        ]
        
        result = session.export_for_requests()
        
        assert result == {
            "session_id": "abc123",
            "csrf_token": "xyz789",
        }

    @pytest.mark.asyncio
    async def test_capture_from_page(self):
        session = BrowserSession()
        
        # Mock page and context
        mock_page = AsyncMock()
        mock_page.evaluate = AsyncMock(side_effect=[
            {"ls_key": "ls_value"},  # localStorage
            {"ss_key": "ss_value"},  # sessionStorage
        ])
        
        mock_context = AsyncMock()
        mock_context.cookies = AsyncMock(return_value=[
            {"name": "session", "value": "abc123"}
        ])
        
        await session.capture_from_page(mock_page, mock_context)
        
        assert session.cookies == [{"name": "session", "value": "abc123"}]
        assert session.local_storage == {"ls_key": "ls_value"}
        assert session.session_storage == {"ss_key": "ss_value"}
        assert session.logged_in is True
        assert session.last_refresh is not None

    @pytest.mark.asyncio
    async def test_restore_to_context_no_cookies(self):
        session = BrowserSession()
        mock_context = AsyncMock()
        
        result = await session.restore_to_context(mock_context)
        
        assert result is False
        mock_context.add_cookies.assert_not_called()

    @pytest.mark.asyncio
    async def test_restore_to_context_with_cookies(self):
        session = BrowserSession()
        session.cookies = [{"name": "session", "value": "abc123"}]
        
        mock_context = AsyncMock()
        
        result = await session.restore_to_context(mock_context)
        
        assert result is True
        mock_context.add_cookies.assert_called_once_with(session.cookies)

    @pytest.mark.asyncio
    async def test_restore_to_context_with_storage(self):
        session = BrowserSession()
        session.cookies = [{"name": "session", "value": "abc123"}]
        session.local_storage = {"ls_key": "ls_value"}
        session.session_storage = {"ss_key": "ss_value"}
        
        mock_page = AsyncMock()
        mock_context = AsyncMock()
        
        result = await session.restore_to_context(mock_context, mock_page)
        
        assert result is True
        # Check page.evaluate was called for localStorage and sessionStorage
        assert mock_page.evaluate.call_count == 2


class TestSessionHandoff:
    @pytest.mark.asyncio
    async def test_generate_handoff_url(self):
        mock_page = MagicMock()
        mock_page.url = "https://www.recreation.gov/cart"
        
        url = await SessionHandoff.generate_handoff_url(mock_page)
        
        assert url == "https://www.recreation.gov/cart"

    @pytest.mark.asyncio
    async def test_generate_cookie_export(self):
        session = BrowserSession()
        session.cookies = [{"name": "session", "value": "abc123"}]
        
        export = await SessionHandoff.generate_cookie_export(session)
        
        assert "cookies" in export
        assert "instructions" in export
        assert "curl_command" in export
        assert "EditThisCookie" in export["instructions"]

    def test_generate_handoff_instructions_url(self):
        data = {"url": "https://www.recreation.gov/cart"}
        instructions = SessionHandoff.generate_handoff_instructions("url", data)
        
        assert "RESERVATION SECURED" in instructions
        assert "https://www.recreation.gov/cart" in instructions
        assert "15 MINUTES" in instructions

    def test_generate_handoff_instructions_cookies(self):
        data = {"file": "cookies.json"}
        instructions = SessionHandoff.generate_handoff_instructions("cookies", data)
        
        assert "RESERVATION SECURED" in instructions
        assert "EditThisCookie" in instructions
        assert "cookies.json" in instructions

    def test_generate_handoff_instructions_remote(self):
        data = {"url": "http://localhost:9222"}
        instructions = SessionHandoff.generate_handoff_instructions("remote", data)
        
        assert "RESERVATION SECURED" in instructions
        assert "http://localhost:9222" in instructions

    def test_generate_handoff_instructions_unknown_method(self):
        data = {}
        instructions = SessionHandoff.generate_handoff_instructions("unknown", data)
        
        assert "Reservation secured" in instructions

    @pytest.mark.asyncio
    async def test_start_remote_debugging(self):
        mock_context = AsyncMock()
        
        url = await SessionHandoff.start_remote_debugging(mock_context, port=9222)
        
        assert url == "http://localhost:9222"
