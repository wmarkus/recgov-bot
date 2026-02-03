import pytest
from unittest.mock import AsyncMock
from datetime import date, datetime, timedelta

from src.legacy.api.client import RecGovAPIClient
from src.legacy.api.auth import AuthenticationError
from src.common.models import (
    Campsite,
    AvailabilitySlot,
    CampsiteAvailability,
    CampsiteAvailabilityResult,
    CartItem,
    ReservationStatus,
)
from src.common.scheduler import RetryStrategy


def _availability_result(campsite_id: str, campground_id: str) -> CampsiteAvailabilityResult:
    campsite = Campsite(id=campsite_id, campground_id=campground_id, name=campsite_id)
    availability = AvailabilitySlot(date=date(2030, 8, 1), status=CampsiteAvailability.AVAILABLE)
    return CampsiteAvailabilityResult(campsite=campsite, availabilities=[availability])

def _cart_item(campsite_id: str, campground_id: str) -> CartItem:
    return CartItem(
        reservation_id="test",
        campsite=Campsite(id=campsite_id, campground_id=campground_id, name=campsite_id),
        arrival_date=date(2030, 8, 1),
        departure_date=date(2030, 8, 3),
        subtotal=10.0,
        fees=2.0,
        total=12.0,
        expires_at=datetime.now() + timedelta(minutes=15),
    )


@pytest.mark.asyncio
async def test_api_attempt_reservation_success_first_site(config, target):
    async with RecGovAPIClient(config) as client:
        cart_item = _cart_item(target.campsite_ids[0], target.campground_id)
        client.add_to_cart = AsyncMock(return_value=cart_item)
        client.find_available_sites = AsyncMock(return_value=[])

        result = await client.attempt_reservation(target, RetryStrategy(max_attempts=1))

        assert result.status == ReservationStatus.IN_CART
        client.add_to_cart.assert_called_once()


@pytest.mark.asyncio
async def test_api_attempt_reservation_uses_fallback_sites(config, target):
    config.target.campsite_ids = []
    target.campsite_ids = []
    available = [
        _availability_result("X1", config.target.campground_id),
        _availability_result("Y2", config.target.campground_id),
    ]

    async with RecGovAPIClient(config) as client:
        client.find_available_sites = AsyncMock(return_value=available)
        client.add_to_cart = AsyncMock(
            side_effect=[None, _cart_item("Y2", config.target.campground_id)]
        )

        result = await client.attempt_reservation(target, RetryStrategy(max_attempts=1))

        assert result.status == ReservationStatus.IN_CART
        assert client.add_to_cart.call_count == 2


@pytest.mark.asyncio
async def test_api_attempt_reservation_reauth_on_auth_error(config, target):
    async with RecGovAPIClient(config) as client:
        client.login = AsyncMock(return_value=True)
        client.add_to_cart = AsyncMock(
            side_effect=[
                AuthenticationError("expired"),
                _cart_item(target.campsite_ids[1], target.campground_id),
            ]
        )
        client.find_available_sites = AsyncMock(return_value=[])

        result = await client.attempt_reservation(target, RetryStrategy(max_attempts=1))

        assert result.status == ReservationStatus.IN_CART
        client.login.assert_called_once()


@pytest.mark.asyncio
async def test_api_attempt_reservation_no_available_sites(config, target):
    target.campsite_ids = []

    async with RecGovAPIClient(config) as client:
        client.find_available_sites = AsyncMock(return_value=[])
        client.add_to_cart = AsyncMock()

        result = await client.attempt_reservation(target, RetryStrategy(max_attempts=1))

        assert result.status == ReservationStatus.FAILED
        client.add_to_cart.assert_not_called()

