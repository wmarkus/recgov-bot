"""
Tests for precision scheduler (src/common/scheduler.py)
"""
import pytest
import asyncio
import time
from datetime import datetime, timedelta

import pytz

from src.common.scheduler import PrecisionScheduler, RateLimiter, RetryStrategy


class TestPrecisionScheduler:
    def test_now_returns_timezone_aware_datetime(self):
        scheduler = PrecisionScheduler("America/Los_Angeles")
        now = scheduler.now()
        assert now.tzinfo is not None
        assert str(now.tzinfo) == "America/Los_Angeles"

    def test_now_with_utc(self):
        scheduler = PrecisionScheduler("UTC")
        now = scheduler.now()
        assert now.tzinfo == pytz.UTC

    @pytest.mark.asyncio
    async def test_wait_until_past_time_returns_immediately(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() - timedelta(seconds=1)
        reached = await scheduler.wait_until(target)
        assert reached is True

    @pytest.mark.asyncio
    async def test_wait_until_future_time(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(milliseconds=50)
        start = time.monotonic()
        reached = await scheduler.wait_until(target)
        elapsed = time.monotonic() - start
        assert reached is True
        # Should have waited at least 40ms (some tolerance)
        assert elapsed >= 0.04

    @pytest.mark.asyncio
    async def test_wait_until_can_be_cancelled(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(seconds=10)

        async def cancel_after_delay():
            await asyncio.sleep(0.05)
            scheduler.cancel()

        asyncio.create_task(cancel_after_delay())
        reached = await scheduler.wait_until(target)
        assert reached is False

    @pytest.mark.asyncio
    async def test_wait_until_with_early_ms(self):
        scheduler = PrecisionScheduler("UTC")
        # Set target 100ms in the future
        target = scheduler.now() + timedelta(milliseconds=100)
        # But start 50ms early
        start = time.monotonic()
        reached = await scheduler.wait_until(target, early_ms=50)
        elapsed = time.monotonic() - start
        assert reached is True
        # Should have waited about 50ms (100 - 50), with tolerance
        assert 0.03 <= elapsed <= 0.15

    @pytest.mark.asyncio
    async def test_wait_until_localizes_naive_datetime(self):
        scheduler = PrecisionScheduler("UTC")
        # Naive datetime (no tzinfo) - use UTC time directly
        target = datetime.utcnow() - timedelta(seconds=1)
        assert target.tzinfo is None
        reached = await scheduler.wait_until(target)
        assert reached is True

    @pytest.mark.asyncio
    async def test_execute_at_runs_function(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(milliseconds=50)
        result = []

        async def test_func():
            result.append("executed")
            return "success"

        ret = await scheduler.execute_at(target, test_func)
        assert ret == "success"
        assert result == ["executed"]

    @pytest.mark.asyncio
    async def test_execute_at_returns_none_if_cancelled(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(seconds=10)
        result = []

        async def test_func():
            result.append("executed")
            return "success"

        async def cancel_after_delay():
            await asyncio.sleep(0.05)
            scheduler.cancel()

        asyncio.create_task(cancel_after_delay())
        ret = await scheduler.execute_at(target, test_func)
        assert ret is None
        assert result == []

    def test_time_until_future(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(minutes=5)
        delta = scheduler.time_until(target)
        assert 299 <= delta.total_seconds() <= 301

    def test_time_until_past(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() - timedelta(minutes=5)
        delta = scheduler.time_until(target)
        assert delta.total_seconds() < 0

    def test_time_until_localizes_naive_datetime(self):
        scheduler = PrecisionScheduler("UTC")
        # Use UTC time directly to avoid timezone conversion issues
        target = datetime.utcnow() + timedelta(minutes=5)
        assert target.tzinfo is None
        delta = scheduler.time_until(target)
        # Should work without error and be roughly 5 minutes
        assert 290 <= delta.total_seconds() <= 310

    def test_format_countdown_now_for_past_time(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() - timedelta(seconds=5)
        assert scheduler.format_countdown(target) == "NOW!"

    def test_format_countdown_seconds(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(seconds=45)
        countdown = scheduler.format_countdown(target)
        assert "s" in countdown
        assert "m" not in countdown

    def test_format_countdown_minutes_seconds(self):
        scheduler = PrecisionScheduler("UTC")
        target = scheduler.now() + timedelta(minutes=5, seconds=30)
        countdown = scheduler.format_countdown(target)
        assert "5m" in countdown
        assert "s" in countdown

    def test_format_countdown_hours(self):
        scheduler = PrecisionScheduler("UTC")
        # Use exact target to avoid edge cases near boundaries
        target = scheduler.now() + timedelta(hours=2, minutes=15, seconds=30)
        countdown = scheduler.format_countdown(target)
        assert "2h" in countdown
        # Allow for some timing variance: could be 15m or 14m
        assert "m" in countdown

    def test_format_countdown_days(self):
        scheduler = PrecisionScheduler("UTC")
        # Use exact target to avoid edge cases
        target = scheduler.now() + timedelta(days=3, hours=4, minutes=30)
        countdown = scheduler.format_countdown(target)
        assert "3d" in countdown
        # Allow for timing variance
        assert "h" in countdown


class TestRateLimiter:
    @pytest.mark.asyncio
    async def test_acquire_immediate_when_tokens_available(self):
        limiter = RateLimiter(requests_per_second=10.0)
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should be nearly immediate
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_acquire_waits_when_no_tokens(self):
        limiter = RateLimiter(requests_per_second=2.0)
        # Exhaust tokens
        await limiter.acquire()
        await limiter.acquire()
        
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should have waited ~0.5 seconds for token to refill
        assert elapsed >= 0.3

    @pytest.mark.asyncio
    async def test_acquire_refills_tokens_over_time(self):
        limiter = RateLimiter(requests_per_second=10.0)
        # Exhaust initial tokens
        for _ in range(10):
            await limiter.acquire()
        
        # Wait for tokens to refill
        await asyncio.sleep(0.5)
        
        start = time.monotonic()
        await limiter.acquire()
        elapsed = time.monotonic() - start
        # Should be nearly immediate after refill
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_context_manager_acquire(self):
        limiter = RateLimiter(requests_per_second=10.0)
        async with limiter:
            pass  # Just verify context manager works

    @pytest.mark.asyncio
    async def test_rate_limiting_enforces_rate(self):
        # Use a slower rate for more predictable test
        limiter = RateLimiter(requests_per_second=5.0)
        
        start = time.monotonic()
        # Make 8 requests at 5/s
        for _ in range(8):
            await limiter.acquire()
        elapsed = time.monotonic() - start
        
        # 8 requests at 5/s: first 5 immediate, next 3 need waiting (~0.6s)
        # Use a conservative threshold for timing-sensitive tests
        assert elapsed >= 0.4

    @pytest.mark.asyncio
    async def test_tokens_cap_at_rate(self):
        limiter = RateLimiter(requests_per_second=5.0)
        # Wait to let tokens accumulate
        await asyncio.sleep(2.0)
        
        # Tokens should be capped at 5 (the rate)
        # So we should only be able to make 5 immediate requests
        start = time.monotonic()
        for _ in range(5):
            await limiter.acquire()
        first_five_elapsed = time.monotonic() - start
        
        # First 5 should be immediate
        assert first_five_elapsed < 0.1
        
        # 6th should require waiting
        start = time.monotonic()
        await limiter.acquire()
        sixth_elapsed = time.monotonic() - start
        assert sixth_elapsed >= 0.1


class TestRetryStrategy:
    def test_default_values(self):
        strategy = RetryStrategy()
        assert strategy.max_attempts == 10
        assert strategy.base_delay_ms == 100
        assert strategy.max_delay_ms == 5000
        assert strategy.exponential_backoff is False
        assert strategy.attempts == 0

    def test_custom_values(self):
        strategy = RetryStrategy(
            max_attempts=5,
            base_delay_ms=200,
            max_delay_ms=10000,
            exponential_backoff=True,
        )
        assert strategy.max_attempts == 5
        assert strategy.base_delay_ms == 200
        assert strategy.max_delay_ms == 10000
        assert strategy.exponential_backoff is True

    def test_should_retry_initial(self):
        strategy = RetryStrategy(max_attempts=3)
        assert strategy.should_retry() is True

    def test_should_retry_after_attempts(self):
        strategy = RetryStrategy(max_attempts=3)
        strategy.record_attempt()
        assert strategy.should_retry() is True
        strategy.record_attempt()
        assert strategy.should_retry() is True
        strategy.record_attempt()
        assert strategy.should_retry() is False

    def test_record_attempt_increments_counter(self):
        strategy = RetryStrategy()
        assert strategy.attempts == 0
        strategy.record_attempt()
        assert strategy.attempts == 1
        strategy.record_attempt()
        assert strategy.attempts == 2

    @pytest.mark.asyncio
    async def test_wait_constant_delay(self):
        strategy = RetryStrategy(base_delay_ms=50, exponential_backoff=False)
        strategy.record_attempt()
        
        start = time.monotonic()
        await strategy.wait()
        elapsed = time.monotonic() - start
        
        # Should wait ~50ms
        assert 0.04 <= elapsed <= 0.15

    @pytest.mark.asyncio
    async def test_wait_exponential_backoff(self):
        strategy = RetryStrategy(
            base_delay_ms=10,
            max_delay_ms=1000,
            exponential_backoff=True,
        )
        
        # First attempt: 10ms
        strategy.record_attempt()
        start = time.monotonic()
        await strategy.wait()
        elapsed1 = time.monotonic() - start
        
        # Second attempt: 20ms
        strategy.record_attempt()
        start = time.monotonic()
        await strategy.wait()
        elapsed2 = time.monotonic() - start
        
        # Third attempt: 40ms
        strategy.record_attempt()
        start = time.monotonic()
        await strategy.wait()
        elapsed3 = time.monotonic() - start
        
        # Each wait should be roughly double the previous
        assert elapsed2 > elapsed1
        assert elapsed3 > elapsed2

    @pytest.mark.asyncio
    async def test_wait_respects_max_delay(self):
        strategy = RetryStrategy(
            base_delay_ms=100,
            max_delay_ms=150,
            exponential_backoff=True,
        )
        
        # After many attempts, delay should be capped
        for _ in range(10):
            strategy.record_attempt()
        
        start = time.monotonic()
        await strategy.wait()
        elapsed = time.monotonic() - start
        
        # Should be capped at 150ms, not 100 * 2^9 = 51200ms
        assert elapsed < 0.3

    def test_reset_clears_attempts(self):
        strategy = RetryStrategy(max_attempts=3)
        strategy.record_attempt()
        strategy.record_attempt()
        assert strategy.attempts == 2
        
        strategy.reset()
        assert strategy.attempts == 0
        assert strategy.should_retry() is True

    def test_max_attempts_zero(self):
        strategy = RetryStrategy(max_attempts=0)
        assert strategy.should_retry() is False

    def test_max_attempts_one(self):
        strategy = RetryStrategy(max_attempts=1)
        assert strategy.should_retry() is True
        strategy.record_attempt()
        assert strategy.should_retry() is False
