"""
Configuration management for Recreation.gov bot
"""
import os
import yaml
from pathlib import Path
from datetime import datetime
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, field_validator
from dateutil import parser as date_parser
import pytz


class CredentialsConfig(BaseModel):
    email: str
    password: str


class TargetConfig(BaseModel):
    campground_id: str
    campsite_ids: List[str] = Field(default_factory=list)
    arrival_date: str
    departure_date: str
    num_people: int = 2
    equipment: Optional[str] = None
    
    @property
    def arrival(self) -> datetime:
        return date_parser.parse(self.arrival_date)
    
    @property
    def departure(self) -> datetime:
        return date_parser.parse(self.departure_date)


class ScheduleConfig(BaseModel):
    window_opens: str
    timezone: str = "America/Los_Angeles"
    prep_time: int = 300
    early_start_ms: int = -100
    
    @property
    def window_datetime(self) -> datetime:
        tz = pytz.timezone(self.timezone)
        dt = date_parser.parse(self.window_opens)
        if dt.tzinfo is None:
            dt = tz.localize(dt)
        return dt
    
    @property
    def prep_datetime(self) -> datetime:
        from datetime import timedelta
        return self.window_datetime - timedelta(seconds=self.prep_time)


class EmailConfig(BaseModel):
    enabled: bool = False
    address: Optional[str] = None
    sendgrid_api_key: Optional[str] = None


class SMSConfig(BaseModel):
    enabled: bool = False
    phone: Optional[str] = None
    twilio_account_sid: Optional[str] = None
    twilio_auth_token: Optional[str] = None
    twilio_from_number: Optional[str] = None


class WebhookConfig(BaseModel):
    enabled: bool = False
    url: Optional[str] = None


class NotificationsConfig(BaseModel):
    email: EmailConfig = Field(default_factory=EmailConfig)
    sms: SMSConfig = Field(default_factory=SMSConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)


class BrowserConfig(BaseModel):
    headless: bool = False
    slow_mo: int = 50
    user_agent: str = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    save_session: bool = True
    session_file: str = "session.json"
    handoff_method: str = "url"
    remote_debugging_port: Optional[int] = None


class APIConfig(BaseModel):
    base_url: str = "https://www.recreation.gov"
    timeout: int = 10
    max_retries: int = 3
    retry_delay: float = 0.5
    requests_per_second: int = 2
    headers: Dict[str, str] = Field(default_factory=lambda: {
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Origin": "https://www.recreation.gov",
        "Referer": "https://www.recreation.gov/"
    })


class RetryConfig(BaseModel):
    max_attempts: int = 10
    attempt_delay_ms: int = 100
    use_fallback_sites: bool = True
    stop_on_success: bool = True


class LoggingConfig(BaseModel):
    level: str = "INFO"
    file: str = "recgov-bot.log"


class AdvancedConfig(BaseModel):
    captcha_handling: str = "pause"
    captcha_api_key: Optional[str] = None
    proxy: Optional[str] = None


class Config(BaseModel):
    """Main configuration class"""
    credentials: CredentialsConfig
    target: TargetConfig
    schedule: ScheduleConfig = Field(default_factory=lambda: ScheduleConfig(
        window_opens="2025-01-01 07:00:00"
    ))
    notifications: NotificationsConfig = Field(default_factory=NotificationsConfig)
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    api: APIConfig = Field(default_factory=APIConfig)
    retry: RetryConfig = Field(default_factory=RetryConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    advanced: AdvancedConfig = Field(default_factory=AdvancedConfig)
    
    @classmethod
    def from_yaml(cls, path: str | Path) -> "Config":
        """Load configuration from YAML file"""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Config file not found: {path}")
        
        with open(path) as f:
            data = yaml.safe_load(f)
        
        return cls(**data)
    
    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables"""
        return cls(
            credentials=CredentialsConfig(
                email=os.environ["RECGOV_EMAIL"],
                password=os.environ["RECGOV_PASSWORD"]
            ),
            target=TargetConfig(
                campground_id=os.environ["RECGOV_CAMPGROUND_ID"],
                campsite_ids=os.environ.get("RECGOV_CAMPSITE_IDS", "").split(","),
                arrival_date=os.environ["RECGOV_ARRIVAL_DATE"],
                departure_date=os.environ["RECGOV_DEPARTURE_DATE"],
            ),
            schedule=ScheduleConfig(
                window_opens=os.environ.get("RECGOV_WINDOW_OPENS", "2025-01-01 07:00:00"),
            )
        )
    
    def to_yaml(self, path: str | Path):
        """Save configuration to YAML file"""
        path = Path(path)
        with open(path, 'w') as f:
            yaml.dump(self.model_dump(), f, default_flow_style=False)


def load_config(path: Optional[str] = None) -> Config:
    """Load configuration from file or environment"""
    if path:
        return Config.from_yaml(path)
    
    # Try default locations
    default_paths = [
        Path("config/config.yaml"),
        Path("config.yaml"),
        Path.home() / ".recgov" / "config.yaml",
    ]
    
    for p in default_paths:
        if p.exists():
            return Config.from_yaml(p)
    
    # Fall back to environment variables
    try:
        return Config.from_env()
    except KeyError as e:
        raise RuntimeError(
            f"No config file found and missing environment variable: {e}. "
            f"Create config/config.yaml or set RECGOV_* environment variables."
        )
