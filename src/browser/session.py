"""
Browser session management for Recreation.gov bot

Handles session persistence, cookie management, and handoff to user.
"""
import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
from playwright.async_api import Page, BrowserContext, Cookie

from ..common.models import SessionState

logger = logging.getLogger(__name__)


class BrowserSession:
    """
    Manages browser session state for persistence and handoff.
    """
    
    def __init__(self, session_file: Optional[str] = None):
        self.session_file = Path(session_file) if session_file else None
        self.cookies: List[Cookie] = []
        self.local_storage: Dict[str, str] = {}
        self.session_storage: Dict[str, str] = {}
        self.logged_in = False
        self.last_refresh: Optional[datetime] = None
    
    async def capture_from_page(self, page: Page, context: BrowserContext):
        """
        Capture session state from browser.
        
        Call this after successful login to save the session.
        """
        # Capture cookies from context
        self.cookies = await context.cookies()
        
        # Capture local storage
        self.local_storage = await page.evaluate("""
            () => {
                const items = {};
                for (let i = 0; i < localStorage.length; i++) {
                    const key = localStorage.key(i);
                    items[key] = localStorage.getItem(key);
                }
                return items;
            }
        """)
        
        # Capture session storage
        self.session_storage = await page.evaluate("""
            () => {
                const items = {};
                for (let i = 0; i < sessionStorage.length; i++) {
                    const key = sessionStorage.key(i);
                    items[key] = sessionStorage.getItem(key);
                }
                return items;
            }
        """)
        
        self.logged_in = True
        self.last_refresh = datetime.now()
        
        logger.info(f"Captured session: {len(self.cookies)} cookies, "
                   f"{len(self.local_storage)} localStorage items")
        
        self.save()
    
    async def restore_to_context(self, context: BrowserContext, page: Optional[Page] = None):
        """
        Restore session state to browser context.
        
        Call this before navigating to restore a saved session.
        """
        if not self.cookies:
            logger.warning("No session to restore")
            return False
        
        # Restore cookies (can be done before navigation)
        await context.add_cookies(self.cookies)
        
        # Restore storage - need to be on the actual domain first
        if page and (self.local_storage or self.session_storage):
            try:
                # Navigate to the site first to enable localStorage access
                current_url = page.url
                if not current_url or 'recreation.gov' not in current_url:
                    await page.goto("https://www.recreation.gov", wait_until="domcontentloaded")
                
                if self.local_storage:
                    await page.evaluate("""
                        (items) => {
                            for (const [key, value] of Object.entries(items)) {
                                localStorage.setItem(key, value);
                            }
                        }
                    """, self.local_storage)
                
                if self.session_storage:
                    await page.evaluate("""
                        (items) => {
                            for (const [key, value] of Object.entries(items)) {
                                sessionStorage.setItem(key, value);
                            }
                        }
                    """, self.session_storage)
            except Exception as e:
                logger.warning(f"Could not restore storage: {e}")
        
        logger.info("Session restored to browser")
        return True
    
    def save(self):
        """Save session to file"""
        if not self.session_file:
            return
        
        try:
            self.session_file.parent.mkdir(parents=True, exist_ok=True)
            
            data = {
                "cookies": self.cookies,
                "local_storage": self.local_storage,
                "session_storage": self.session_storage,
                "logged_in": self.logged_in,
                "last_refresh": self.last_refresh.isoformat() if self.last_refresh else None
            }
            
            with open(self.session_file, 'w') as f:
                json.dump(data, f, indent=2, default=str)
            
            logger.debug(f"Session saved to {self.session_file}")
            
        except Exception as e:
            logger.error(f"Failed to save session: {e}")
    
    def load(self) -> bool:
        """Load session from file"""
        if not self.session_file or not self.session_file.exists():
            return False
        
        try:
            with open(self.session_file) as f:
                data = json.load(f)
            
            self.cookies = data.get("cookies", [])
            self.local_storage = data.get("local_storage", {})
            self.session_storage = data.get("session_storage", {})
            self.logged_in = data.get("logged_in", False)
            
            if data.get("last_refresh"):
                self.last_refresh = datetime.fromisoformat(data["last_refresh"])
            
            logger.info(f"Session loaded from {self.session_file}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to load session: {e}")
            return False
    
    def is_expired(self, max_age_hours: int = 24) -> bool:
        """Check if session is too old"""
        if not self.last_refresh:
            return True
        
        age = datetime.now() - self.last_refresh
        return age.total_seconds() > max_age_hours * 3600
    
    def to_cookie_string(self) -> str:
        """
        Export cookies as a string for manual browser import.
        
        Format compatible with browser extension import.
        """
        return "; ".join(
            f"{c['name']}={c['value']}"
            for c in self.cookies
        )
    
    def to_netscape_format(self) -> str:
        """
        Export cookies in Netscape format (compatible with curl, wget).
        """
        lines = ["# Netscape HTTP Cookie File"]
        
        for cookie in self.cookies:
            domain = cookie.get("domain", "")
            if not domain.startswith("."):
                domain = "." + domain
            
            line = "\t".join([
                domain,
                "TRUE",  # include subdomains
                cookie.get("path", "/"),
                "TRUE" if cookie.get("secure") else "FALSE",
                str(int(cookie.get("expires", 0))),
                cookie.get("name", ""),
                cookie.get("value", "")
            ])
            lines.append(line)
        
        return "\n".join(lines)
    
    def export_for_requests(self) -> Dict[str, str]:
        """
        Export cookies as dict for use with requests library.
        """
        return {c["name"]: c["value"] for c in self.cookies}


