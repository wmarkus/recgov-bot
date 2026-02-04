#!/usr/bin/env python3
"""
Recreation.gov Campsite Sniper Bot - Main Entry Point

Usage:
    python main.py browser --config config/config.yaml [--test|--now|--schedule]
    python main.py legacy-api --config config/config.yaml [--check|--reserve]
"""
import asyncio
import logging
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.logging import RichHandler
from rich.panel import Panel
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn

from src.common.config import load_config, Config
from src.common.models import ReservationTarget, ReservationStatus
from src.common.scheduler import PrecisionScheduler

console = Console()


def setup_logging(level: str = "INFO", log_file: str = None):
    """Configure logging"""
    handlers = [RichHandler(console=console, rich_tracebacks=True)]
    
    if log_file:
        handlers.append(logging.FileHandler(log_file))
    
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(message)s",
        handlers=handlers
    )


@click.group()
@click.option("--config", "-c", default="config/config.yaml", help="Path to config file")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx, config, verbose):
    """
    Recreation.gov Campsite Sniper Bot
    
    Automatically reserve campsites when they become available.
    """
    ctx.ensure_object(dict)
    
    try:
        cfg = load_config(config)
        ctx.obj["config"] = cfg
        setup_logging(
            level="DEBUG" if verbose else cfg.logging.level,
            log_file=cfg.logging.file
        )
    except FileNotFoundError:
        console.print(f"[red]Config file not found: {config}[/red]")
        console.print("Create a config file from config/config.example.yaml")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error loading config: {e}[/red]")
        sys.exit(1)


@cli.group()
def browser():
    """Browser automation mode (Playwright)"""
    pass


@browser.command("test")
@click.pass_context
def browser_test(ctx):
    """Test browser login and navigation"""
    from src.browser import RecGovBrowserBot
    
    cfg = ctx.obj["config"]
    
    async def run():
        console.print(Panel("🧪 Testing Browser Automation", style="blue"))
        
        async with RecGovBrowserBot(cfg) as bot:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console
            ) as progress:
                
                task = progress.add_task("Logging in...", total=None)
                if await bot.login():
                    progress.update(task, description="[green]✓ Login successful[/green]")
                else:
                    progress.update(task, description="[red]✗ Login failed[/red]")
                    return
                
                task = progress.add_task("Navigating to campground...", total=None)
                await bot.navigate_to_campground(cfg.target.campground_id)
                progress.update(task, description="[green]✓ Navigation successful[/green]")
                
                task = progress.add_task("Finding available sites...", total=None)
                sites = await bot.find_available_sites(
                    cfg.target.campground_id,
                    cfg.target.arrival.date(),
                    cfg.target.departure.date()
                )
                progress.update(task, description=f"[green]✓ Found {len(sites)} available sites[/green]")
        
        if sites:
            table = Table(title="Available Campsites")
            table.add_column("Site ID")
            for site in sites[:10]:
                table.add_row(site)
            if len(sites) > 10:
                table.add_row(f"... and {len(sites) - 10} more")
            console.print(table)
    
    asyncio.run(run())


@browser.command("now")
@click.pass_context
def browser_now(ctx):
    """Attempt reservation immediately"""
    from src.browser import RecGovBrowserBot
    
    cfg = ctx.obj["config"]
    
    async def run():
        console.print(Panel("🚀 Attempting Reservation Now", style="green"))
        
        target = ReservationTarget(
            campground_id=cfg.target.campground_id,
            campsite_ids=cfg.target.campsite_ids,
            arrival_date=cfg.target.arrival.date(),
            departure_date=cfg.target.departure.date()
        )
        
        async with RecGovBrowserBot(cfg) as bot:
            result = await bot.attempt_reservation(target)
            
            if result.status == ReservationStatus.IN_CART:
                console.print(Panel(
                    f"[bold green]🎉 SUCCESS![/bold green]\n\n"
                    f"Site: {result.campsite_secured.name if result.campsite_secured else 'Unknown'}\n"
                    f"Complete checkout within 15 minutes!",
                    style="green"
                ))
                await bot.handoff_to_user()
            else:
                console.print(Panel(
                    f"[bold red]❌ Failed[/bold red]\n\n{result.error_message}",
                    style="red"
                ))
    
    asyncio.run(run())


