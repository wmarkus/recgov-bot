import pytest
from datetime import timedelta

from src.common.scheduler import PrecisionScheduler


@pytest.mark.asyncio
async def test_wait_until_past_time_returns_immediately():
    scheduler = PrecisionScheduler("UTC")
    target = scheduler.now() - timedelta(seconds=1)
    reached = await scheduler.wait_until(target)
    assert reached is True


def test_format_countdown_now_for_past_time():
    scheduler = PrecisionScheduler("UTC")
    target = scheduler.now() - timedelta(seconds=5)
    assert scheduler.format_countdown(target) == "NOW!"

