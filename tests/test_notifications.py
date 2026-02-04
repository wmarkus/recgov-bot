"""
Tests for notification services (src/common/notifications.py)
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, date, timedelta

from src.common.notifications import (
    NotificationProvider,
    EmailNotifier,
    SMSNotifier,
    WebhookNotifier,
    ConsoleNotifier,
    NotificationManager,
)
from src.common.models import (
    NotificationPayload,
    ReservationAttempt,
    ReservationTarget,
    ReservationStatus,
    Campsite,
    CartItem,
)
from src.common.config import (
    NotificationsConfig,
    EmailConfig,
    SMSConfig,
    WebhookConfig,
)


class TestNotificationPayload:
    def test_create_basic_payload(self):
        payload = NotificationPayload(
            title="Test Title",
            message="Test message",
        )
        assert payload.title == "Test Title"
        assert payload.message == "Test message"
        assert payload.url is None
        assert payload.urgency == "normal"

    def test_create_full_payload(self):
        payload = NotificationPayload(
            title="Success",
            message="Reservation complete",
            url="https://example.com/cart",
            urgency="high",
        )
        assert payload.url == "https://example.com/cart"
        assert payload.urgency == "high"


class TestConsoleNotifier:
    @pytest.mark.asyncio
    async def test_send_basic_payload(self, capsys):
        notifier = ConsoleNotifier()
        payload = NotificationPayload(
            title="Test Title",
            message="Test message",
        )
        
        result = await notifier.send(payload)
        
        assert result is True
        captured = capsys.readouterr()
        assert "Test Title" in captured.out
        assert "Test message" in captured.out

    @pytest.mark.asyncio
    async def test_send_payload_with_url(self, capsys):
        notifier = ConsoleNotifier()
        payload = NotificationPayload(
            title="Success",
            message="Reservation complete",
            url="https://example.com/cart",
        )
        
        result = await notifier.send(payload)
        
        assert result is True
        captured = capsys.readouterr()
        assert "https://example.com/cart" in captured.out


class TestEmailNotifier:
    @pytest.mark.asyncio
    async def test_send_success(self):
        notifier = EmailNotifier(
            api_key="SG.test_key",
            to_address="user@example.com",
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 202
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(
            title="Test",
            message="Test message",
        )
        
        result = await notifier.send(payload)
        assert result is True
        notifier.client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_failure(self):
        notifier = EmailNotifier(
            api_key="SG.test_key",
            to_address="user@example.com",
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 401
        mock_response.text = "Unauthorized"
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(title="Test", message="Test")
        result = await notifier.send(payload)
        
        assert result is False

    @pytest.mark.asyncio
    async def test_send_network_error(self):
        notifier = EmailNotifier(
            api_key="SG.test_key",
            to_address="user@example.com",
        )
        
        notifier.client.post = AsyncMock(side_effect=Exception("Network error"))
        
        payload = NotificationPayload(title="Test", message="Test")
        result = await notifier.send(payload)
        
        assert result is False

    def test_format_html_success(self):
        notifier = EmailNotifier(
            api_key="SG.test_key",
            to_address="user@example.com",
        )
        
        payload = NotificationPayload(
            title="SUCCESS!",
            message="Reservation complete",
            url="https://example.com/cart",
        )
        
        html = notifier._format_html(payload)
        
        assert "SUCCESS!" in html
        assert "Reservation complete" in html
        assert "https://example.com/cart" in html
        assert "#22c55e" in html  # Success color

    def test_format_html_failure(self):
        notifier = EmailNotifier(
            api_key="SG.test_key",
            to_address="user@example.com",
        )
        
        payload = NotificationPayload(
            title="Failed",
            message="Could not complete",
        )
        
        html = notifier._format_html(payload)
        
        assert "Failed" in html
        assert "#ef4444" in html  # Failure color


class TestSMSNotifier:
    @pytest.mark.asyncio
    async def test_send_success(self):
        notifier = SMSNotifier(
            account_sid="AC123",
            auth_token="token123",
            from_number="+10987654321",
            to_number="+11234567890",
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 201
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(title="Test", message="Test message")
        result = await notifier.send(payload)
        
        assert result is True
        notifier.client.post.assert_called_once()
        call_args = notifier.client.post.call_args
        assert "twilio.com" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_send_failure(self):
        notifier = SMSNotifier(
            account_sid="AC123",
            auth_token="token123",
            from_number="+10987654321",
            to_number="+11234567890",
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 400
        mock_response.text = "Bad request"
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(title="Test", message="Test")
        result = await notifier.send(payload)
        
        assert result is False

    def test_format_sms_basic(self):
        notifier = SMSNotifier(
            account_sid="AC123",
            auth_token="token123",
            from_number="+10987654321",
            to_number="+11234567890",
        )
        
        payload = NotificationPayload(title="Success", message="Got it!")
        sms = notifier._format_sms(payload)
        
        assert "Success" in sms
        assert "Got it!" in sms

    def test_format_sms_with_url(self):
        notifier = SMSNotifier(
            account_sid="AC123",
            auth_token="token123",
            from_number="+10987654321",
            to_number="+11234567890",
        )
        
        payload = NotificationPayload(
            title="Success",
            message="Got it!",
            url="https://example.com/cart",
        )
        sms = notifier._format_sms(payload)
        
        assert "https://example.com/cart" in sms

    def test_format_sms_truncates_long_messages(self):
        notifier = SMSNotifier(
            account_sid="AC123",
            auth_token="token123",
            from_number="+10987654321",
            to_number="+11234567890",
        )
        
        long_message = "x" * 2000
        payload = NotificationPayload(title="Test", message=long_message)
        sms = notifier._format_sms(payload)
        
        assert len(sms) <= 1600


class TestWebhookNotifier:
    @pytest.mark.asyncio
    async def test_send_success(self):
        notifier = WebhookNotifier(
            webhook_url="https://hooks.slack.com/services/xxx"
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(title="Test", message="Test message")
        result = await notifier.send(payload)
        
        assert result is True
        notifier.client.post.assert_called_once()

    @pytest.mark.asyncio
    async def test_send_with_url(self):
        notifier = WebhookNotifier(
            webhook_url="https://hooks.slack.com/services/xxx"
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 200
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(
            title="Test",
            message="Test message",
            url="https://example.com/cart",
        )
        result = await notifier.send(payload)
        
        assert result is True
        # Check that the URL was included in the request
        call_args = notifier.client.post.call_args
        json_body = call_args[1]["json"]
        assert any("https://example.com/cart" in str(block) for block in json_body["blocks"])

    @pytest.mark.asyncio
    async def test_send_failure(self):
        notifier = WebhookNotifier(
            webhook_url="https://hooks.slack.com/services/xxx"
        )
        
        mock_response = MagicMock()
        mock_response.status_code = 500
        
        notifier.client.post = AsyncMock(return_value=mock_response)
        
        payload = NotificationPayload(title="Test", message="Test")
        result = await notifier.send(payload)
        
        assert result is False


class TestNotificationManager:
    def test_init_with_no_providers_enabled(self):
        config = NotificationsConfig()
        manager = NotificationManager(config)
        
        # Should only have console notifier
        assert len(manager.providers) == 1
        assert isinstance(manager.providers[0], ConsoleNotifier)

    def test_init_with_email_enabled(self):
        config = NotificationsConfig(
            email=EmailConfig(
                enabled=True,
                address="user@example.com",
                sendgrid_api_key="SG.test_key",
            )
        )
        manager = NotificationManager(config)
        
        assert len(manager.providers) == 2
        assert any(isinstance(p, EmailNotifier) for p in manager.providers)

    def test_init_with_sms_enabled(self):
        config = NotificationsConfig(
            sms=SMSConfig(
                enabled=True,
                phone="+11234567890",
                twilio_account_sid="AC123",
                twilio_auth_token="token123",
                twilio_from_number="+10987654321",
            )
        )
        manager = NotificationManager(config)
        
        assert len(manager.providers) == 2
        assert any(isinstance(p, SMSNotifier) for p in manager.providers)

    def test_init_with_webhook_enabled(self):
        config = NotificationsConfig(
            webhook=WebhookConfig(
                enabled=True,
                url="https://hooks.slack.com/services/xxx",
            )
        )
        manager = NotificationManager(config)
        
        assert len(manager.providers) == 2
        assert any(isinstance(p, WebhookNotifier) for p in manager.providers)

    def test_init_with_email_missing_api_key(self):
        config = NotificationsConfig(
            email=EmailConfig(
                enabled=True,
                address="user@example.com",
                # Missing sendgrid_api_key
            )
        )
        manager = NotificationManager(config)
        
        # Should only have console notifier
        assert len(manager.providers) == 1
        assert isinstance(manager.providers[0], ConsoleNotifier)

    def test_init_with_all_providers_enabled(self):
        config = NotificationsConfig(
            email=EmailConfig(
                enabled=True,
                address="user@example.com",
                sendgrid_api_key="SG.test_key",
            ),
            sms=SMSConfig(
                enabled=True,
                phone="+11234567890",
                twilio_account_sid="AC123",
                twilio_auth_token="token123",
                twilio_from_number="+10987654321",
            ),
            webhook=WebhookConfig(
                enabled=True,
                url="https://hooks.slack.com/services/xxx",
            )
        )
        manager = NotificationManager(config)
        
        # Console + Email + SMS + Webhook = 4
        assert len(manager.providers) == 4

    @pytest.mark.asyncio
    async def test_notify_success(self, target):
        config = NotificationsConfig()
        manager = NotificationManager(config)
        
        # Replace console notifier with mock
        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=True)
        manager.providers = [mock_provider]
        
        campsite = Campsite(id="1001", campground_id=target.campground_id, name="A001")
        cart_item = CartItem(
            reservation_id="RES123",
            campsite=campsite,
            arrival_date=target.arrival_date,
            departure_date=target.departure_date,
            subtotal=50.0,
            fees=5.0,
            total=55.0,
            expires_at=datetime.now() + timedelta(minutes=15),
        )
        
        attempt = ReservationAttempt(target=target)
        attempt.mark_success(campsite, cart_item)
        
        await manager.notify_success(attempt)
        
        mock_provider.send.assert_called_once()
        call_args = mock_provider.send.call_args[0][0]
        assert "CAMPSITE SECURED" in call_args.title
        assert "A001" in call_args.message

    @pytest.mark.asyncio
    async def test_notify_failure(self, target):
        config = NotificationsConfig()
        manager = NotificationManager(config)
        
        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=True)
        manager.providers = [mock_provider]
        
        attempt = ReservationAttempt(target=target)
        attempt.mark_failed("No sites available")
        
        await manager.notify_failure(attempt)
        
        mock_provider.send.assert_called_once()
        call_args = mock_provider.send.call_args[0][0]
        assert "Failed" in call_args.title
        assert "No sites available" in call_args.message

    @pytest.mark.asyncio
    async def test_notify_captcha(self):
        config = NotificationsConfig()
        manager = NotificationManager(config)
        
        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=True)
        manager.providers = [mock_provider]
        
        await manager.notify_captcha("https://example.com/captcha")
        
        mock_provider.send.assert_called_once()
        call_args = mock_provider.send.call_args[0][0]
        assert "CAPTCHA" in call_args.title
        assert call_args.url == "https://example.com/captcha"

    @pytest.mark.asyncio
    async def test_notify_starting(self, target):
        config = NotificationsConfig()
        manager = NotificationManager(config)
        
        mock_provider = AsyncMock()
        mock_provider.send = AsyncMock(return_value=True)
        manager.providers = [mock_provider]
        
        attempt = ReservationAttempt(target=target)
        
        await manager.notify_starting(attempt)
        
        mock_provider.send.assert_called_once()
        call_args = mock_provider.send.call_args[0][0]
        assert "Starting" in call_args.title

    @pytest.mark.asyncio
    async def test_send_all_handles_mixed_results(self, target):
        config = NotificationsConfig()
        manager = NotificationManager(config)
        
        # Create providers with mixed results
        success_provider = AsyncMock()
        success_provider.send = AsyncMock(return_value=True)
        
        failure_provider = AsyncMock()
        failure_provider.send = AsyncMock(return_value=False)
        
        error_provider = AsyncMock()
        error_provider.send = AsyncMock(side_effect=Exception("Error"))
        
        manager.providers = [success_provider, failure_provider, error_provider]
        
        payload = NotificationPayload(title="Test", message="Test")
        await manager._send_all(payload)
        
        # All providers should be called despite errors
        success_provider.send.assert_called_once()
        failure_provider.send.assert_called_once()
        error_provider.send.assert_called_once()
