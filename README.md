# Recreation.gov Campsite Sniper Bot

An automated tool to secure highly competitive campsite reservations on Recreation.gov.

## ⚠️ Disclaimer

This tool is for **personal use only**. Using automated tools may violate Recreation.gov's Terms of Service and could result in account suspension. Use at your own risk.

## Architecture

This project implements **two approaches**:

### 1. Browser Automation (`src/browser/`)
Uses Playwright to automate a real browser session. More reliable but slower.
- Handles JavaScript rendering
- Works with CAPTCHAs (pauses for human intervention)
- Seamless session handoff to user

### 2. Direct API (Legacy, `src/legacy/api/`)
Uses reverse-engineered API endpoints. Faster but more fragile.
- Sub-second reservation attempts
- May break if Recreation.gov changes their API
- Deprecated in favor of browser automation

## Project Structure

```
recgov-bot/
├── src/
│   ├── browser/           # Playwright-based automation
│   │   ├── bot.py         # Main browser bot
│   │   ├── session.py     # Session management
│   │   └── urls.py        # Browser URL helpers
│   ├── legacy/            # Parked legacy modules
│   │   └── api/           # Direct API approach (deprecated)
│   │       ├── client.py  # API client
│   │       ├── endpoints.py # Known API endpoints
│   │       └── auth.py    # Authentication handling
│   └── common/            # Shared utilities
│       ├── config.py      # Configuration management
│       ├── notifications.py # SMS/Email alerts
│       ├── scheduler.py   # Precision timing
│       └── models.py      # Data models
├── config/
│   └── config.yaml        # User configuration
├── tests/
└── requirements.txt
```

## Installation

```bash
# Clone and setup
cd recgov-bot
python -m venv venv
source venv/bin/activate  # or `venv\Scripts\activate` on Windows

# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Configuration

Edit `config/config.yaml`:

```yaml
credentials:
  email: "your-email@example.com"
  password: "your-password"

target:
  campground_id: "232447"  # Upper Pines, Yosemite
  campsite_ids: ["42", "38", "15"]  # Numeric IDs only (priority order)
  arrival_date: "2025-08-15"
  departure_date: "2025-08-17"
  
notifications:
  email: "your-email@example.com"
  # sms: "+1234567890"  # Optional
```

## Usage

### Browser Automation (Recommended)

```bash
# Test run (checks availability only)
python main.py browser test

# Schedule for window opening
python main.py browser schedule

# Run immediately
python main.py browser now
```

### Direct API (Legacy)

```bash
# Check availability via API
python main.py legacy-api check

# Attempt reservation via API
python main.py legacy-api reserve
```

## How It Works

### Reservation Flow

1. **Pre-auth** (T-5 minutes): Bot logs in and navigates to target campground
2. **Polling** (T-10 seconds): Refreshes availability page rapidly
3. **Submit** (T-0): Attempts to add campsite to cart
4. **Fallback**: If primary site unavailable, tries backup sites
5. **Notify**: Sends alert with checkout link
6. **Handoff**: User completes payment within 15-minute hold window

### Finding Campground/Site IDs

1. Go to https://recreation.gov
2. Search for your campground
3. URL will look like: `https://www.recreation.gov/camping/campgrounds/232447`
4. The number at the end (`232447`) is the campground ID
5. For specific campsites, click on one - URL shows `/campsites/12345`
6. Use numeric campsite IDs only in config (names are not resolved)

## API Endpoints (Reverse-Engineered)

These are undocumented and may change:

```
# Availability
GET /api/camps/availability/campground/{id}/month?start_date={ISO_DATE}

# Search
GET /api/search?q={query}&entity_type=campground

# Add to cart (requires auth)
POST /api/ticket/reservation

# Cart contents
GET /api/ticket/cart
```

## Troubleshooting

### "Site no longer available"
- Someone else got it first. Try backup sites.

### CAPTCHA triggered
- Browser mode will pause for you to solve it manually.
- Consider using a CAPTCHA solving service for API mode.

### Session expired
- Increase `session_refresh_interval` in config.

### Rate limited
- Reduce polling frequency. Default is safe.

## Contributing

This is for educational purposes. PRs welcome for:
- Additional notification providers
- Better error handling
- UI improvements

## License

MIT - Use responsibly.
