"""
Tests for data models (src/common/models.py)
"""
import pytest
from datetime import datetime, date, timedelta

from src.common.models import (
    ReservationStatus,
    CampsiteAvailability,
    Campground,
    Campsite,
    AvailabilitySlot,
    CampsiteAvailabilityResult,
    ReservationTarget,
    CartItem,
    ReservationAttempt,
    SessionState,
    NotificationPayload,
)


class TestReservationStatus:
    def test_status_values(self):
        assert ReservationStatus.PENDING.value == "pending"
        assert ReservationStatus.SCHEDULED.value == "scheduled"
        assert ReservationStatus.ATTEMPTING.value == "attempting"
        assert ReservationStatus.IN_CART.value == "in_cart"
        assert ReservationStatus.SUCCESS.value == "success"
        assert ReservationStatus.FAILED.value == "failed"
        assert ReservationStatus.TIMEOUT.value == "timeout"


class TestCampsiteAvailability:
    def test_availability_values(self):
        assert CampsiteAvailability.AVAILABLE.value == "Available"
        assert CampsiteAvailability.RESERVED.value == "Reserved"
        assert CampsiteAvailability.NOT_AVAILABLE.value == "Not Available"
        assert CampsiteAvailability.WALK_UP.value == "Walk Up"
        assert CampsiteAvailability.NOT_RESERVABLE.value == "Not Reservable"
        assert CampsiteAvailability.OPEN.value == "Open"


class TestCampground:
    def test_create_campground(self):
        campground = Campground(id="12345", name="Test Campground")
        assert campground.id == "12345"
        assert campground.name == "Test Campground"
        assert campground.facility_id is None

    def test_campground_url_property(self):
        campground = Campground(id="232447", name="North Pines")
        assert campground.url == "https://www.recreation.gov/camping/campgrounds/232447"

    def test_campground_with_optional_fields(self):
        campground = Campground(
            id="12345",
            name="Test Campground",
            facility_id="FAC001",
            parent_name="Yosemite National Park",
            latitude=37.7381,
            longitude=-119.5729,
        )
        assert campground.parent_name == "Yosemite National Park"
        assert campground.latitude == 37.7381


class TestCampsite:
    def test_create_campsite(self):
        campsite = Campsite(
            id="1001",
            campground_id="12345",
            name="A001",
        )
        assert campsite.id == "1001"
        assert campsite.campground_id == "12345"
        assert campsite.name == "A001"

    def test_campsite_url_property(self):
        campsite = Campsite(
            id="99999",
            campground_id="12345",
            name="Site 42",
        )
        assert campsite.url == "https://www.recreation.gov/camping/campsites/99999"

    def test_campsite_with_optional_fields(self):
        campsite = Campsite(
            id="1001",
            campground_id="12345",
            name="A001",
            site_type="STANDARD",
            max_people=6,
            min_people=1,
            loop="Loop A",
        )
        assert campsite.site_type == "STANDARD"
        assert campsite.max_people == 6
        assert campsite.loop == "Loop A"


class TestAvailabilitySlot:
    def test_create_availability_slot(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.AVAILABLE,
        )
        assert slot.date == date(2030, 8, 1)
        assert slot.status == CampsiteAvailability.AVAILABLE

    def test_is_available_when_available(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.AVAILABLE,
        )
        assert slot.is_available is True

    def test_is_available_when_open(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.OPEN,
        )
        assert slot.is_available is True

    def test_is_available_when_reserved(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.RESERVED,
        )
        assert slot.is_available is False

    def test_is_available_when_not_available(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.NOT_AVAILABLE,
        )
        assert slot.is_available is False

    def test_is_available_when_walk_up(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.WALK_UP,
        )
        assert slot.is_available is False

    def test_is_available_when_not_reservable(self):
        slot = AvailabilitySlot(
            date=date(2030, 8, 1),
            status=CampsiteAvailability.NOT_RESERVABLE,
        )
        assert slot.is_available is False


