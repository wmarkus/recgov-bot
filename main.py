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
