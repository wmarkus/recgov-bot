"""
Precision scheduler for Recreation.gov bot

Handles timing-critical operations with millisecond accuracy.
"""
import asyncio
import time
import logging
from datetime import datetime, timedelta
from typing import Callable, Awaitable, Optional
import pytz

logger = logging.getLogger(__name__)


class PrecisionScheduler:
    """
    High-precision scheduler for timing-critical operations.
    
    Uses a combination of sleep and busy-wait for accuracy.
    """
    
    def __init__(self, timezone: str = "America/Los_Angeles"):
        self.tz = pytz.timezone(timezone)
        self._cancelled = False
    
    def now(self) -> datetime:
        """Get current time in configured timezone"""
        return datetime.now(self.tz)
    
    def cancel(self):
        """Cancel any pending waits"""
        self._cancelled = True
    
    async def wait_until(
        self, 
        target: datetime,
        callback: Optional[Callable[[], None]] = None,
        early_ms: int = 0
    ) -> bool:
        """
        Wait until the target time with high precision.
        
        Args:
            target: Target datetime (should be timezone-aware)
            callback: Optional callback to call every second while waiting
            early_ms: Milliseconds before target to trigger (negative = before, positive = after)
            
        Returns:
            True if reached target time, False if cancelled
        """
        self._cancelled = False
        
        # Ensure target is timezone-aware
        if target.tzinfo is None:
            target = self.tz.localize(target)
        
        # Adjust for early start
        adjusted_target = target - timedelta(milliseconds=early_ms)
        
        logger.info(f"Waiting until {target.isoformat()} (adjusted: {adjusted_target.isoformat()})")
        
        while not self._cancelled:
            now = datetime.now(self.tz)
            remaining = (adjusted_target - now).total_seconds()
            
            if remaining <= 0:
                logger.info("Target time reached!")
                return True
            
            if callback:
                callback()
            
            # Use different strategies based on remaining time
            if remaining > 60:
                # More than 1 minute: sleep in 30-second chunks
                await asyncio.sleep(30)
            elif remaining > 5:
                # 5-60 seconds: sleep in 1-second chunks
                await asyncio.sleep(1)
            elif remaining > 0.5:
                # 0.5-5 seconds: sleep in 100ms chunks
                await asyncio.sleep(0.1)
            elif remaining > 0.01:
                # 10ms - 500ms: sleep in 1ms chunks
                await asyncio.sleep(0.001)
            else:
                # Under 10ms: busy-wait for precision
                while (adjusted_target - datetime.now(self.tz)).total_seconds() > 0:
                    pass
                return True
        
        logger.info("Wait cancelled")
        return False
    
    async def execute_at(
        self,
        target: datetime,
        func: Callable[[], Awaitable],
        early_ms: int = 0
    ):
        """
        Execute an async function at the target time.
        
        Args:
            target: Target datetime
            func: Async function to execute
            early_ms: Milliseconds adjustment
        """
        reached = await self.wait_until(target, early_ms=early_ms)
        if reached:
            return await func()
        return None
    
    def time_until(self, target: datetime) -> timedelta:
        """Get timedelta until target"""
        now = datetime.now(self.tz)
        if target.tzinfo is None:
            target = self.tz.localize(target)
        return target - now
    
    def format_countdown(self, target: datetime) -> str:
        """Format remaining time as human-readable string"""
        delta = self.time_until(target)
        total_seconds = int(delta.total_seconds())
        
        if total_seconds < 0:
            return "NOW!"
        
        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60
        
        parts = []
        if days > 0:
            parts.append(f"{days}d")
        if hours > 0:
            parts.append(f"{hours}h")
        if minutes > 0:
            parts.append(f"{minutes}m")
        parts.append(f"{seconds}s")
        
        return " ".join(parts)


class RateLimiter:
    """
    Rate limiter for API requests.
    
    Uses token bucket algorithm.
    """
    
    def __init__(self, requests_per_second: float = 2.0):
        self.rate = requests_per_second
        self.tokens = requests_per_second
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()
    
    async def acquire(self):
        """Wait until a request can be made"""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * self.rate)
            self.last_update = now
            
            if self.tokens < 1:
                wait_time = (1 - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1
    
    async def __aenter__(self):
        await self.acquire()
        return self
    
    async def __aexit__(self, *args):
        pass


class RetryStrategy:
    """
    Configurable retry strategy for reservation attempts.
    """
    
    def __init__(
        self,
        max_attempts: int = 10,
        base_delay_ms: int = 100,
        max_delay_ms: int = 5000,
        exponential_backoff: bool = False
    ):
        self.max_attempts = max_attempts
        self.base_delay_ms = base_delay_ms
        self.max_delay_ms = max_delay_ms
        self.exponential_backoff = exponential_backoff
        self.attempts = 0
    
    def should_retry(self) -> bool:
        """Check if another attempt should be made"""
        return self.attempts < self.max_attempts
    
    def record_attempt(self):
        """Record an attempt"""
        self.attempts += 1
    
    async def wait(self):
        """Wait appropriate time before next attempt"""
        if self.exponential_backoff:
            delay_ms = min(
                self.base_delay_ms * (2 ** (self.attempts - 1)),
                self.max_delay_ms
            )
        else:
            delay_ms = self.base_delay_ms
        
        await asyncio.sleep(delay_ms / 1000)
    
    def reset(self):
        """Reset attempt counter"""
        self.attempts = 0


async def countdown_display(
    target: datetime,
    scheduler: PrecisionScheduler,
    update_interval: float = 1.0
):
    """
    Display a countdown to target time.
    
    Useful for CLI feedback.
    """
    from rich.live import Live
    from rich.text import Text
    from rich.panel import Panel
    
    with Live(refresh_per_second=4) as live:
        while scheduler.time_until(target).total_seconds() > 0:
            countdown = scheduler.format_countdown(target)
            panel = Panel(
                Text(countdown, style="bold green", justify="center"),
                title="⏰ Reservation Window Opens In",
                border_style="green"
            )
            live.update(panel)
            await asyncio.sleep(update_interval)
    
    print("🚀 GO TIME!")