class TestCampsiteAvailabilityResult:
    def test_create_availability_result(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[],
        )
        assert result.campsite == campsite
        assert result.availabilities == []

    def test_is_available_for_dates_single_day_available(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[
                AvailabilitySlot(date=date(2030, 8, 1), status=CampsiteAvailability.AVAILABLE),
            ],
        )
        assert result.is_available_for_dates(date(2030, 8, 1), date(2030, 8, 2)) is True

    def test_is_available_for_dates_multi_day_all_available(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[
                AvailabilitySlot(date=date(2030, 8, 1), status=CampsiteAvailability.AVAILABLE),
                AvailabilitySlot(date=date(2030, 8, 2), status=CampsiteAvailability.AVAILABLE),
                AvailabilitySlot(date=date(2030, 8, 3), status=CampsiteAvailability.AVAILABLE),
            ],
        )
        assert result.is_available_for_dates(date(2030, 8, 1), date(2030, 8, 4)) is True

    def test_is_available_for_dates_multi_day_one_reserved(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[
                AvailabilitySlot(date=date(2030, 8, 1), status=CampsiteAvailability.AVAILABLE),
                AvailabilitySlot(date=date(2030, 8, 2), status=CampsiteAvailability.RESERVED),
                AvailabilitySlot(date=date(2030, 8, 3), status=CampsiteAvailability.AVAILABLE),
            ],
        )
        assert result.is_available_for_dates(date(2030, 8, 1), date(2030, 8, 4)) is False

    def test_is_available_for_dates_missing_date_in_range(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[
                AvailabilitySlot(date=date(2030, 8, 1), status=CampsiteAvailability.AVAILABLE),
                # Missing 8/2
                AvailabilitySlot(date=date(2030, 8, 3), status=CampsiteAvailability.AVAILABLE),
            ],
        )
        assert result.is_available_for_dates(date(2030, 8, 1), date(2030, 8, 4)) is False

    def test_is_available_for_dates_empty_availabilities(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[],
        )
        assert result.is_available_for_dates(date(2030, 8, 1), date(2030, 8, 2)) is False

    def test_is_available_for_dates_with_open_status(self):
        """OPEN status should also be considered available"""
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        result = CampsiteAvailabilityResult(
            campsite=campsite,
            availabilities=[
                AvailabilitySlot(date=date(2030, 8, 1), status=CampsiteAvailability.OPEN),
                AvailabilitySlot(date=date(2030, 8, 2), status=CampsiteAvailability.AVAILABLE),
            ],
        )
        assert result.is_available_for_dates(date(2030, 8, 1), date(2030, 8, 3)) is True


class TestReservationTarget:
    def test_create_target(self):
        target = ReservationTarget(
            campground_id="12345",
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 5),
        )
        assert target.campground_id == "12345"
        assert target.campsite_ids == []
        assert target.num_people == 2

    def test_num_nights_property(self):
        target = ReservationTarget(
            campground_id="12345",
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 5),
        )
        assert target.num_nights == 4

    def test_num_nights_single_night(self):
        target = ReservationTarget(
            campground_id="12345",
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 2),
        )
        assert target.num_nights == 1

    def test_to_api_params(self):
        target = ReservationTarget(
            campground_id="12345",
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 5),
            num_people=4,
        )
        params = target.to_api_params()
        assert params == {
            "campground_id": "12345",
            "start_date": "2030-08-01",
            "end_date": "2030-08-05",
            "occupants": 4,
        }

    def test_to_api_params_with_defaults(self):
        target = ReservationTarget(
            campground_id="12345",
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 3),
        )
        params = target.to_api_params()
        assert params["occupants"] == 2


class TestCartItem:
    def test_create_cart_item(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        expires_at = datetime.now() + timedelta(minutes=15)
        cart_item = CartItem(
            reservation_id="RES123",
            campsite=campsite,
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 5),
            subtotal=50.0,
            fees=5.0,
            total=55.0,
            expires_at=expires_at,
        )
        assert cart_item.reservation_id == "RES123"
        assert cart_item.total == 55.0

    def test_time_remaining_positive(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        expires_at = datetime.now() + timedelta(minutes=10)
        cart_item = CartItem(
            reservation_id="RES123",
            campsite=campsite,
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 3),
            subtotal=50.0,
            fees=5.0,
            total=55.0,
            expires_at=expires_at,
        )
        remaining = cart_item.time_remaining
        # Should be around 600 seconds (10 minutes), allow some tolerance
        assert 590 <= remaining <= 610

    def test_time_remaining_expired(self):
        campsite = Campsite(id="1001", campground_id="12345", name="A001")
        expires_at = datetime.now() - timedelta(minutes=5)
        cart_item = CartItem(
            reservation_id="RES123",
            campsite=campsite,
            arrival_date=date(2030, 8, 1),
            departure_date=date(2030, 8, 3),
            subtotal=50.0,
            fees=5.0,
            total=55.0,
            expires_at=expires_at,
        )
        assert cart_item.time_remaining == 0


