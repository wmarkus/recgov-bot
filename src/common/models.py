"""
Data models for Recreation.gov bot
"""
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, Field
from enum import Enum


class ReservationStatus(str, Enum):
    PENDING = "pending"
    SCHEDULED = "scheduled"
    ATTEMPTING = "attempting"
    IN_CART = "in_cart"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"


class CampsiteAvailability(str, Enum):
    AVAILABLE = "Available"
    RESERVED = "Reserved"
    NOT_AVAILABLE = "Not Available"
    WALK_UP = "Walk Up"
    NOT_RESERVABLE = "Not Reservable"
    OPEN = "Open"


class Campground(BaseModel):
    """Recreation.gov campground"""
    id: str
    name: str
    facility_id: Optional[str] = None
    parent_name: Optional[str] = None  # e.g., "Yosemite National Park"
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    reservation_url: Optional[str] = None
    
    @property
    def url(self) -> str:
        return f"https://www.recreation.gov/camping/campgrounds/{self.id}"


class Campsite(BaseModel):
    """Individual campsite within a campground"""
    id: str
    campground_id: str
    name: str  # e.g., "A001" or "Site 42"
    site_type: Optional[str] = None  # STANDARD, GROUP, etc.
    max_people: Optional[int] = None
    min_people: Optional[int] = None
    loop: Optional[str] = None
    
    @property
    def url(self) -> str:
        return f"https://www.recreation.gov/camping/campsites/{self.id}"


class AvailabilitySlot(BaseModel):
    """Availability for a specific date"""
    date: date
    status: CampsiteAvailability
    
    @property
    def is_available(self) -> bool:
        return self.status in [
            CampsiteAvailability.AVAILABLE,
            CampsiteAvailability.OPEN
        ]


class CampsiteAvailabilityResult(BaseModel):
    """Full availability result for a campsite"""
    campsite: Campsite
    availabilities: List[AvailabilitySlot]
    
    def is_available_for_dates(self, start: date, end: date) -> bool:
        """Check if campsite is available for entire date range"""
        current = start
        while current < end:
            slot = next(
                (a for a in self.availabilities if a.date == current), 
                None
            )
            if not slot or not slot.is_available:
                return False
            current = date.fromordinal(current.toordinal() + 1)
        return True


class ReservationTarget(BaseModel):
    """Target reservation configuration"""
    campground_id: str
    campsite_ids: List[str] = Field(default_factory=list)
    arrival_date: date
    departure_date: date
    num_people: int = 2
    equipment: Optional[str] = None
    
    @property
    def num_nights(self) -> int:
        return (self.departure_date - self.arrival_date).days
    
    def to_api_params(self) -> dict:
        """Convert to API request parameters"""
        return {
            "campground_id": self.campground_id,
            "start_date": self.arrival_date.isoformat(),
            "end_date": self.departure_date.isoformat(),
            "occupants": self.num_people,
        }


class CartItem(BaseModel):
    """Item in Recreation.gov shopping cart"""
    reservation_id: str
    campsite: Campsite
    arrival_date: date
    departure_date: date
    subtotal: float
    fees: float
    total: float
    expires_at: datetime
    
    @property
    def time_remaining(self) -> int:
        """Seconds until cart item expires"""
        delta = self.expires_at - datetime.now()
        return max(0, int(delta.total_seconds()))


class ReservationAttempt(BaseModel):
    """Record of a reservation attempt"""
    id: str = Field(default_factory=lambda: datetime.now().isoformat())
    target: ReservationTarget
    status: ReservationStatus = ReservationStatus.PENDING
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    campsite_secured: Optional[Campsite] = None
    cart_item: Optional[CartItem] = None
    checkout_url: Optional[str] = None
    error_message: Optional[str] = None
    attempts_made: int = 0
    
    def mark_success(self, campsite: Campsite, cart_item: CartItem):
        """Mark attempt as successful"""
        self.status = ReservationStatus.IN_CART
        self.completed_at = datetime.now()
        self.campsite_secured = campsite
        self.cart_item = cart_item
        self.checkout_url = "https://www.recreation.gov/cart"
    
    def mark_failed(self, error: str):
        """Mark attempt as failed"""
        self.status = ReservationStatus.FAILED
        self.completed_at = datetime.now()
        self.error_message = error


class SessionState(BaseModel):
    """Browser/API session state"""
    cookies: dict = Field(default_factory=dict)
    local_storage: dict = Field(default_factory=dict)
    csrf_token: Optional[str] = None
    auth_token: Optional[str] = None
    logged_in: bool = False
    last_refresh: Optional[datetime] = None
    
    def to_cookie_header(self) -> str:
        """Convert cookies to header string"""
        return "; ".join(f"{k}={v}" for k, v in self.cookies.items())
    
    def is_expired(self, max_age_seconds: int = 3600) -> bool:
        """Check if session needs refresh"""
        if not self.last_refresh:
            return True
        age = (datetime.now() - self.last_refresh).total_seconds()
        return age > max_age_seconds


class NotificationPayload(BaseModel):
    """Notification content"""
    title: str
    message: str
    url: Optional[str] = None
    urgency: str = "normal"  # low, normal, high
    attempt: Optional[ReservationAttempt] = None