class SessionHandoff:
    """
    Handles transferring an authenticated session to the user.
    
    Multiple handoff methods supported:
    1. URL: Simply provide checkout URL (user must be logged in separately)
    2. Cookies: Export cookies for user to import via browser extension
    3. Remote: Keep browser running for remote access
    """
    
    @staticmethod
    async def generate_handoff_url(page: Page) -> str:
        """Get the current page URL for handoff"""
        return page.url
    
    @staticmethod
    async def generate_cookie_export(session: BrowserSession) -> Dict[str, Any]:
        """
        Generate cookie export data for user import.
        
        Returns data compatible with "EditThisCookie" browser extension.
        """
        return {
            "cookies": session.cookies,
            "instructions": (
                "To use these cookies:\n"
                "1. Install 'EditThisCookie' browser extension\n"
                "2. Go to recreation.gov\n"
                "3. Click the extension icon\n"
                "4. Click 'Import' and paste the cookies JSON\n"
                "5. Refresh the page\n"
                "6. Navigate to your cart to complete checkout"
            ),
            "curl_command": f'curl -b "{session.to_cookie_string()}" https://www.recreation.gov/cart'
        }
    
    @staticmethod
    async def start_remote_debugging(context: BrowserContext, port: int = 9222) -> str:
        """
        Start remote debugging for direct browser control handoff.
        
        Note: This requires the browser to be started with remote debugging enabled.
        Returns connection URL.
        """
        # This is a placeholder - actual implementation depends on how
        # Playwright is configured. For full remote debugging, you'd
        # typically start Chrome with --remote-debugging-port flag.
        return f"http://localhost:{port}"
    
    @staticmethod
    def generate_handoff_instructions(method: str, data: Dict[str, Any]) -> str:
        """Generate human-readable handoff instructions"""
        if method == "url":
            url = data.get('url', 'https://www.recreation.gov/cart')
            return f"""
╔══════════════════════════════════════════════════════════════╗
║                    🏕️ RESERVATION SECURED!                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Your campsite is in the cart!                              ║
║                                                              ║
║  1. Open this URL in your browser:                          ║
║     {url}
║                                                              ║
║  2. Log in with your Recreation.gov account                 ║
║                                                              ║
║  3. Complete checkout within 15 MINUTES                     ║
║                                                              ║
║  ⚠️  The reservation will be released if not completed!      ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
        elif method == "cookies":
            file_path = data.get('file', 'cookies.json')
            return f"""
╔══════════════════════════════════════════════════════════════╗
║                    🏕️ RESERVATION SECURED!                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Your campsite is in the cart!                              ║
║                                                              ║
║  To access your cart, import these cookies:                 ║
║                                                              ║
║  1. Install 'EditThisCookie' browser extension              ║
║  2. Go to recreation.gov                                    ║
║  3. Click extension → Import → Paste the JSON               ║
║  4. Refresh and go to Cart                                  ║
║                                                              ║
║  Cookie data saved to: {file_path}
║                                                              ║
║  ⚠️  Complete checkout within 15 MINUTES!                    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
        elif method == "remote":
            remote_url = data.get('url', 'Browser window should be visible')
            return f"""
╔══════════════════════════════════════════════════════════════╗
║                    🏕️ RESERVATION SECURED!                    ║
╠══════════════════════════════════════════════════════════════╣
║                                                              ║
║  Your campsite is in the cart!                              ║
║                                                              ║
║  The browser is still running. Access it at:                ║
║  {remote_url}
║                                                              ║
║  Complete checkout in the open browser window.              ║
║                                                              ║
║  ⚠️  Complete checkout within 15 MINUTES!                    ║
║                                                              ║
╚══════════════════════════════════════════════════════════════╝
"""
        return "Reservation secured! Check the browser window."
