"""
Recreation.gov Direct API Client

This module provides direct API access for faster reservation attempts.
Uses reverse-engineered endpoints - may break if Recreation.gov changes their API.
"""
import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Dict, Any
import httpx

from .endpoints import Endpoints, DEFAULT_HEADERS, WebPages, CartAddRequest
from .auth import RecGovAuth, AuthenticationError
from ...common.models import (
    Campground,
    Campsite,
    CampsiteAvailability,
    AvailabilitySlot,
    CampsiteAvailabilityResult,
    ReservationTarget,
    ReservationAttempt,
    ReservationStatus,
    CartItem,
)
from ...common.config import Config
from ...common.scheduler import RateLimiter, RetryStrategy
from ...common.notifications import NotificationManager

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Raised when API request fails"""
    def __init__(self, message: str, status_code: Optional[int] = None, response_body: Optional[str] = None):
        super().__init__(message)
        self.status_code = status_code
        self.response_body = response_body


class RecGovAPIClient:
    """
    Direct API client for Recreation.gov.
    
    This provides faster reservation attempts than browser automation,
    but is more fragile and may trigger bot detection.
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.auth = RecGovAuth(session_file=config.browser.session_file)
        self.rate_limiter = RateLimiter(config.api.requests_per_second)
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            timeout=config.api.timeout,
            follow_redirects=True
        )
        self.notifications: Optional[NotificationManager] = None
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, *args):
        await self.client.aclose()
    
    # ========================================
    # Authentication
    # ========================================
    
    async def login(self) -> bool:
        """Login with configured credentials"""
        try:
            # Try to load existing session first
            existing = self.auth.load_session()
            if existing and not existing.is_expired():
                logger.info("Using existing session")
                return True
            
            # Perform fresh login
            await self.auth.login(
                self.config.credentials.email,
                self.config.credentials.password
            )
            return True
            
        except AuthenticationError as e:
            logger.error(f"Login failed: {e}")
            return False
    
    # ========================================
    # Availability Checking
    # ========================================
    
    async def get_campground_availability(
        self,
        campground_id: str,
        month: date
    ) -> Dict[str, CampsiteAvailabilityResult]:
        """
        Get availability for all campsites in a campground.
        
        Args:
            campground_id: Campground ID (e.g., "232447")
            month: First day of month to check
            
        Returns:
            Dict mapping campsite_id to availability data
        """
        async with self.rate_limiter:
            start_date = month.replace(day=1).strftime("%Y-%m-%dT00:00:00.000Z")
            url = Endpoints.campground_availability(campground_id, start_date)
            
            response = await self.client.get(
                url,
                cookies=self.auth.get_cookies(),
                headers=self.auth.get_auth_headers()
            )
            
            if response.status_code != 200:
                raise APIError(
                    f"Failed to get availability: {response.status_code}",
                    response.status_code,
                    response.text
                )
            
            data = response.json()
            results = {}
            
            for site_id, site_data in data.get("campsites", {}).items():
                campsite = Campsite(
                    id=site_id,
                    campground_id=campground_id,
                    name=site_data.get("site", site_id),
                    site_type=site_data.get("campsite_type"),
                    max_people=site_data.get("max_num_people"),
                    min_people=site_data.get("min_num_people"),
                    loop=site_data.get("loop")
                )
                
                availabilities = []
                for date_str, status in site_data.get("availabilities", {}).items():
                    try:
                        slot_date = datetime.fromisoformat(
                            date_str.replace("Z", "+00:00")
                        ).date()
                        try:
                            availability_status = CampsiteAvailability(status)
                        except ValueError:
                            availability_status = CampsiteAvailability.NOT_AVAILABLE
                        availabilities.append(AvailabilitySlot(
                            date=slot_date,
                            status=availability_status
                        ))
                    except (ValueError, KeyError):
                        continue
                
                results[site_id] = CampsiteAvailabilityResult(
                    campsite=campsite,
                    availabilities=sorted(availabilities, key=lambda x: x.date)
                )
            
            return results
    
    async def find_available_sites(
        self,
        target: ReservationTarget
    ) -> List[CampsiteAvailabilityResult]:
        """
        Find all available campsites matching the target criteria.
        
        Returns sites in priority order (if campsite_ids specified) or all available.
        """
        # Get availability for the relevant month(s)
        months_needed = set()
        current = target.arrival_date
        while current <= target.departure_date:
            months_needed.add(current.replace(day=1))
            current = date(
                current.year + (current.month // 12),
                (current.month % 12) + 1,
                1
            )
        
        # Fetch availability for each month
        all_availability = {}
        for month in months_needed:
            availability = await self.get_campground_availability(
                target.campground_id,
                month
            )
            # Merge results
            for site_id, result in availability.items():
                if site_id not in all_availability:
                    all_availability[site_id] = result
                else:
                    all_availability[site_id].availabilities.extend(result.availabilities)
        
        # Filter to available sites
        available = []
        for site_id, result in all_availability.items():
            # Check if specific sites are requested
            if target.campsite_ids and site_id not in target.campsite_ids:
                continue
            
            # Check full date range availability
            if result.is_available_for_dates(target.arrival_date, target.departure_date):
                available.append(result)
        
        # Sort by priority if specific sites requested
        if target.campsite_ids:
            priority = {sid: i for i, sid in enumerate(target.campsite_ids)}
            available.sort(key=lambda x: priority.get(x.campsite.id, 999))
        
        logger.info(f"Found {len(available)} available sites")
        return available
    
    # ========================================
    # Cart Operations
    # ========================================
    
    async def add_to_cart(
        self,
        campsite_id: str,
        facility_id: str,
        arrival_date: date,
        departure_date: date
    ) -> Optional[CartItem]:
        """
        Add a campsite reservation to cart.
        
        This is the critical path - must be as fast as possible.
        
        Returns:
            CartItem if successful, None if failed
        """
        async with self.rate_limiter:
            request = CartAddRequest(
                campsite_id=campsite_id,
                facility_id=facility_id,
                arrival_date=arrival_date.isoformat(),
                departure_date=departure_date.isoformat()
            )
            
            logger.info(f"Adding campsite {campsite_id} to cart...")
            
            response = await self.client.post(
                Endpoints.add_to_cart(),
                json=request.to_dict(),
                cookies=self.auth.get_cookies(),
                headers=self.auth.get_auth_headers()
            )
            
            if response.status_code == 200:
                data = response.json()
                logger.info(f"Successfully added to cart!")
                
                # Parse cart item from response
                # Note: actual response structure may vary
                return CartItem(
                    reservation_id=data.get("reservationId", "unknown"),
                    campsite=Campsite(
                        id=campsite_id,
                        campground_id=facility_id,
                        name=data.get("siteName", campsite_id)
                    ),
                    arrival_date=arrival_date,
                    departure_date=departure_date,
                    subtotal=data.get("subtotal", 0),
                    fees=data.get("fees", 0),
                    total=data.get("total", 0),
                    expires_at=datetime.now() + __import__('datetime').timedelta(minutes=15)
                )
            
            elif response.status_code == 409:
                # Site no longer available
                logger.warning(f"Site {campsite_id} no longer available")
                return None
            
            elif response.status_code == 401:
                logger.error("Session expired during add to cart")
                raise AuthenticationError("Session expired")
            
            else:
                logger.error(f"Add to cart failed: {response.status_code} - {response.text}")
                return None
    
    async def get_cart(self) -> List[CartItem]:
        """Get current cart contents"""
        async with self.rate_limiter:
            response = await self.client.get(
                Endpoints.cart(),
                cookies=self.auth.get_cookies(),
                headers=self.auth.get_auth_headers()
            )
            
            if response.status_code != 200:
                raise APIError("Failed to get cart", response.status_code)
            
            # Parse cart items
            # Note: actual response structure needs verification
            data = response.json()
            items = []
            
            for item_data in data.get("items", []):
                items.append(CartItem(
                    reservation_id=item_data.get("id"),
                    campsite=Campsite(
                        id=item_data.get("campsiteId"),
                        campground_id=item_data.get("facilityId"),
                        name=item_data.get("siteName", "Unknown")
                    ),
                    arrival_date=date.fromisoformat(item_data.get("arrivalDate")),
                    departure_date=date.fromisoformat(item_data.get("departureDate")),
                    subtotal=item_data.get("subtotal", 0),
                    fees=item_data.get("fees", 0),
                    total=item_data.get("total", 0),
                    expires_at=datetime.fromisoformat(item_data.get("expiresAt", datetime.now().isoformat()))
                ))
            
            return items
    
    async def clear_cart(self):
        """Remove all items from cart"""
        items = await self.get_cart()
        for item in items:
            async with self.rate_limiter:
                await self.client.delete(
                    Endpoints.remove_from_cart(item.reservation_id),
                    cookies=self.auth.get_cookies(),
                    headers=self.auth.get_auth_headers()
                )
    
    # ========================================
    # Main Reservation Flow
    # ========================================
    
    async def attempt_reservation(
        self,
        target: ReservationTarget,
        retry_strategy: Optional[RetryStrategy] = None
    ) -> ReservationAttempt:
        """
        Attempt to reserve a campsite.
        
        This is the main entry point for reservation attempts.
        Tries each site in priority order with retries.
        """
        if retry_strategy is None:
            retry_strategy = RetryStrategy(
                max_attempts=self.config.retry.max_attempts,
                base_delay_ms=self.config.retry.attempt_delay_ms
            )
        
        attempt = ReservationAttempt(
            target=target,
            status=ReservationStatus.ATTEMPTING,
            started_at=datetime.now()
        )
        
        # Determine sites to try
        sites_to_try = target.campsite_ids.copy() if target.campsite_ids else []
        
        # If no specific sites or we should use fallbacks, find available sites
        if not sites_to_try or self.config.retry.use_fallback_sites:
            available = await self.find_available_sites(target)
            for result in available:
                if result.campsite.id not in sites_to_try:
                    sites_to_try.append(result.campsite.id)
        
        if not sites_to_try:
            attempt.mark_failed("No available sites found")
            return attempt
        
        logger.info(f"Attempting reservation for {len(sites_to_try)} sites")
        
        # Try each site with retries
        while retry_strategy.should_retry():
            retry_strategy.record_attempt()
            attempt.attempts_made = retry_strategy.attempts
            
            for site_id in sites_to_try:
                try:
                    cart_item = await self.add_to_cart(
                        campsite_id=site_id,
                        facility_id=target.campground_id,
                        arrival_date=target.arrival_date,
                        departure_date=target.departure_date
                    )
                    
                    if cart_item:
                        attempt.mark_success(
                            campsite=cart_item.campsite,
                            cart_item=cart_item
                        )
                        return attempt
                    
                except AuthenticationError:
                    # Try to re-login and continue
                    await self.login()
                    
                except Exception as e:
                    logger.error(f"Error adding site {site_id}: {e}")
            
            # Wait before retry
            if retry_strategy.should_retry():
                await retry_strategy.wait()
        
        attempt.mark_failed(f"Failed after {attempt.attempts_made} attempts")
        return attempt


# CLI interface
async def main():
    """CLI entry point"""
    import click
    from rich.console import Console
    from rich.table import Table
    
    console = Console()
    
    @click.group()
    def cli():
        """Recreation.gov API Client"""
        pass
    
    @cli.command()
    @click.option("--config", "-c", default="config/config.yaml", help="Config file path")
    def check(config):
        """Check campsite availability"""
        async def run():
            cfg = Config.from_yaml(config)
            async with RecGovAPIClient(cfg) as client:
                target = ReservationTarget(
                    campground_id=cfg.target.campground_id,
                    campsite_ids=cfg.target.campsite_ids,
                    arrival_date=cfg.target.arrival.date(),
                    departure_date=cfg.target.departure.date()
                )
                
                available = await client.find_available_sites(target)
                
                table = Table(title="Available Campsites")
                table.add_column("Site ID")
                table.add_column("Name")
                table.add_column("Loop")
                table.add_column("Max People")
                
                for result in available:
                    table.add_row(
                        result.campsite.id,
                        result.campsite.name,
                        result.campsite.loop or "-",
                        str(result.campsite.max_people or "-")
                    )
                
                console.print(table)
        
        asyncio.run(run())
    
    @cli.command()
    @click.option("--config", "-c", default="config/config.yaml", help="Config file path")
    def reserve(config):
        """Attempt to make a reservation"""
        async def run():
            cfg = Config.from_yaml(config)
            async with RecGovAPIClient(cfg) as client:
                # Login first
                if not await client.login():
                    console.print("[red]Login failed![/red]")
                    return
                
                console.print("[green]Logged in successfully[/green]")
                
                target = ReservationTarget(
                    campground_id=cfg.target.campground_id,
                    campsite_ids=cfg.target.campsite_ids,
                    arrival_date=cfg.target.arrival.date(),
                    departure_date=cfg.target.departure.date()
                )
                
                console.print(f"Attempting reservation for {target.campground_id}...")
                
                result = await client.attempt_reservation(target)
                
                if result.status == ReservationStatus.IN_CART:
                    console.print(f"[bold green]SUCCESS![/bold green] Site {result.campsite_secured.name} added to cart!")
                    console.print(f"Checkout URL: {result.checkout_url}")
                    console.print(f"[yellow]Complete checkout within 15 minutes![/yellow]")
                else:
                    console.print(f"[red]Failed: {result.error_message}[/red]")
        
        asyncio.run(run())
    
    cli()


if __name__ == "__main__":
    main()
