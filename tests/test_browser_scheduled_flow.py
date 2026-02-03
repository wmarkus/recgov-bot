import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.browser.bot import RecGovBrowserBot
from src.common.models import ReservationAttempt, ReservationStatus


async def _idle_loop():
    try:
        while True:
            await asyncio.sleep(1)
    except asyncio.CancelledError:
        return


@pytest.mark.asyncio
async def test_run_scheduled_success_notifies(config, target):
    bot = RecGovBrowserBot(config)
    bot.scheduler = SimpleNamespace(wait_until=AsyncMock())
    bot.notifications = SimpleNamespace(
        notify_starting=AsyncMock(),
        notify_success=AsyncMock(),
        notify_failure=AsyncMock(),
    )
    bot._is_logged_in = AsyncMock(return_value=False)
    bot.login = AsyncMock(return_value=True)
    bot.navigate_to_campground = AsyncMock()
    bot._refresh_session_loop = _idle_loop

    success_attempt = ReservationAttempt(
        target=target,
        status=ReservationStatus.IN_CART,
    )
    bot.attempt_reservation = AsyncMock(return_value=success_attempt)

    result = await bot.run_scheduled(target)

    assert result.status == ReservationStatus.IN_CART
    assert bot.scheduler.wait_until.call_count == 2
    bot.notifications.notify_starting.assert_called_once()
    bot.notifications.notify_success.assert_called_once_with(success_attempt)
    bot.notifications.notify_failure.assert_not_called()


@pytest.mark.asyncio
async def test_run_scheduled_failure_notifies(config, target):
    bot = RecGovBrowserBot(config)
    bot.scheduler = SimpleNamespace(wait_until=AsyncMock())
    bot.notifications = SimpleNamespace(
        notify_starting=AsyncMock(),
        notify_success=AsyncMock(),
        notify_failure=AsyncMock(),
    )
    bot._is_logged_in = AsyncMock(return_value=True)
    bot.navigate_to_campground = AsyncMock()
    bot._refresh_session_loop = _idle_loop

    failed_attempt = ReservationAttempt(
        target=target,
        status=ReservationStatus.FAILED,
    )
    bot.attempt_reservation = AsyncMock(return_value=failed_attempt)

    result = await bot.run_scheduled(target)

    assert result.status == ReservationStatus.FAILED
    bot.notifications.notify_starting.assert_called_once()
    bot.notifications.notify_failure.assert_called_once_with(failed_attempt)
    bot.notifications.notify_success.assert_not_called()

