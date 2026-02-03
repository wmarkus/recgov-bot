"""
Recreation.gov API Endpoints (Reverse-Engineered)

⚠️ WARNING: These endpoints are undocumented and may change without notice.
Last verified: January 2025

These were discovered by inspecting network traffic in browser DevTools.
"""
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlencode


BASE_URL = "https://www.recreation.gov"
API_BASE = f"{BASE_URL}/api"


@dataclass
class Endpoints:
    """
    Collection of Recreation.gov API endpoints.
    
    To discover endpoints yourself:
    1. Open browser DevTools → Network tab
    2. Navigate through recreation.gov booking flow
    3. Filter by XHR/Fetch requests
    4. Inspect request/response details
    """
    
    # ============================================================
    # PUBLIC ENDPOINTS (No auth required)
    # ============================================================
    
    @staticmethod
    def search(query: str, entity_type: str = "campground", limit: int = 20) -> str:
        """
        Search for campgrounds, campsites, permits, etc.
        
        GET /api/search?q={query}&entity_type={type}&size={limit}
        """
        params = {
            "q": query,
            "entity_type": entity_type,
            "size": limit
        }
        return f"{API_BASE}/search?{urlencode(params)}"
    
    @staticmethod
    def campground_details(campground_id: str) -> str:
        """
        Get campground details.
        
        GET /api/camps/campgrounds/{id}
        """
        return f"{API_BASE}/camps/campgrounds/{campground_id}"
    
    @staticmethod
    def campsite_details(campsite_id: str) -> str:
        """
        Get individual campsite details.
        
        GET /api/camps/campsites/{id}
        """
        return f"{API_BASE}/camps/campsites/{campsite_id}"
    
    @staticmethod
    def campground_availability(campground_id: str, start_date: str) -> str:
        """
        Get availability for all campsites in a campground for a month.
        
        GET /api/camps/availability/campground/{id}/month?start_date={ISO_DATE}
        
        The start_date should be first of month, e.g., "2025-08-01T00:00:00.000Z"
        Response includes availability status for each campsite for each day.
        """
        return f"{API_BASE}/camps/availability/campground/{campground_id}/month?start_date={start_date}"
    
    @staticmethod
    def campsite_availability(campsite_id: str, start_date: str) -> str:
        """
        Get availability for a specific campsite.
        
        GET /api/camps/availability/campsite/{id}/month?start_date={ISO_DATE}
        """
        return f"{API_BASE}/camps/availability/campsite/{campsite_id}/month?start_date={start_date}"
    
    # ============================================================
    # AUTHENTICATION ENDPOINTS
    # ============================================================
    
    @staticmethod
    def login() -> str:
        """
        Login endpoint.
        
        POST /api/accounts/login
        Body: {"email": "...", "password": "..."}
        
        Returns session cookies and auth token.
        """
        return f"{API_BASE}/accounts/login"
    
    @staticmethod
    def logout() -> str:
        """
        Logout endpoint.
        
        POST /api/accounts/logout
        """
        return f"{API_BASE}/accounts/logout"
    
    @staticmethod
    def account_info() -> str:
        """
        Get current account info (requires auth).
        
        GET /api/accounts/account
        """
        return f"{API_BASE}/accounts/account"
    
    # ============================================================
    # CART/RESERVATION ENDPOINTS (Auth required)
    # ============================================================
    
    @staticmethod
    def cart() -> str:
        """
        Get current cart contents.
        
        GET /api/ticket/cart
        """
        return f"{API_BASE}/ticket/cart"
    
    @staticmethod
    def add_to_cart() -> str:
        """
        Add item to cart.
        
        POST /api/ticket/reservation
        
        Body varies by reservation type. For camping:
        {
            "campsiteId": "12345",
            "facilityId": "232447",
            "unitTypeId": 1,  # STANDARD
            "arrivalDate": "2025-08-15",
            "departureDate": "2025-08-17",
            "numberOfVehicles": 1,
            "isOvernightStay": true,
            ...
        }
        """
        return f"{API_BASE}/ticket/reservation"
    
    @staticmethod
    def remove_from_cart(item_id: str) -> str:
        """
        Remove item from cart.
        
        DELETE /api/ticket/reservation/{id}
        """
        return f"{API_BASE}/ticket/reservation/{item_id}"
    
    @staticmethod
    def checkout() -> str:
        """
        Begin checkout process.
        
        POST /api/ticket/checkout
        """
        return f"{API_BASE}/ticket/checkout"
    
    # ============================================================
    # UTILITY ENDPOINTS
    # ============================================================
    
    @staticmethod
    def facility_rules(facility_id: str) -> str:
        """
        Get facility booking rules (window, limits, etc.).
        
        GET /api/camps/campgrounds/{id}/rules
        """
        return f"{API_BASE}/camps/campgrounds/{facility_id}/rules"
    
    @staticmethod
    def csrf_token() -> str:
        """
        Get CSRF token (may be required for some operations).
        
        GET /api/csrf
        """
        return f"{API_BASE}/csrf"


# Common request headers to mimic browser
DEFAULT_HEADERS = {
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Content-Type": "application/json",
    "Origin": "https://www.recreation.gov",
    "Referer": "https://www.recreation.gov/",
    "Sec-Fetch-Dest": "empty",
    "Sec-Fetch-Mode": "cors",
    "Sec-Fetch-Site": "same-origin",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}


# Known response structures

AVAILABILITY_STATUS_MAP = {
    "Available": True,
    "Reserved": False,
    "Not Available": False,
    "Walk Up": False,  # First-come, first-served
    "Not Reservable": False,
    "Open": True,
}


@dataclass
class AvailabilityResponse:
    """
    Structure of availability API response.
    
    Response format:
    {
        "campsites": {
            "12345": {  # campsite_id
                "availabilities": {
                    "2025-08-15T00:00:00Z": "Available",
                    "2025-08-16T00:00:00Z": "Reserved",
                    ...
                },
                "campsite_id": "12345",
                "campsite_type": "STANDARD",
                "loop": "A",
                "max_num_people": 6,
                "min_num_people": 1,
                "site": "A001",
                ...
            },
            ...
        }
    }
    """
    pass


@dataclass  
class CartAddRequest:
    """
    Request body for adding camping reservation to cart.
    
    This structure was reverse-engineered and may be incomplete.
    """
    campsite_id: str
    facility_id: str
    arrival_date: str  # YYYY-MM-DD
    departure_date: str  # YYYY-MM-DD
    number_of_vehicles: int = 1
    is_overnight_stay: bool = True
    
    def to_dict(self) -> dict:
        return {
            "campsiteId": self.campsite_id,
            "facilityId": self.facility_id,
            "arrivalDate": self.arrival_date,
            "departureDate": self.departure_date,
            "numberOfVehicles": self.number_of_vehicles,
            "isOvernightStay": self.is_overnight_stay,
            # Additional fields that may be required:
            "unitTypeId": 1,  # 1 = STANDARD
            "inventoryType": "CAMPING",
        }


# Webpage URLs (for browser automation)

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
