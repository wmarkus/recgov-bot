"""
Tests for API endpoints (src/legacy/api/endpoints.py)
"""
import pytest

from src.legacy.api.endpoints import (
    Endpoints,
    WebPages,
    CartAddRequest,
    DEFAULT_HEADERS,
    AVAILABILITY_STATUS_MAP,
    BASE_URL,
    API_BASE,
)


class TestEndpointsPublic:
    def test_search_basic(self):
        url = Endpoints.search("yosemite")
        assert "api/search" in url
        assert "q=yosemite" in url
        assert "entity_type=campground" in url
        assert "size=20" in url

    def test_search_custom_params(self):
        url = Endpoints.search("grand canyon", entity_type="permit", limit=50)
        assert "q=grand+canyon" in url or "q=grand%20canyon" in url
        assert "entity_type=permit" in url
        assert "size=50" in url

    def test_campground_details(self):
        url = Endpoints.campground_details("232447")
        assert url == f"{API_BASE}/camps/campgrounds/232447"

    def test_campsite_details(self):
        url = Endpoints.campsite_details("12345")
        assert url == f"{API_BASE}/camps/campsites/12345"

    def test_campground_availability(self):
        url = Endpoints.campground_availability("232447", "2030-08-01T00:00:00.000Z")
        assert "api/camps/availability/campground/232447" in url
        assert "start_date=2030-08-01T00:00:00.000Z" in url

    def test_campsite_availability(self):
        url = Endpoints.campsite_availability("12345", "2030-08-01T00:00:00.000Z")
        assert "api/camps/availability/campsite/12345" in url
        assert "start_date=2030-08-01T00:00:00.000Z" in url


class TestEndpointsAuth:
    def test_login(self):
        url = Endpoints.login()
        assert url == f"{API_BASE}/accounts/login"

    def test_logout(self):
        url = Endpoints.logout()
        assert url == f"{API_BASE}/accounts/logout"

    def test_account_info(self):
        url = Endpoints.account_info()
        assert url == f"{API_BASE}/accounts/account"


class TestEndpointsCart:
    def test_cart(self):
        url = Endpoints.cart()
        assert url == f"{API_BASE}/ticket/cart"

    def test_add_to_cart(self):
        url = Endpoints.add_to_cart()
        assert url == f"{API_BASE}/ticket/reservation"

    def test_remove_from_cart(self):
        url = Endpoints.remove_from_cart("RES123")
        assert url == f"{API_BASE}/ticket/reservation/RES123"

    def test_checkout(self):
        url = Endpoints.checkout()
        assert url == f"{API_BASE}/ticket/checkout"


class TestEndpointsUtility:
    def test_facility_rules(self):
        url = Endpoints.facility_rules("232447")
        assert url == f"{API_BASE}/camps/campgrounds/232447/rules"

    def test_csrf_token(self):
        url = Endpoints.csrf_token()
        assert url == f"{API_BASE}/csrf"


class TestWebPages:
    def test_home(self):
        url = WebPages.home()
        assert url == BASE_URL

    def test_login(self):
        url = WebPages.login()
        assert url == f"{BASE_URL}/log-in"

    def test_campground(self):
        url = WebPages.campground("232447")
        assert url == f"{BASE_URL}/camping/campgrounds/232447"

    def test_campsite(self):
        url = WebPages.campsite("12345")
        assert url == f"{BASE_URL}/camping/campsites/12345"

    def test_availability(self):
        url = WebPages.availability("232447")
        assert url == f"{BASE_URL}/camping/campgrounds/232447/availability"

    def test_cart(self):
        url = WebPages.cart()
        assert url == f"{BASE_URL}/cart"

    def test_checkout(self):
        url = WebPages.checkout()
        assert url == f"{BASE_URL}/checkout"


class TestCartAddRequest:
    def test_create_request(self):
        request = CartAddRequest(
            campsite_id="12345",
            facility_id="232447",
            arrival_date="2030-08-15",
            departure_date="2030-08-17",
        )
        assert request.campsite_id == "12345"
        assert request.facility_id == "232447"
        assert request.number_of_vehicles == 1
        assert request.is_overnight_stay is True

    def test_create_request_custom(self):
        request = CartAddRequest(
            campsite_id="12345",
            facility_id="232447",
            arrival_date="2030-08-15",
            departure_date="2030-08-17",
            number_of_vehicles=2,
            is_overnight_stay=False,
        )
        assert request.number_of_vehicles == 2
        assert request.is_overnight_stay is False

    def test_to_dict(self):
        request = CartAddRequest(
            campsite_id="12345",
            facility_id="232447",
            arrival_date="2030-08-15",
            departure_date="2030-08-17",
        )
        data = request.to_dict()
        
        assert data["campsiteId"] == "12345"
        assert data["facilityId"] == "232447"
        assert data["arrivalDate"] == "2030-08-15"
        assert data["departureDate"] == "2030-08-17"
        assert data["numberOfVehicles"] == 1
        assert data["isOvernightStay"] is True
        assert data["unitTypeId"] == 1
        assert data["inventoryType"] == "CAMPING"

    def test_to_dict_custom_values(self):
        request = CartAddRequest(
            campsite_id="99999",
            facility_id="11111",
            arrival_date="2030-09-01",
            departure_date="2030-09-05",
            number_of_vehicles=3,
            is_overnight_stay=True,
        )
        data = request.to_dict()
        
        assert data["numberOfVehicles"] == 3


class TestDefaultHeaders:
    def test_accept_header(self):
        assert "Accept" in DEFAULT_HEADERS
        assert "application/json" in DEFAULT_HEADERS["Accept"]

    def test_content_type_header(self):
        assert "Content-Type" in DEFAULT_HEADERS
        assert DEFAULT_HEADERS["Content-Type"] == "application/json"

    def test_origin_header(self):
        assert "Origin" in DEFAULT_HEADERS
        assert DEFAULT_HEADERS["Origin"] == "https://www.recreation.gov"

    def test_user_agent_header(self):
        assert "User-Agent" in DEFAULT_HEADERS
        assert "Mozilla" in DEFAULT_HEADERS["User-Agent"]


class TestAvailabilityStatusMap:
    def test_available_statuses(self):
        assert AVAILABILITY_STATUS_MAP["Available"] is True
        assert AVAILABILITY_STATUS_MAP["Open"] is True

    def test_unavailable_statuses(self):
        assert AVAILABILITY_STATUS_MAP["Reserved"] is False
        assert AVAILABILITY_STATUS_MAP["Not Available"] is False
        assert AVAILABILITY_STATUS_MAP["Walk Up"] is False
        assert AVAILABILITY_STATUS_MAP["Not Reservable"] is False


class TestConstants:
    def test_base_url(self):
        assert BASE_URL == "https://www.recreation.gov"

    def test_api_base(self):
        assert API_BASE == "https://www.recreation.gov/api"
