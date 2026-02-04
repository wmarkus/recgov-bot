"""
Tests for configuration management (src/common/config.py)
"""
import pytest
import tempfile
import os
from pathlib import Path
from datetime import datetime, timedelta

import pytz

from src.common.config import (
    Config,
    CredentialsConfig,
    TargetConfig,
    ScheduleConfig,
    EmailConfig,
    SMSConfig,
    WebhookConfig,
    NotificationsConfig,
    BrowserConfig,
    APIConfig,
    RetryConfig,
    LoggingConfig,
    AdvancedConfig,
    load_config,
)


class TestCredentialsConfig:
    def test_create_credentials(self):
        creds = CredentialsConfig(email="test@example.com", password="secret123")
        assert creds.email == "test@example.com"
        assert creds.password == "secret123"

    def test_credentials_required_fields(self):
        with pytest.raises(Exception):
            CredentialsConfig(email="test@example.com")


class TestTargetConfig:
    def test_create_target(self):
        target = TargetConfig(
            campground_id="12345",
            arrival_date="2030-08-01",
            departure_date="2030-08-05",
        )
        assert target.campground_id == "12345"
        assert target.campsite_ids == []
        assert target.num_people == 2

    def test_target_with_campsite_ids(self):
        target = TargetConfig(
            campground_id="12345",
            campsite_ids=["A001", "A002", "B001"],
            arrival_date="2030-08-01",
            departure_date="2030-08-05",
        )
        assert target.campsite_ids == ["A001", "A002", "B001"]

    def test_arrival_property(self):
        target = TargetConfig(
            campground_id="12345",
            arrival_date="2030-08-15",
            departure_date="2030-08-17",
        )
        arrival = target.arrival
        assert isinstance(arrival, datetime)
        assert arrival.year == 2030
        assert arrival.month == 8
        assert arrival.day == 15

    def test_departure_property(self):
        target = TargetConfig(
            campground_id="12345",
            arrival_date="2030-08-15",
            departure_date="2030-08-17",
        )
        departure = target.departure
        assert isinstance(departure, datetime)
        assert departure.year == 2030
        assert departure.month == 8
        assert departure.day == 17

    def test_optional_equipment(self):
        target = TargetConfig(
            campground_id="12345",
            arrival_date="2030-08-01",
            departure_date="2030-08-03",
            equipment="Tent",
        )
        assert target.equipment == "Tent"


class TestScheduleConfig:
    def test_create_schedule(self):
        schedule = ScheduleConfig(window_opens="2030-08-01 07:00:00")
        assert schedule.timezone == "America/Los_Angeles"
        assert schedule.prep_time == 300
        assert schedule.early_start_ms == -100

    def test_window_datetime_property(self):
        schedule = ScheduleConfig(
            window_opens="2030-08-01 07:00:00",
            timezone="America/Los_Angeles",
        )
        window_dt = schedule.window_datetime
        assert isinstance(window_dt, datetime)
        assert window_dt.year == 2030
        assert window_dt.month == 8
        assert window_dt.day == 1
        assert window_dt.hour == 7
        assert window_dt.minute == 0
        assert window_dt.tzinfo is not None

    def test_window_datetime_with_utc(self):
        schedule = ScheduleConfig(
            window_opens="2030-08-01 14:00:00",
            timezone="UTC",
        )
        window_dt = schedule.window_datetime
        assert window_dt.tzinfo == pytz.UTC

    def test_prep_datetime_property(self):
        schedule = ScheduleConfig(
            window_opens="2030-08-01 07:00:00",
            prep_time=300,  # 5 minutes
        )
        prep_dt = schedule.prep_datetime
        window_dt = schedule.window_datetime
        assert prep_dt < window_dt
        assert (window_dt - prep_dt).total_seconds() == 300

    def test_custom_early_start_ms(self):
        schedule = ScheduleConfig(
            window_opens="2030-08-01 07:00:00",
            early_start_ms=-200,
        )
        assert schedule.early_start_ms == -200


class TestNotificationsConfig:
    def test_default_notifications_disabled(self):
        notif = NotificationsConfig()
        assert notif.email.enabled is False
        assert notif.sms.enabled is False
        assert notif.webhook.enabled is False

    def test_email_config(self):
        email = EmailConfig(
            enabled=True,
            address="user@example.com",
            sendgrid_api_key="SG.test_key",
        )
        assert email.enabled is True
        assert email.address == "user@example.com"

    def test_sms_config(self):
        sms = SMSConfig(
            enabled=True,
            phone="+1234567890",
            twilio_account_sid="AC123",
            twilio_auth_token="token123",
            twilio_from_number="+0987654321",
        )
        assert sms.enabled is True
        assert sms.phone == "+1234567890"

    def test_webhook_config(self):
        webhook = WebhookConfig(
            enabled=True,
            url="https://hooks.slack.com/services/xxx",
        )
        assert webhook.enabled is True
        assert webhook.url == "https://hooks.slack.com/services/xxx"


class TestBrowserConfig:
    def test_default_browser_config(self):
        browser = BrowserConfig()
        assert browser.headless is False
        assert browser.slow_mo == 50
        assert browser.save_session is True
        assert browser.session_file == "session.json"
        assert browser.handoff_method == "url"

    def test_custom_browser_config(self):
        browser = BrowserConfig(
            headless=True,
            slow_mo=100,
            remote_debugging_port=9222,
        )
        assert browser.headless is True
        assert browser.slow_mo == 100
        assert browser.remote_debugging_port == 9222