class TestReservationAttempt:
    def test_create_attempt(self, target):
        attempt = ReservationAttempt(target=target)
        assert attempt.status == ReservationStatus.PENDING
        assert attempt.started_at is None
        assert attempt.completed_at is None
        assert attempt.attempts_made == 0

    def test_mark_success(self, target):
        attempt = ReservationAttempt(target=target)
        campsite = Campsite(id="1001", campground_id=target.campground_id, name="A001")
        cart_item = CartItem(
            reservation_id="RES123",
            campsite=campsite,
            arrival_date=target.arrival_date,
            departure_date=target.departure_date,
            subtotal=50.0,
            fees=5.0,
            total=55.0,
            expires_at=datetime.now() + timedelta(minutes=15),
        )

        attempt.mark_success(campsite, cart_item)

        assert attempt.status == ReservationStatus.IN_CART
        assert attempt.completed_at is not None
        assert attempt.campsite_secured == campsite
        assert attempt.cart_item == cart_item
        assert attempt.checkout_url == "https://www.recreation.gov/cart"

    def test_mark_failed(self, target):
        attempt = ReservationAttempt(target=target)
        attempt.mark_failed("No sites available")

        assert attempt.status == ReservationStatus.FAILED
        assert attempt.completed_at is not None
        assert attempt.error_message == "No sites available"

    def test_attempt_id_auto_generated(self, target):
        attempt = ReservationAttempt(target=target)
        assert attempt.id is not None
        assert len(attempt.id) > 0


class TestSessionState:
    def test_create_session_state(self):
        state = SessionState()
        assert state.cookies == {}
        assert state.local_storage == {}
        assert state.csrf_token is None
        assert state.logged_in is False

    def test_to_cookie_header_empty(self):
        state = SessionState()
        assert state.to_cookie_header() == ""

    def test_to_cookie_header_with_cookies(self):
        state = SessionState(
            cookies={
                "session_id": "abc123",
                "csrf_token": "xyz789",
            }
        )
        header = state.to_cookie_header()
        # Order doesn't matter, check both cookies are present
        assert "session_id=abc123" in header
        assert "csrf_token=xyz789" in header
        assert "; " in header or header.count("=") == 2

    def test_is_expired_no_refresh(self):
        state = SessionState()
        assert state.is_expired() is True

    def test_is_expired_fresh(self):
        state = SessionState(last_refresh=datetime.now())
        assert state.is_expired() is False

    def test_is_expired_old(self):
        state = SessionState(
            last_refresh=datetime.now() - timedelta(hours=2)
        )
        assert state.is_expired() is True

    def test_is_expired_custom_max_age(self):
        # 30 minutes ago
        state = SessionState(
            last_refresh=datetime.now() - timedelta(minutes=30)
        )
        # Default 1 hour: not expired
        assert state.is_expired(max_age_seconds=3600) is False
        # 20 minute max: expired
        assert state.is_expired(max_age_seconds=1200) is True


class TestNotificationPayload:
    def test_create_payload(self):
        payload = NotificationPayload(
            title="Test Title",
            message="Test message body",
        )
        assert payload.title == "Test Title"
        assert payload.message == "Test message body"
        assert payload.url is None
        assert payload.urgency == "normal"

    def test_payload_with_url(self):
        payload = NotificationPayload(
            title="Success!",
            message="Reservation secured",
            url="https://www.recreation.gov/cart",
            urgency="high",
        )
        assert payload.url == "https://www.recreation.gov/cart"
        assert payload.urgency == "high"

    def test_payload_with_attempt(self, target):
        attempt = ReservationAttempt(target=target)
        payload = NotificationPayload(
            title="Attempt Started",
            message="Starting reservation",
            attempt=attempt,
        )
        assert payload.attempt == attempt