@browser.command("quick")
@click.pass_context
def browser_quick(ctx):
    """Interactive reservation - prompts for campground, site, and dates"""
    from src.browser import RecGovBrowserBot
    from datetime import date
    
    cfg = ctx.obj["config"]
    
    console.print(Panel(
        "🏕️  Quick Reservation Setup\n\n"
        "Enter your reservation details below.\n"
        "Tip: Find campground IDs from recreation.gov URLs\n"
        "Example: recreation.gov/camping/campgrounds/[bold]234501[/bold]",
        style="blue"
    ))
    
    # Prompt for campground ID
    campground_id = click.prompt(
        "\n📍 Campground ID",
        default=cfg.target.campground_id if cfg.target.campground_id else None,
        type=str
    )
    
    # Prompt for site number
    default_site = cfg.target.campsite_ids[0] if cfg.target.campsite_ids else None
    site_number = click.prompt(
        "🏕️  Site number (e.g., 06, A001)",
        default=default_site,
        type=str
    )
    
    # Prompt for arrival date
    console.print("\n[dim]Date format: YYYY-MM-DD (e.g., 2026-05-26)[/dim]")
    
    def parse_date(value):
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError:
            raise click.BadParameter(f"Invalid date format: {value}. Use YYYY-MM-DD")
    
    arrival_str = click.prompt(
        "📅 Arrival date",
        default=cfg.target.arrival.strftime("%Y-%m-%d") if cfg.target.arrival else None,
        type=str
    )
    arrival_date = parse_date(arrival_str)
    
    departure_str = click.prompt(
        "📅 Departure date",
        default=cfg.target.departure.strftime("%Y-%m-%d") if cfg.target.departure else None,
        type=str
    )
    departure_date = parse_date(departure_str)
    
    # Validate dates
    if departure_date <= arrival_date:
        console.print("[red]Error: Departure date must be after arrival date[/red]")
        return
    
    nights = (departure_date - arrival_date).days
    
    # Confirm
    console.print()
    table = Table(title="Reservation Details", show_header=False)
    table.add_column("Field", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("Campground ID", campground_id)
    table.add_row("Site", site_number)
    table.add_row("Arrival", arrival_str)
    table.add_row("Departure", departure_str)
    table.add_row("Nights", str(nights))
    console.print(table)
    
    if not click.confirm("\n🚀 Start reservation attempt?", default=True):
        console.print("[yellow]Cancelled[/yellow]")
        return
    
    # Run the reservation
    async def run():
        console.print(Panel("🚀 Attempting Reservation", style="green"))
        
        target = ReservationTarget(
            campground_id=campground_id,
            campsite_ids=[site_number],
            arrival_date=arrival_date,
            departure_date=departure_date
        )
        
        async with RecGovBrowserBot(cfg) as bot:
            result = await bot.attempt_reservation(target)
            
            if result.status == ReservationStatus.IN_CART:
                console.print(Panel(
                    f"[bold green]🎉 SUCCESS![/bold green]\n\n"
                    f"Site: {result.campsite_secured.name if result.campsite_secured else site_number}\n"
                    f"Dates: {arrival_str} to {departure_str} ({nights} nights)\n"
                    f"Complete checkout within 15 minutes!",
                    style="green"
                ))
                await bot.handoff_to_user()
            else:
                console.print(Panel(
                    f"[bold red]❌ Failed[/bold red]\n\n{result.error_message}",
                    style="red"
                ))
    
    asyncio.run(run())


@browser.command("snipe")
@click.pass_context
def browser_snipe(ctx):
    """Pre-stage everything, then strike at window open time"""
    from src.browser import RecGovBrowserBot
    import time
    
    cfg = ctx.obj["config"]
    scheduler = PrecisionScheduler(cfg.schedule.timezone)
    
    async def run():
        window_time = cfg.schedule.window_datetime
        target = ReservationTarget(
            campground_id=cfg.target.campground_id,
            campsite_ids=cfg.target.campsite_ids,
            arrival_date=cfg.target.arrival.date(),
            departure_date=cfg.target.departure.date()
        )
        
        console.print(Panel(
            f"🎯 SNIPE MODE\n\n"
            f"Campground: {target.campground_id}\n"
            f"Site: {target.campsite_ids[0] if target.campsite_ids else 'Any'}\n"
            f"Dates: {target.arrival_date} to {target.departure_date}\n"
            f"Window: {window_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n\n"
            f"Strategy:\n"
            f"1. Login & navigate now\n"
            f"2. Pre-select dates\n"
            f"3. Wait for window\n"
            f"4. STRIKE at {window_time.strftime('%H:%M:%S')}",
            style="red"
        ))
        
        async with RecGovBrowserBot(cfg) as bot:
            # Phase 1: Login
            console.print("\n[bold cyan]Phase 1: Login[/bold cyan]")
            if not await bot._is_logged_in():
                if not await bot.login():
                    console.print("[red]Login failed![/red]")
                    return
            console.print("[green]✓ Logged in[/green]")
            
            # Phase 2: Navigate to availability page
            console.print("\n[bold cyan]Phase 2: Navigate to campground[/bold cyan]")
            await bot.navigate_to_availability(
                target.campground_id,
                target.arrival_date,
                target.departure_date
            )
            console.print(f"[green]✓ On availability page[/green]")
            
            # Phase 3: Set dates in the date picker
            console.print("\n[bold cyan]Phase 3: Pre-set dates[/bold cyan]")
            arrival_str = target.arrival_date.strftime("%m/%d/%Y")
            departure_str = target.departure_date.strftime("%m/%d/%Y")
            
            date_inputs = await bot.page.query_selector_all('input[placeholder*="mm/dd/yyyy"]')
            if len(date_inputs) >= 2:
                await date_inputs[0].click(click_count=3)
                await bot.page.keyboard.type(arrival_str, delay=30)
                await date_inputs[1].click(click_count=3)
                await bot.page.keyboard.type(departure_str, delay=30)
                await bot.page.keyboard.press("Enter")
                await asyncio.sleep(2)
                console.print(f"[green]✓ Dates set: {arrival_str} - {departure_str}[/green]")
            else:
                console.print("[yellow]⚠ Could not pre-set dates[/yellow]")
            
            # Phase 4: Find the site row
            console.print("\n[bold cyan]Phase 4: Locate site row[/bold cyan]")
            site_id = target.campsite_ids[0] if target.campsite_ids else None
            site_row = None
            if site_id:
                site_row = await bot.page.query_selector(f'tr:has(a:has-text("{site_id}"))')
                if site_row:
                    console.print(f"[green]✓ Found site {site_id}[/green]")
                else:
                    console.print(f"[yellow]⚠ Site {site_id} row not found yet[/yellow]")
            
            # Phase 5: Wait for window with countdown
            console.print("\n[bold cyan]Phase 5: Waiting for window...[/bold cyan]")
            console.print("[dim]Press Ctrl+C to abort[/dim]\n")
            
            while True:
                now = datetime.now(window_time.tzinfo)
                remaining = (window_time - now).total_seconds()
                
                if remaining <= 0:
                    break
                
                if remaining > 60:
                    console.print(f"\r⏳ T-{int(remaining)}s    ", end="")
                    await asyncio.sleep(1)
                elif remaining > 10:
                    console.print(f"\r⏳ T-{remaining:.1f}s   ", end="")
                    await asyncio.sleep(0.1)
                else:
                    # Final countdown - poll rapidly
                    console.print(f"\r🔥 T-{remaining:.3f}s ", end="")
                    await asyncio.sleep(0.01)
            
            # Phase 6: STRIKE!
            console.print("\n\n[bold red]🚀 GO GO GO![/bold red]")
            
            # Re-find site row (page may have updated)
            if site_id:
                site_row = await bot.page.query_selector(f'tr:has(a:has-text("{site_id}"))')
            
            if site_row:
                # Click all available "A" cells rapidly
                available_cells = await site_row.query_selector_all('button:has-text("A"), a:has-text("A")')
                num_nights = (target.departure_date - target.arrival_date).days
                
                console.print(f"[yellow]Clicking {min(len(available_cells), num_nights)} date cells...[/yellow]")
                
                clicked = 0
                for cell in available_cells:
                    if clicked >= num_nights:
                        break
                    try:
                        await cell.click()
                        clicked += 1
                    except:
                        pass
                
                await asyncio.sleep(0.5)
            
            # Click Add to Cart
            console.print("[yellow]Clicking Add to Cart...[/yellow]")
            add_btn = await bot.page.query_selector('button:has-text("Add to Cart")')
            if add_btn:
                await add_btn.click()
                console.print("[green]✓ Clicked Add to Cart![/green]")
            
            # Phase 7: CAPTCHA handling
            console.print("\n[bold magenta]⚠️  SOLVE CAPTCHA NOW IF IT APPEARS![/bold magenta]")
            console.print("[dim]Bot will wait for you...[/dim]\n")
            
            # Wait for CAPTCHA to be solved (check for cart success)
            for i in range(120):  # Wait up to 2 minutes
                # Check if we made it to cart
                cart_success = await bot.page.query_selector('text="Added to Cart", text="View Cart", text="Checkout"')
                if cart_success:
                    console.print(Panel(
                        "[bold green]🎉 SUCCESS! Item in cart![/bold green]\n\n"
                        "Complete checkout NOW - you have 15 minutes!",
                        style="green"
                    ))
                    break
                
                # Check if still on CAPTCHA
                captcha = await bot.page.query_selector('iframe[src*="recaptcha"]')
                if captcha and i % 10 == 0:
                    console.print("[yellow]Waiting for CAPTCHA solve...[/yellow]")
                
                await asyncio.sleep(1)
            
            # Keep browser open
            console.print("\n[cyan]Browser staying open for checkout. Press Ctrl+C when done.[/cyan]")
            try:
                while True:
                    await asyncio.sleep(1)
            except KeyboardInterrupt:
                pass
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Aborted[/yellow]")


@browser.command("schedule")
@click.pass_context
def browser_schedule(ctx):
    """Run at scheduled time"""
    from src.browser import RecGovBrowserBot
    
    cfg = ctx.obj["config"]
    scheduler = PrecisionScheduler(cfg.schedule.timezone)
    
    async def run():
        window_time = cfg.schedule.window_datetime
        countdown = scheduler.format_countdown(window_time)
        
        console.print(Panel(
            f"⏰ Scheduled Reservation\n\n"
            f"Window opens: {window_time.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
            f"Countdown: {countdown}\n\n"
            f"Press Ctrl+C to cancel",
            style="blue"
        ))
        
        target = ReservationTarget(
            campground_id=cfg.target.campground_id,
            campsite_ids=cfg.target.campsite_ids,
            arrival_date=cfg.target.arrival.date(),
            departure_date=cfg.target.departure.date()
        )
        
        async with RecGovBrowserBot(cfg) as bot:
            result = await bot.run_scheduled(target)
            
            if result.status == ReservationStatus.IN_CART:
                await bot.handoff_to_user()
    
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        console.print("\n[yellow]Cancelled[/yellow]")


@cli.group("legacy-api")
def legacy_api():
    """Legacy direct API mode (not recommended)"""
    console.print(Panel(
        "⚠️ Legacy API mode is deprecated and may break without notice.\n"
        "Use browser mode for the supported flow.",
        style="yellow"
    ))


@legacy_api.command("check")
@click.pass_context
def api_check(ctx):
    """Check campsite availability via API"""
    from src.legacy.api import RecGovAPIClient
    
    cfg = ctx.obj["config"]
    
    async def run():
        console.print(Panel("🔍 Checking Availability via API", style="blue"))
        
        target = ReservationTarget(
            campground_id=cfg.target.campground_id,
            campsite_ids=cfg.target.campsite_ids,
            arrival_date=cfg.target.arrival.date(),
            departure_date=cfg.target.departure.date()
        )
        
        async with RecGovAPIClient(cfg) as client:
            available = await client.find_available_sites(target)
            
            if available:
                table = Table(title=f"Available Sites ({len(available)} total)")
                table.add_column("Site ID")
                table.add_column("Name")
                table.add_column("Loop")
                table.add_column("Max People")
                
                for result in available[:20]:
                    table.add_row(
                        result.campsite.id,
                        result.campsite.name,
                        result.campsite.loop or "-",
                        str(result.campsite.max_people or "-")
                    )
                
                if len(available) > 20:
                    table.add_row("...", f"{len(available) - 20} more", "", "")
                
                console.print(table)
            else:
                console.print("[yellow]No available sites found for the specified dates[/yellow]")
    
    asyncio.run(run())


@legacy_api.command("reserve")
@click.pass_context
def api_reserve(ctx):
    """Attempt reservation via API"""
    from src.legacy.api import RecGovAPIClient
    
    cfg = ctx.obj["config"]
    
    async def run():
        console.print(Panel("🚀 Attempting Reservation via API", style="green"))
        
        async with RecGovAPIClient(cfg) as client:
            # Login first
            if not await client.login():
                console.print("[red]Login failed![/red]")
                return
            
            console.print("[green]✓ Logged in[/green]")
            
            target = ReservationTarget(
                campground_id=cfg.target.campground_id,
                campsite_ids=cfg.target.campsite_ids,
                arrival_date=cfg.target.arrival.date(),
                departure_date=cfg.target.departure.date()
            )
            
            result = await client.attempt_reservation(target)
            
            if result.status == ReservationStatus.IN_CART:
                console.print(Panel(
                    f"[bold green]🎉 SUCCESS![/bold green]\n\n"
                    f"Site: {result.campsite_secured.name if result.campsite_secured else 'Unknown'}\n"
                    f"Checkout URL: {result.checkout_url}\n\n"
                    f"Complete checkout within 15 minutes!",
                    style="green"
                ))
            else:
                console.print(Panel(
                    f"[bold red]❌ Failed[/bold red]\n\n{result.error_message}",
                    style="red"
                ))
    
    asyncio.run(run())


@cli.command()
@click.pass_context
def info(ctx):
    """Show current configuration"""
    cfg = ctx.obj["config"]
    
    console.print(Panel("📋 Current Configuration", style="blue"))
    
    table = Table(show_header=False)
    table.add_column("Setting", style="cyan")
    table.add_column("Value")
    
    table.add_row("Campground ID", cfg.target.campground_id)
    table.add_row("Target Sites", ", ".join(cfg.target.campsite_ids) if cfg.target.campsite_ids else "Any")
    table.add_row("Arrival", cfg.target.arrival_date)
    table.add_row("Departure", cfg.target.departure_date)
    table.add_row("Window Opens", str(cfg.schedule.window_datetime))
    table.add_row("Email", cfg.credentials.email)
    table.add_row("Headless Mode", str(cfg.browser.headless))
    table.add_row("Max Attempts", str(cfg.retry.max_attempts))
    
    console.print(table)


if __name__ == "__main__":
    cli()