class TestAPIConfig:
    def test_default_api_config(self):
        api = APIConfig()
        assert api.base_url == "https://www.recreation.gov"
        assert api.timeout == 10
        assert api.max_retries == 3
        assert api.requests_per_second == 2

    def test_custom_headers(self):
        api = APIConfig(
            headers={"Custom-Header": "value"}
        )
        assert api.headers == {"Custom-Header": "value"}


class TestRetryConfig:
    def test_default_retry_config(self):
        retry = RetryConfig()
        assert retry.max_attempts == 10
        assert retry.attempt_delay_ms == 100
        assert retry.use_fallback_sites is True
        assert retry.stop_on_success is True


class TestConfig:
    def test_create_minimal_config(self):
        config = Config(
            credentials=CredentialsConfig(email="test@example.com", password="secret"),
            target=TargetConfig(
                campground_id="12345",
                arrival_date="2030-08-01",
                departure_date="2030-08-03",
            ),
        )
        assert config.credentials.email == "test@example.com"
        assert config.target.campground_id == "12345"
        # Default values
        assert config.browser.headless is False
        assert config.retry.max_attempts == 10

    def test_from_yaml_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            Config.from_yaml("/nonexistent/path/config.yaml")

    def test_from_yaml_valid_file(self):
        yaml_content = """
credentials:
  email: test@example.com
  password: secret123
target:
  campground_id: "12345"
  campsite_ids:
    - A001
    - A002
  arrival_date: "2030-08-01"
  departure_date: "2030-08-03"
schedule:
  window_opens: "2030-08-01 07:00:00"
  timezone: "America/New_York"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                config = Config.from_yaml(f.name)
                assert config.credentials.email == "test@example.com"
                assert config.target.campground_id == "12345"
                assert config.target.campsite_ids == ["A001", "A002"]
                assert config.schedule.timezone == "America/New_York"
            finally:
                os.unlink(f.name)

    def test_from_env(self, monkeypatch):
        monkeypatch.setenv("RECGOV_EMAIL", "env@example.com")
        monkeypatch.setenv("RECGOV_PASSWORD", "envpassword")
        monkeypatch.setenv("RECGOV_CAMPGROUND_ID", "67890")
        monkeypatch.setenv("RECGOV_ARRIVAL_DATE", "2030-09-01")
        monkeypatch.setenv("RECGOV_DEPARTURE_DATE", "2030-09-03")

        config = Config.from_env()
        assert config.credentials.email == "env@example.com"
        assert config.credentials.password == "envpassword"
        assert config.target.campground_id == "67890"

    def test_from_env_with_campsite_ids(self, monkeypatch):
        monkeypatch.setenv("RECGOV_EMAIL", "env@example.com")
        monkeypatch.setenv("RECGOV_PASSWORD", "envpassword")
        monkeypatch.setenv("RECGOV_CAMPGROUND_ID", "67890")
        monkeypatch.setenv("RECGOV_CAMPSITE_IDS", "X1,X2,X3")
        monkeypatch.setenv("RECGOV_ARRIVAL_DATE", "2030-09-01")
        monkeypatch.setenv("RECGOV_DEPARTURE_DATE", "2030-09-03")

        config = Config.from_env()
        assert config.target.campsite_ids == ["X1", "X2", "X3"]

    def test_from_env_missing_required(self, monkeypatch):
        # Clear any existing env vars
        for key in ["RECGOV_EMAIL", "RECGOV_PASSWORD", "RECGOV_CAMPGROUND_ID",
                    "RECGOV_ARRIVAL_DATE", "RECGOV_DEPARTURE_DATE"]:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(KeyError):
            Config.from_env()

    def test_to_yaml(self):
        config = Config(
            credentials=CredentialsConfig(email="test@example.com", password="secret"),
            target=TargetConfig(
                campground_id="12345",
                arrival_date="2030-08-01",
                departure_date="2030-08-03",
            ),
        )
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            try:
                config.to_yaml(f.name)
                loaded = Config.from_yaml(f.name)
                assert loaded.credentials.email == config.credentials.email
                assert loaded.target.campground_id == config.target.campground_id
            finally:
                os.unlink(f.name)


class TestLoadConfig:
    def test_load_config_with_path(self):
        yaml_content = """
credentials:
  email: load@example.com
  password: loadpassword
target:
  campground_id: "99999"
  arrival_date: "2030-08-01"
  departure_date: "2030-08-03"
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
            f.write(yaml_content)
            f.flush()
            try:
                config = load_config(f.name)
                assert config.credentials.email == "load@example.com"
            finally:
                os.unlink(f.name)

    def test_load_config_falls_back_to_env(self, monkeypatch):
        # Clear default paths
        monkeypatch.chdir(tempfile.gettempdir())
        monkeypatch.setenv("RECGOV_EMAIL", "fallback@example.com")
        monkeypatch.setenv("RECGOV_PASSWORD", "fallbackpwd")
        monkeypatch.setenv("RECGOV_CAMPGROUND_ID", "11111")
        monkeypatch.setenv("RECGOV_ARRIVAL_DATE", "2030-10-01")
        monkeypatch.setenv("RECGOV_DEPARTURE_DATE", "2030-10-03")

        # Should fall back to env vars when no config files exist
        config = load_config()
        assert config.credentials.email == "fallback@example.com"

    def test_load_config_no_config_raises_error(self, monkeypatch):
        # Clear default paths and env vars
        monkeypatch.chdir(tempfile.gettempdir())
        for key in ["RECGOV_EMAIL", "RECGOV_PASSWORD", "RECGOV_CAMPGROUND_ID",
                    "RECGOV_ARRIVAL_DATE", "RECGOV_DEPARTURE_DATE"]:
            monkeypatch.delenv(key, raising=False)

        with pytest.raises(RuntimeError, match="No config file found"):
            load_config()
