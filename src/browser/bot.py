"""
Recreation.gov Browser Automation Bot

Uses Playwright to automate the full reservation flow through a real browser.
More reliable than direct API but slower.
"""
import asyncio
import logging
from datetime import datetime, date
from typing import Optional, List, Callable, Awaitable
from pathlib import Path

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
)

from .session import BrowserSession, SessionHandoff
from .urls import WebPages
from ..common.models import (
    Campground,
    Campsite,
    ReservationTarget,
    ReservationAttempt,
    ReservationStatus,
    CartItem,
)
from ..common.config import Config
from ..common.notifications import NotificationManager
from ..common.scheduler import PrecisionScheduler, RetryStrategy

logger = logging.getLogger(__name__)


class RecGovBrowserBot:
    """
    Browser-based automation for Recreation.gov reservations.
    
    This approach:
    - Uses a real browser (Chromium via Playwright)
    - Handles JavaScript-rendered content
    - Can pause for CAPTCHA human intervention
    - Provides seamless session handoff
    """
    
    def __init__(self, config: Config):
        self.config = config
        self.playwright: Optional[Playwright] = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.session = BrowserSession(config.browser.session_file)
        self.notifications = NotificationManager(config.notifications)
        self.scheduler = PrecisionScheduler(config.schedule.timezone)
        
        # Callbacks for external handling
        self.on_captcha: Optional[Callable[[str], Awaitable[None]]] = None
        self.on_success: Optional[Callable[[ReservationAttempt], Awaitable[None]]] = None
    
    async def start(self):
        """Start the browser"""
        logger.info("Starting browser...")
        
        self.playwright = await async_playwright().start()
        
        # Launch browser
        self.browser = await self.playwright.chromium.launch(
            headless=self.config.browser.headless,
            slow_mo=self.config.browser.slow_mo,
        )
        
        # Create context with custom user agent
        self.context = await self.browser.new_context(
            user_agent=self.config.browser.user_agent,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        
        # Create page
        self.page = await self.context.new_page()
        
        # Try to restore session
        if self.config.browser.save_session and self.session.load():
            if not self.session.is_expired():
                await self.session.restore_to_context(self.context, self.page)
                logger.info("Previous session restored")
        
        logger.info("Browser started")
    
    async def stop(self):
        """Stop the browser"""
        if self.context:
            await self.context.close()
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        logger.info("Browser stopped")
    
    async def __aenter__(self):
        await self.start()
        return self
    
    async def __aexit__(self, *args):
        await self.stop()
    
    # ========================================
    # Navigation and Login
    # ========================================
    
    async def navigate_to_home(self):
        """Navigate to Recreation.gov homepage"""
        await self.page.goto(WebPages.home())
        await self.page.wait_for_load_state("domcontentloaded")
    
    async def login(self, email: Optional[str] = None, password: Optional[str] = None) -> bool:
        """
        Login to Recreation.gov.
        
        Returns True if login successful.
        """
        email = email or self.config.credentials.email
        password = password or self.config.credentials.password
        
        logger.info(f"Logging in as {email}...")
        
        try:
            # Go to login page
            await self.page.goto(WebPages.login())
            await self.page.wait_for_load_state("domcontentloaded")
            
            # Wait for login form elements to be ready
            await self.page.wait_for_selector(
                'input[name="email"], input[type="email"], input[id="email"]',
                timeout=15000
            )
            
            # Check if already logged in
            if await self._is_logged_in():
                logger.info("Already logged in")
                return True
            
            # Fill login form
            await self.page.fill('input[name="email"], input[type="email"]', email)
            await self.page.fill('input[name="password"], input[type="password"]', password)
            
            # Click login button
            await self.page.click('button[type="submit"]')
            
            # Wait for navigation after login
            await self.page.wait_for_load_state("domcontentloaded")
            # Give time for redirect and session establishment
            await asyncio.sleep(3)
            
            # Debug: log current URL after login attempt
            logger.info(f"Post-login URL: {self.page.url}")
            
            # First check if login already succeeded (invisible reCAPTCHA passed automatically)
            if await self._is_logged_in():
                logger.info("Login successful")
                await self.session.capture_from_page(self.page, self.context)
                return True
            
            # Only check for blocking CAPTCHA if not logged in
            if await self._check_captcha():
                logger.warning("CAPTCHA detected during login")
                await self._handle_captcha()
                
                # Check login again after CAPTCHA
                if await self._is_logged_in():
                    logger.info("Login successful after CAPTCHA")
                    await self.session.capture_from_page(self.page, self.context)
                    return True
            
            # Check for error message
            error = await self.page.query_selector('.error-message, .alert-danger')
            if error:
                error_text = await error.text_content()
                logger.error(f"Login failed: {error_text}")
            else:
                logger.error("Login failed: Unknown error")
            
            return False
            
        except PlaywrightTimeout:
            logger.error("Login timed out")
            return False
        except Exception as e:
            logger.error(f"Login error: {e}")
            return False
    
    async def _is_logged_in(self) -> bool:
        """Check if currently logged in"""
        # Primary check: Look for user menu or account indicators
        indicators = [
            '[data-component="UserMenu"]',
            '.user-menu',
            'a[href*="/account"]',
            'button:has-text("Sign Out")',
            'a:has-text("Sign Out")',
            'button:has-text("Log Out")',
            'a:has-text("Log Out")',
            '[data-testid="user-menu"]',
            '[aria-label*="account"]',
            '[aria-label*="Account"]',
            '.nav-account',
            '#account-menu',
            # Common avatar/profile indicators
            '.user-avatar',
            '.profile-icon',
            '[data-testid="avatar"]',
            'img[alt*="profile"]',
            'img[alt*="avatar"]',
        ]
        
        for selector in indicators:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    logger.debug(f"Logged in indicator found: {selector}")
                    return True
            except:
                continue
        
        # Secondary check: Login form/button is NOT present
        # If we're on homepage and login elements are gone, we're logged in
        login_indicators = [
            'input[name="email"]',
            'input[type="password"]',
            'a:has-text("Sign In")',
            'a:has-text("Log In")',
            'button:has-text("Sign In")',
        ]
        
        login_elements_found = 0
        for selector in login_indicators:
            try:
                element = await self.page.query_selector(selector)
                if element and await element.is_visible():
                    login_elements_found += 1
            except:
                continue
        
        # If no login elements visible and we're on homepage, assume logged in
        if login_elements_found == 0:
            url = self.page.url.lower()
            if 'recreation.gov' in url and '/log-in' not in url:
                logger.info("No login elements visible - assuming logged in")
                return True
        
        return False
    
    async def _check_captcha(self) -> bool:
        """Check if a blocking CAPTCHA challenge is present (not invisible reCAPTCHA)"""
        # Check for visible reCAPTCHA challenge iframe (the actual challenge, not the badge)
        captcha_challenges = [
            # reCAPTCHA challenge iframe (visible challenge popup)
            'iframe[src*="recaptcha"][src*="bframe"]',
            'iframe[title*="recaptcha challenge"]',
            # Visible CAPTCHA container that's blocking
            '.rc-imageselect',  # Image selection challenge
            '.rc-doscaptcha',   # "Try again" challenge
            '#captcha-box:visible',
            # hCaptcha
            'iframe[src*="hcaptcha"]',
        ]
        
        for selector in captcha_challenges:
            try:
                element = await self.page.query_selector(selector)
                if element:
                    # Verify it's actually visible
                    is_visible = await element.is_visible()
                    if is_visible:
                        return True
            except:
                continue
        
        # Also check if we're on an explicit CAPTCHA/challenge page
        try:
            url = self.page.url.lower()
            if 'captcha' in url or 'challenge' in url:
                return True
        except:
            pass
        
        return False
    
    async def _handle_captcha(self):
        """
        Handle CAPTCHA - pause for human intervention.
        """
        logger.warning("CAPTCHA detected - human intervention required")
        
        # Send notification
        await self.notifications.notify_captcha(self.page.url)
        
        if self.on_captcha:
            await self.on_captcha(self.page.url)
        
        # Wait for CAPTCHA to be solved (poll for page change)
        print("\n" + "=" * 60)
        print("⚠️  CAPTCHA DETECTED")
        print("Please solve the CAPTCHA in the browser window.")
        print("Waiting for you to complete it...")
        print("=" * 60 + "\n")
        
        # Wait up to 5 minutes for CAPTCHA
        start = datetime.now()
        timeout = 300  # 5 minutes
        
        while (datetime.now() - start).total_seconds() < timeout:
            await asyncio.sleep(2)
            
            # Check if CAPTCHA is gone
            if not await self._check_captcha():
                logger.info("CAPTCHA solved")
                return
            
            # Check if we navigated away
            if "captcha" not in self.page.url.lower() and await self._is_logged_in():
                logger.info("CAPTCHA bypassed")
                return
        
        logger.error("CAPTCHA timeout")
        raise TimeoutError("CAPTCHA was not solved in time")
    
    # ========================================
    # Campground Navigation
    # ========================================
    
    async def navigate_to_campground(self, campground_id: str):
        """Navigate to a campground page"""
        url = WebPages.campground(campground_id)
        logger.info(f"Navigating to campground {campground_id}")
        await self.page.goto(url)
        await self.page.wait_for_load_state("domcontentloaded")
        # Wait for campground content to load
        await self.page.wait_for_selector('h1, [data-component="FacilityHeader"]', timeout=15000)
    
    async def navigate_to_availability(self, campground_id: str, arrival: date, departure: date):
        """Navigate to campground availability with dates set"""
        # Go to availability page
        url = WebPages.availability(campground_id)
        logger.info(f"Navigating to availability: {url}")
        await self.page.goto(url)
        await self.page.wait_for_load_state("domcontentloaded")
        
        # Wait for page content to load - use flexible selectors
        availability_indicators = [
            '[data-component="AvailabilityGrid"]',
            '.availability-grid',
            '.rec-availability-grid',
            'table[class*="availability"]',
            '[class*="availability"]',
            '.campsite-row',
            '[data-testid="availability"]',
        ]
        
        for selector in availability_indicators:
            try:
                await self.page.wait_for_selector(selector, timeout=5000)
                logger.info(f"Found availability grid with selector: {selector}")
                break
            except:
                continue
        
        # Give extra time for dynamic content
        await asyncio.sleep(2)
        
        # Set dates if date inputs are available
        await self._set_dates(arrival, departure)
    
    async def _set_dates(self, arrival: date, departure: date):
        """Set arrival and departure dates in the date picker"""
        # Format dates
        arrival_str = arrival.strftime("%m/%d/%Y")
        departure_str = departure.strftime("%m/%d/%Y")
        
        try:
            # Try to find and fill date inputs
            arrival_input = await self.page.query_selector(
                'input[name="arrivalDate"], input[placeholder*="Arrival"]'
            )
            departure_input = await self.page.query_selector(
                'input[name="departureDate"], input[placeholder*="Departure"]'
            )
            
            if arrival_input and departure_input:
                await arrival_input.fill(arrival_str)
                await departure_input.fill(departure_str)
                await self.page.keyboard.press("Enter")
            else:
                # Try clicking date picker and selecting dates
                # This is campground-page specific
                logger.warning("Date inputs not found, trying alternative method")
                
        except Exception as e:
            logger.warning(f"Failed to set dates: {e}")
    
    # ========================================
    # Reservation Flow
    # ========================================
    
    async def find_available_sites(self, campground_id: str, arrival: date, departure: date) -> List[str]:
        """
        Find available campsite IDs for the given dates.
        
        Returns list of campsite IDs that are available.
        """
        await self.navigate_to_availability(campground_id, arrival, departure)
        
        # Wait for availability grid
        await asyncio.sleep(2)  # Let data load
        
        # Find available site buttons
        available = []
        
        try:
            # Look for "Available" buttons/links
            buttons = await self.page.query_selector_all(
                'button:has-text("Available"), a:has-text("Available")'
            )
            
            for button in buttons:
                # Try to extract campsite ID from parent or data attribute
                site_id = await button.get_attribute("data-campsite-id")
                if not site_id:
                    # Try to get from href
                    href = await button.get_attribute("href")
                    if href and "/campsites/" in href:
                        site_id = href.split("/campsites/")[-1].split("/")[0]
                
                if site_id and site_id not in available:
                    available.append(site_id)
            
            logger.info(f"Found {len(available)} available sites")
            
        except Exception as e:
            logger.error(f"Error finding available sites: {e}")
        
        return available
    
    async def add_to_cart(
        self,
        campsite_id: str,
        arrival: date,
        departure: date
    ) -> bool:
        """
        Add a campsite to cart.
        
        campsite_id can be either:
        - A site name like "06", "A001", etc.
        - An internal Recreation.gov campsite ID
        
        Returns True if successful.
        """
        logger.info(f"Adding campsite {campsite_id} to cart for {arrival} to {departure}...")
        
        try:
            # Strategy 1: Find and click on a link to the site detail page
            # On availability pages, site names are often links
            site_link_selectors = [
                f'a:has-text("Site {campsite_id}")',
                f'a:has-text("{campsite_id}")',
                f'a[href*="campsites"]:has-text("{campsite_id}")',
            ]
            
            site_link = None
            for selector in site_link_selectors:
                try:
                    site_link = await self.page.query_selector(selector)
                    if site_link:
                        href = await site_link.get_attribute("href")
                        if href and "campsites" in href:
                            logger.info(f"Found site link: {href}")
                            # Navigate to the campsite detail page
                            await site_link.click()
                            await self.page.wait_for_load_state("domcontentloaded")
                            await asyncio.sleep(2)
                            break
                except:
                    continue
            
            # Now we should be on the campsite detail page
            # Set the dates using the date picker
            arrival_str = arrival.strftime("%m/%d/%Y")
            departure_str = departure.strftime("%m/%d/%Y")
            logger.info(f"Setting dates: {arrival_str} to {departure_str}")
            
            # First, try to click on the date picker to open it
            date_picker_triggers = [
                'button[aria-label*="date"]',
                'button[class*="date"]',
                '[data-component="DateRange"]',
                '.sarsa-date-picker-trigger',
                'input[placeholder*="Date"]',
                '.date-picker-trigger',
            ]
            
            for trigger in date_picker_triggers:
                try:
                    picker = await self.page.query_selector(trigger)
                    if picker and await picker.is_visible():
                        logger.info(f"Clicking date picker trigger: {trigger}")
                        await picker.click()
                        await asyncio.sleep(1)
                        break
                except:
                    continue
            
            # Try to find and fill date inputs
            date_input_selectors = [
                ('input[id*="start-date"]', 'input[id*="end-date"]'),
                ('input[id*="arrival"]', 'input[id*="departure"]'),
                ('input[name*="start"]', 'input[name*="end"]'),
                ('input[placeholder*="Start"]', 'input[placeholder*="End"]'),
                ('input[aria-label*="arrival"]', 'input[aria-label*="departure"]'),
                ('input[aria-label*="Start"]', 'input[aria-label*="End"]'),
            ]
            
            dates_set = False
            for start_sel, end_sel in date_input_selectors:
                try:
                    start_input = await self.page.query_selector(start_sel)
                    end_input = await self.page.query_selector(end_sel)
                    if start_input and end_input:
                        logger.info(f"Found date inputs: {start_sel}, {end_sel}")
                        # Clear and fill start date
                        await start_input.click()
                        await asyncio.sleep(0.3)
                        await start_input.fill("")
                        await start_input.type(arrival_str, delay=50)
                        await asyncio.sleep(0.5)
                        
                        # Clear and fill end date
                        await end_input.click()
                        await asyncio.sleep(0.3)
                        await end_input.fill("")
                        await end_input.type(departure_str, delay=50)
                        await asyncio.sleep(0.5)
                        
                        # Press Enter or Tab to confirm
                        await self.page.keyboard.press("Tab")
                        await asyncio.sleep(1)
                        dates_set = True
                        break
                except Exception as e:
                    logger.debug(f"Date input error with {start_sel}: {e}")
                    continue
            
            # If we couldn't fill inputs, try clicking on calendar dates directly
            if not dates_set:
                logger.info("Trying to click calendar dates directly")
                # Look for the arrival date in the calendar
                arrival_day = arrival.day
                arrival_month = arrival.strftime("%B")
                
                # Try to find the date in a calendar view
                date_cell_selectors = [
                    f'button[aria-label*="{arrival_month}"][aria-label*="{arrival_day}"]',
                    f'td[aria-label*="{arrival_day}"]',
                    f'button:has-text("{arrival_day}")',
                ]
                
                for selector in date_cell_selectors:
                    try:
                        cells = await self.page.query_selector_all(selector)
                        if cells:
                            await cells[0].click()
                            await asyncio.sleep(0.5)
                            dates_set = True
                            break
                    except:
                        continue
            
            # Wait for availability to update after date selection
            await asyncio.sleep(2)
            
            # Look for "Add to Cart" or "Book" button
            add_button_selectors = [
                'button:has-text("Add to Cart")',
                'button:has-text("Book Now")',
                'button:has-text("Book")',
                'button:has-text("Reserve")',
                'a:has-text("Add to Cart")',
                'a:has-text("Book")',
            ]
            
            add_button = None
            for selector in add_button_selectors:
                try:
                    add_button = await self.page.query_selector(selector)
                    if add_button and await add_button.is_visible():
                        logger.info(f"Found add button with selector: {selector}")
                        break
                    add_button = None
                except:
                    continue
            
            if not add_button:
                logger.warning("Add to Cart button not found")
                # Take a screenshot for debugging
                try:
                    await self.page.screenshot(path="debug_screenshot.png")
                    logger.info("Saved debug screenshot to debug_screenshot.png")
                except:
                    pass
                return False
            
            # Check if button is enabled - wait a bit for it to become enabled
            for _ in range(10):
                is_disabled = await add_button.get_attribute("disabled")
                if not is_disabled:
                    break
                await asyncio.sleep(0.5)
            
            if is_disabled:
                logger.warning("Add to Cart button is disabled - dates may not be available")
                return False
            
            # Click the button
            await add_button.click()
            
            # Wait for response
            await asyncio.sleep(2)
            
            # Check for CAPTCHA
            if await self._check_captcha():
                await self._handle_captcha()
            
            # Check if item was added (look for cart indicator or success message)
            success_indicators = [
                '.cart-count:not(:empty)',
                'text="Added to Cart"',
                'text="Item added"',
            ]
            
            for selector in success_indicators:
                try:
                    element = await self.page.wait_for_selector(selector, timeout=5000)
                    if element:
                        logger.info("Successfully added to cart!")
                        return True
                except:
                    continue
            
            # Check for error message
            error = await self.page.query_selector('.error-message, .alert-danger')
            if error:
                error_text = await error.text_content()
                logger.warning(f"Add to cart failed: {error_text}")
                return False
            
            # Assume success if no error
            return True
            
        except PlaywrightTimeout:
            logger.error("Add to cart timed out")
            return False
        except Exception as e:
            logger.error(f"Add to cart error: {e}")
            return False
    
    async def navigate_to_cart(self):
        """Navigate to the shopping cart"""
        await self.page.goto(WebPages.cart())
        await self.page.wait_for_load_state("domcontentloaded")
        # Wait for cart content
        await asyncio.sleep(1)
    
    async def get_cart_expiry(self) -> Optional[int]:
        """
        Get seconds until cart expires.
        
        Returns None if no cart timer found.
        """
        try:
            timer = await self.page.query_selector('.cart-timer, [data-component="CartTimer"]')
            if timer:
                text = await timer.text_content()
                # Parse timer text (e.g., "14:32" or "14 minutes")
                if ":" in text:
                    parts = text.split(":")
                    return int(parts[0]) * 60 + int(parts[1])
                # Try to extract minutes
                import re
                match = re.search(r'(\d+)\s*min', text)
                if match:
                    return int(match.group(1)) * 60
        except:
            pass
        return None
    
    # ========================================
    # Main Reservation Flow
    # ========================================
    
    async def attempt_reservation(
        self,
        target: ReservationTarget,
        retry_strategy: Optional[RetryStrategy] = None
    ) -> ReservationAttempt:
        """
        Main reservation flow.
        
        1. Login (if needed)
        2. Navigate to campground
        3. Try to add preferred sites to cart
        4. Notify user of success/failure
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
        
        try:
            # Ensure we're logged in
            if not await self._is_logged_in():
                if not await self.login():
                    attempt.mark_failed("Login failed")
                    return attempt
            
            # Build list of sites to try
            sites_to_try = list(target.campsite_ids) if target.campsite_ids else []
            
            # If no specific sites or using fallbacks, find available ones
            if not sites_to_try or self.config.retry.use_fallback_sites:
                available = await self.find_available_sites(
                    target.campground_id,
                    target.arrival_date,
                    target.departure_date
                )
                for site_id in available:
                    if site_id not in sites_to_try:
                        sites_to_try.append(site_id)
            
            if not sites_to_try:
                attempt.mark_failed("No available sites found")
                return attempt
            
            logger.info(f"Will try {len(sites_to_try)} sites: {sites_to_try[:5]}...")
            
            # Try each site with retries
            while retry_strategy.should_retry():
                retry_strategy.record_attempt()
                attempt.attempts_made = retry_strategy.attempts
                
                for site_id in sites_to_try:
                    try:
                        success = await self.add_to_cart(
                            site_id,
                            target.arrival_date,
                            target.departure_date
                        )
                        
                        if success:
                            # Save session
                            await self.session.capture_from_page(self.page, self.context)
                            
                            # Create cart item
                            cart_item = CartItem(
                                reservation_id="browser",
                                campsite=Campsite(
                                    id=site_id,
                                    campground_id=target.campground_id,
                                    name=site_id
                                ),
                                arrival_date=target.arrival_date,
                                departure_date=target.departure_date,
                                subtotal=0,
                                fees=0,
                                total=0,
                                expires_at=datetime.now() + __import__('datetime').timedelta(minutes=15)
                            )
                            
                            attempt.mark_success(cart_item.campsite, cart_item)
                            
                            if self.on_success:
                                await self.on_success(attempt)
                            
                            return attempt
                            
                    except Exception as e:
                        logger.error(f"Error trying site {site_id}: {e}")
                
                # Wait before retry
                if retry_strategy.should_retry():
                    await asyncio.sleep(retry_strategy.base_delay_ms / 1000)
            
            attempt.mark_failed(f"Failed after {attempt.attempts_made} attempts")
            
        except Exception as e:
            attempt.mark_failed(str(e))
            logger.error(f"Reservation attempt error: {e}")
        
        return attempt
    
    async def run_scheduled(self, target: ReservationTarget) -> ReservationAttempt:
        """
        Run reservation at scheduled time.
        
        Waits for the configured window opening time, then attempts reservation.
        """
        window_time = self.config.schedule.window_datetime
        prep_time = self.config.schedule.prep_datetime
        
        logger.info(f"Scheduled for {window_time}")
        logger.info(f"Preparation starts at {prep_time}")
        
        # Wait until prep time
        await self.scheduler.wait_until(prep_time)
        
        # Prepare: login and navigate
        logger.info("Starting preparation...")
        await self.notifications.notify_starting(
            ReservationAttempt(target=target, status=ReservationStatus.SCHEDULED)
        )
        
        if not await self._is_logged_in():
            if not await self.login():
                raise RuntimeError("Login failed during preparation")
        
        # Navigate to campground
        await self.navigate_to_campground(target.campground_id)
        
        # Refresh session periodically while waiting
        refresh_task = asyncio.create_task(self._refresh_session_loop())
        
        try:
            # Wait until window opens
            logger.info(f"Waiting for window to open at {window_time}...")
            await self.scheduler.wait_until(
                window_time,
                early_ms=self.config.schedule.early_start_ms
            )
            
            # GO!
            logger.info("🚀 GO TIME!")
            attempt = await self.attempt_reservation(target)
            
            # Notify
            if attempt.status == ReservationStatus.IN_CART:
                await self.notifications.notify_success(attempt)
            else:
                await self.notifications.notify_failure(attempt)
            
            return attempt
            
        finally:
            refresh_task.cancel()
    
    async def _refresh_session_loop(self):
        """Periodically refresh the page to keep session alive"""
        try:
            while True:
                await asyncio.sleep(60)  # Every minute
                try:
                    await self.page.reload()
                    await self.session.capture_from_page(self.page, self.context)
                except:
                    pass
        except asyncio.CancelledError:
            pass
    
    # ========================================
    # Handoff
    # ========================================
    
    async def handoff_to_user(self) -> str:
        """
        Hand off the session to the user for checkout.
        
        Returns instructions for the user.
        """
        method = self.config.browser.handoff_method
        
        if method == "url":
            # Navigate to cart and provide URL
            await self.navigate_to_cart()
            url = self.page.url
            data = {"url": url}
            
        elif method == "cookies":
            # Export cookies
            export = await SessionHandoff.generate_cookie_export(self.session)
            
            # Save to file
            cookie_file = Path("cookies.json")
            with open(cookie_file, 'w') as f:
                import json
                json.dump(export["cookies"], f, indent=2, default=str)
            
            data = {"file": str(cookie_file)}
            
        elif method == "remote":
            # Keep browser open
            data = {"url": "Browser window is open"}
            
        else:
            data = {"url": WebPages.cart()}
        
        instructions = SessionHandoff.generate_handoff_instructions(method, data)
        print(instructions)
        
        # If not headless, always wait for user to complete checkout
        if not self.config.browser.headless:
            print("\n" + "=" * 60)
            print("🛒 Browser is open for you to complete checkout!")
            print("Press Ctrl+C when done...")
            print("=" * 60 + "\n")
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                print("\nCheckout session ended.")
        
        return instructions


# CLI entry point
async def main():
    import click
    from rich.console import Console
    
    console = Console()
    
    @click.group()
    def cli():
        """Recreation.gov Browser Bot"""
        pass
    
    @cli.command()
    @click.option("--config", "-c", default="config/config.yaml", help="Config file path")
    def test(config):
        """Test login and navigation"""
        async def run():
            cfg = Config.from_yaml(config)
            async with RecGovBrowserBot(cfg) as bot:
                console.print("Testing login...")
                if await bot.login():
                    console.print("[green]Login successful![/green]")
                    
                    console.print(f"Navigating to campground {cfg.target.campground_id}...")
                    await bot.navigate_to_campground(cfg.target.campground_id)
                    console.print("[green]Navigation successful![/green]")
                    
                    console.print("Finding available sites...")
                    sites = await bot.find_available_sites(
                        cfg.target.campground_id,
                        cfg.target.arrival.date(),
                        cfg.target.departure.date()
                    )
                    console.print(f"Found {len(sites)} available sites")
                else:
                    console.print("[red]Login failed![/red]")
        
        asyncio.run(run())
    
    @cli.command()
    @click.option("--config", "-c", default="config/config.yaml", help="Config file path")
    def now(config):
        """Attempt reservation immediately"""
        async def run():
            cfg = Config.from_yaml(config)
            async with RecGovBrowserBot(cfg) as bot:
                target = ReservationTarget(
                    campground_id=cfg.target.campground_id,
                    campsite_ids=cfg.target.campsite_ids,
                    arrival_date=cfg.target.arrival.date(),
                    departure_date=cfg.target.departure.date()
                )
                
                result = await bot.attempt_reservation(target)
                
                if result.status == ReservationStatus.IN_CART:
                    console.print("[bold green]SUCCESS![/bold green]")
                    await bot.handoff_to_user()
                else:
                    console.print(f"[red]Failed: {result.error_message}[/red]")
        
        asyncio.run(run())
    
    @cli.command()
    @click.option("--config", "-c", default="config/config.yaml", help="Config file path")
    def schedule(config):
        """Run at scheduled time"""
        async def run():
            cfg = Config.from_yaml(config)
            
            console.print(f"Scheduled for: {cfg.schedule.window_datetime}")
            console.print("Press Ctrl+C to cancel\n")
            
            async with RecGovBrowserBot(cfg) as bot:
                target = ReservationTarget(
                    campground_id=cfg.target.campground_id,
                    campsite_ids=cfg.target.campsite_ids,
                    arrival_date=cfg.target.arrival.date(),
                    departure_date=cfg.target.departure.date()
                )
                
                result = await bot.run_scheduled(target)
                
                if result.status == ReservationStatus.IN_CART:
                    await bot.handoff_to_user()
        
        asyncio.run(run())
    
    cli()


if __name__ == "__main__":
    asyncio.run(main())
