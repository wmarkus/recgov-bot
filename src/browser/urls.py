"""
Browser URL helpers for Recreation.gov.
"""

BASE_URL = "https://www.recreation.gov"


class WebPages:
    """URLs for browser-based automation"""

    @staticmethod
    def home() -> str:
        return BASE_URL

    @staticmethod
    def login() -> str:
        return f"{BASE_URL}/log-in"

    @staticmethod
    def campground(campground_id: str) -> str:
        return f"{BASE_URL}/camping/campgrounds/{campground_id}"

    @staticmethod
    def campsite(campsite_id: str) -> str:
        return f"{BASE_URL}/camping/campsites/{campsite_id}"

    @staticmethod
    def availability(campground_id: str) -> str:
        return f"{BASE_URL}/camping/campgrounds/{campground_id}/availability"

    @staticmethod
    def cart() -> str:
        return f"{BASE_URL}/cart"

    @staticmethod
    def checkout() -> str:
        return f"{BASE_URL}/checkout"

