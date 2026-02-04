# AGENTS.md

This file provides guidance to AI coding assistants when working with code in this repository.

## Project Overview

A Recreation.gov campsite reservation bot with two approaches:
- **Browser automation** (`src/browser/`): Playwright-based, slower but more reliable, handles CAPTCHAs
- **Direct API** (`src/legacy/api/`): Fast (<1s attempts) but fragile, reverse-engineered endpoints (deprecated)

The bot pre-authenticates, waits for reservation windows to open (typically 7:00 AM PT), and attempts to secure campsites with millisecond precision timing.

## Architecture

### Dual Strategy Pattern
- Both browser and legacy API modes share common configuration, models, scheduling, and notification infrastructure
- Browser mode uses Playwright for full browser automation with session handoff
- Legacy API mode uses httpx for direct HTTP requests to reverse-engineered endpoints
- Common layer (`src/common/`) provides configuration management (Pydantic models), data models, precision timing, rate limiting, and notifications

### Key Abstractions
- `ReservationTarget`: Encapsulates what to reserve (campground, sites, dates)
- `ReservationAttempt`: Tracks attempt lifecycle and status
- `PrecisionScheduler`: High-precision timing using progressive sleep strategies (30s -> 1s -> 100ms -> 1ms -> busy-wait)
- `RateLimiter`: Token bucket algorithm for API requests
- `RetryStrategy`: Configurable retry logic with optional exponential backoff
- `BrowserSession`: Manages session persistence and handoff between bot and user

### Critical Flow
1. Pre-auth phase (T-5 min): Login, navigate to campground
2. Polling phase (T-10s): Rapid availability checks
3. Submit phase (T-0): Attempts reservation with configurable early start (default -100ms)
4. Fallback: Tries backup sites if primary unavailable
5. Handoff: User completes checkout within 15-minute cart hold

## Development Commands

### Setup
```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### Running
```bash
# Browser mode (recommended)
python main.py browser test                              # Test login and availability
python main.py browser now                               # Immediate attempt
python main.py browser schedule                          # Wait for window time

# Legacy API mode (deprecated)
python main.py legacy-api check                          # Check availability
python main.py legacy-api reserve                        # Attempt reservation

# View config
python main.py info
```

### Testing
```bash
# Run all tests (237 tests)
pytest tests/ -v

# Run specific test file
pytest tests/test_models.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=html
```

Test organization:
- `tests/conftest.py`: Shared fixtures (config, target)
- `tests/test_config.py`: Configuration loading and validation
- `tests/test_models.py`: Data models and their methods
- `tests/test_scheduler.py`: PrecisionScheduler, RateLimiter, RetryStrategy
- `tests/test_notifications.py`: Notification providers
- `tests/test_session.py`: Browser session management
- `tests/test_auth.py`: API authentication
- `tests/test_endpoints.py`: URL building and endpoints
- `tests/test_api_reservation_flow.py`: API client integration tests
- `tests/test_browser_scheduled_flow.py`: Browser bot integration tests

### Configuration
- Main config: `config/config.yaml` (copy from `config/config.example.yaml`)
- Uses Pydantic models for validation (`src/common/config.py`)
- Supports environment variables as fallback: `RECGOV_EMAIL`, `RECGOV_PASSWORD`, etc.

## Important Constraints

### Recreation.gov API Behavior
- API endpoints in `src/legacy/api/endpoints.py` are reverse-engineered and undocumented
- Endpoints can change without notice; verify by inspecting network traffic in browser DevTools
- Rate limiting is enforced; default 2 req/s is safe
- CAPTCHA can trigger on suspicious activity; browser mode handles with pause for human intervention

### Timing Precision
- Recreation.gov windows often open exactly at HH:MM:00.000
- `PrecisionScheduler` uses progressive strategy: sleep for coarse waits, busy-wait for <10ms
- `early_start_ms` config allows submission before window (negative values); default -100ms
- Browser mode inherently slower (~500ms) than API mode (<100ms) for submission

### Session Management
- Sessions expire after inactivity (typically 1 hour)
- Browser mode can save/restore sessions to `session.json`
- API mode must re-authenticate if session expired
- Cart items expire 15 minutes after being added

### Error Handling
- Browser: Gracefully handles CAPTCHA, session expiration, network errors
- API (legacy): Raises `APIError` with status codes; may need to fall back to browser mode
- Both: Implement retry logic with exponential backoff in `RetryStrategy`

## Code Patterns

### Async/Await Convention
All I/O operations are async. Use:
- `async with RecGovBrowserBot(config) as bot:` for browser automation
- `async with RecGovAPIClient(config) as client:` for legacy API calls
- `await scheduler.wait_until(target_time)` for precision timing
- `async with rate_limiter:` for API rate limiting

### Configuration Access
Always use Pydantic models, never raw dicts:
```python
config = load_config("config/config.yaml")
email = config.credentials.email
arrival = config.target.arrival  # Returns datetime, not string
```

### Model Validation
Data from external sources goes through Pydantic models:
```python
campsite = Campsite(id="123", campground_id="456", name="A001")
availability = CampsiteAvailability.AVAILABLE  # Enum, not string
```

### Logging
Use module-level logger:
```python
logger = logging.getLogger(__name__)
logger.info("Starting reservation attempt")
```

Main CLI configures Rich logging with tracebacks.

## Module Responsibilities

### `src/browser/`
- `bot.py`: Main `RecGovBrowserBot` class, implements full reservation flow
- `session.py`: Session persistence, cookie/storage management, handoff methods
- `urls.py`: URL builders for Recreation.gov pages

### `src/legacy/api/`
- `client.py`: `RecGovAPIClient` for direct HTTP requests (deprecated)
- `endpoints.py`: API endpoint definitions (reverse-engineered)
- `auth.py`: Authentication handling, token management

### `src/common/`
- `config.py`: Pydantic configuration models, YAML/env loading
- `models.py`: Core data models (Campsite, ReservationTarget, etc.)
- `scheduler.py`: Precision timing, rate limiting, retry strategies
- `notifications.py`: Email (SendGrid), SMS (Twilio), webhook support

### Root
- `main.py`: Click-based CLI, entry point for all operations
- `config/config.example.yaml`: Template with all available options

## Credentials and Secrets

- Never commit actual credentials
- Config uses `config/config.yaml` (gitignored)
- Example config is `config/config.example.yaml`
- API keys for SendGrid/Twilio should be in config file or env vars
- Session data in `session.json` contains auth cookies; keep secure
