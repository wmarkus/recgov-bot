"""
Authentication handling for Recreation.gov API
"""
import json
import logging
from typing import Optional, Tuple
from pathlib import Path
import httpx

from .endpoints import Endpoints, DEFAULT_HEADERS
from ..common.models import SessionState

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails"""
    pass


class RecGovAuth:
    """
    Handles authentication with Recreation.gov.
    
    Recreation.gov uses cookie-based authentication with a JWT token.
    The login endpoint returns cookies that must be included in subsequent requests.
    """
    
    def __init__(self, session_file: Optional[str] = None):
        self.session_file = Path(session_file) if session_file else None
        self.session = SessionState()
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=30.0
        )
    
    async def login(self, email: str, password: str) -> SessionState:
        """
        Login to Recreation.gov and get session cookies.
        
        Returns:
            SessionState with cookies and auth info
        """
        logger.info(f"Attempting login for {email}")
        
        try:
            # First, get any initial cookies/CSRF token
            await self._init_session()
            
            # Perform login
            response = await self.client.post(
                Endpoints.login(),
                json={
                    "email": email,
                    "password": password
                }
            )
            
            if response.status_code == 200:
                # Extract cookies
                self.session.cookies = dict(response.cookies)
                
                # Check for auth token in response
                try:
                    data = response.json()
                    if "token" in data:
                        self.session.auth_token = data["token"]
                except:
                    pass
                
                self.session.logged_in = True
                self.session.last_refresh = __import__('datetime').datetime.now()
                
                logger.info("Login successful")
                
                # Verify login by checking account
                if await self._verify_login():
                    self._save_session()
                    return self.session
                else:
                    raise AuthenticationError("Login appeared successful but verification failed")
            
            elif response.status_code == 401:
                raise AuthenticationError("Invalid email or password")
            
            elif response.status_code == 429:
                raise AuthenticationError("Rate limited. Try again later.")
            
            else:
                raise AuthenticationError(
                    f"Login failed with status {response.status_code}: {response.text}"
                )
                
        except httpx.RequestError as e:
            raise AuthenticationError(f"Network error during login: {e}")
    
    async def _init_session(self):
        """Initialize session by visiting homepage to get cookies"""
        try:
            response = await self.client.get("https://www.recreation.gov")
            self.session.cookies.update(dict(response.cookies))
            
            # Try to get CSRF token
            csrf_response = await self.client.get(Endpoints.csrf_token())
            if csrf_response.status_code == 200:
                try:
                    data = csrf_response.json()
                    self.session.csrf_token = data.get("csrf")
                except:
                    pass
        except Exception as e:
            logger.warning(f"Failed to initialize session: {e}")
    
    async def _verify_login(self) -> bool:
        """Verify that we're actually logged in"""
        try:
            response = await self.client.get(
                Endpoints.account_info(),
                cookies=self.session.cookies
            )
            return response.status_code == 200
        except:
            return False
    
    async def refresh_session(self) -> bool:
        """
        Refresh the session to keep it alive.
        
        Call this periodically to prevent session expiry.
        """
        try:
            response = await self.client.get(
                "https://www.recreation.gov",
                cookies=self.session.cookies
            )
            self.session.cookies.update(dict(response.cookies))
            self.session.last_refresh = __import__('datetime').datetime.now()
            self._save_session()
            return True
        except Exception as e:
            logger.error(f"Failed to refresh session: {e}")
            return False
    
    async def logout(self):
        """Logout and clear session"""
        try:
            await self.client.post(
                Endpoints.logout(),
                cookies=self.session.cookies
            )
        except:
            pass
        
        self.session = SessionState()
        if self.session_file and self.session_file.exists():
            self.session_file.unlink()
    
    def _save_session(self):
        """Save session to file for persistence"""
        if not self.session_file:
            return
        
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.session_file, 'w') as f:
                json.dump(self.session.model_dump(), f)
            logger.debug(f"Session saved to {self.session_file}")
        except Exception as e:
            logger.warning(f"Failed to save session: {e}")
    
    def load_session(self) -> Optional[SessionState]:
        """Load session from file if available"""
        if not self.session_file or not self.session_file.exists():
            return None
        
        try:
            with open(self.session_file) as f:
                data = json.load(f)
            self.session = SessionState(**data)
            logger.info(f"Session loaded from {self.session_file}")
            return self.session
        except Exception as e:
            logger.warning(f"Failed to load session: {e}")
            return None
    
    def get_auth_headers(self) -> dict:
        """Get headers with authentication for API requests"""
        headers = DEFAULT_HEADERS.copy()
        
        if self.session.auth_token:
            headers["Authorization"] = f"Bearer {self.session.auth_token}"
        
        if self.session.csrf_token:
            headers["X-CSRF-Token"] = self.session.csrf_token
        
        return headers
    
    def get_cookies(self) -> dict:
        """Get session cookies"""
        return self.session.cookies.copy()
    
    @property
    def is_logged_in(self) -> bool:
        """Check if currently logged in"""
        return self.session.logged_in and not self.session.is_expired()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.client.aclose()
