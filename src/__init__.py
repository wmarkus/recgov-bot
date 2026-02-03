"""
Recreation.gov Campsite Sniper Bot

Two approaches for automated campsite reservations:

1. Browser Automation (src.browser)
   - Uses Playwright to control a real browser
   - More reliable, handles JavaScript
   - Supports CAPTCHA pause for human intervention
   
2. Direct API (src.api)
   - Uses reverse-engineered REST endpoints
   - Faster but more fragile
   - May break if Recreation.gov changes their API
"""
from .common.config import Config, load_config

__version__ = "1.0.0"

__all__ = [
    "Config",
    "load_config",
]
