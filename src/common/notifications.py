"""
Notification services for Recreation.gov bot
"""
import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional
import httpx

from .models import NotificationPayload, ReservationAttempt
from .config import NotificationsConfig

logger = logging.getLogger(__name__)


class NotificationProvider(ABC):
    """Base class for notification providers"""
    
    @abstractmethod
    async def send(self, payload: NotificationPayload) -> bool:
        """Send notification, return True if successful"""
        pass


class EmailNotifier(NotificationProvider):
    """SendGrid email notifications"""
    
    def __init__(self, api_key: str, to_address: str, from_address: str = "noreply@recgov-bot.local"):
        self.api_key = api_key
        self.to_address = to_address
        self.from_address = from_address
        self.client = httpx.AsyncClient()
    
    async def send(self, payload: NotificationPayload) -> bool:
        try:
            response = await self.client.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json={
                    "personalizations": [{"to": [{"email": self.to_address}]}],
                    "from": {"email": self.from_address, "name": "RecGov Bot"},
                    "subject": payload.title,
                    "content": [
                        {
                            "type": "text/html",
                            "value": self._format_html(payload)
                        }
                    ]
                }
            )
            success = response.status_code in (200, 202)
            if not success:
                logger.error(f"Email send failed: {response.status_code} - {response.text}")
            return success
        except Exception as e:
            logger.error(f"Email send error: {e}")
            return False
    
    def _format_html(self, payload: NotificationPayload) -> str:
        html = f"""
        <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h1 style="color: {'#22c55e' if 'SUCCESS' in payload.title else '#ef4444'};">
                {payload.title}
            </h1>
            <p style="font-size: 16px;">{payload.message}</p>
        """
        if payload.url:
            html += f"""
            <p style="margin-top: 20px;">
                <a href="{payload.url}" 
                   style="background: #2563eb; color: white; padding: 12px 24px; 
                          text-decoration: none; border-radius: 6px; font-weight: bold;">
                    Complete Checkout →
                </a>
            </p>
            <p style="color: #666; font-size: 14px; margin-top: 20px;">
                ⏰ You have 15 minutes to complete your reservation!
            </p>
            """
        html += """
        </body>
        </html>
        """
        return html


class SMSNotifier(NotificationProvider):
    """Twilio SMS notifications"""
    
    def __init__(self, account_sid: str, auth_token: str, from_number: str, to_number: str):
        self.account_sid = account_sid
        self.auth_token = auth_token
        self.from_number = from_number
        self.to_number = to_number
        self.client = httpx.AsyncClient()
    
    async def send(self, payload: NotificationPayload) -> bool:
        try:
            response = await self.client.post(
                f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json",
                auth=(self.account_sid, self.auth_token),
                data={
                    "From": self.from_number,
                    "To": self.to_number,
                    "Body": self._format_sms(payload)
                }
            )
            success = response.status_code == 201
            if not success:
                logger.error(f"SMS send failed: {response.status_code} - {response.text}")
            return success
        except Exception as e:
            logger.error(f"SMS send error: {e}")
            return False
    
    def _format_sms(self, payload: NotificationPayload) -> str:
        msg = f"🏕️ {payload.title}\n\n{payload.message}"
        if payload.url:
            msg += f"\n\nCheckout: {payload.url}"
        return msg[:1600]  # SMS length limit


class WebhookNotifier(NotificationProvider):
    """Generic webhook notifications (Slack, Discord, etc.)"""
    
    def __init__(self, webhook_url: str):
        self.webhook_url = webhook_url
        self.client = httpx.AsyncClient()
    
    async def send(self, payload: NotificationPayload) -> bool:
        try:
            # Format for Slack-compatible webhooks
            response = await self.client.post(
                self.webhook_url,
                json={
                    "text": payload.title,
                    "blocks": [
                        {
                            "type": "header",
                            "text": {"type": "plain_text", "text": payload.title}
                        },
                        {
                            "type": "section",
                            "text": {"type": "mrkdwn", "text": payload.message}
                        },
                        *([{
                            "type": "section",
                            "text": {
                                "type": "mrkdwn",
                                "text": f"<{payload.url}|Complete Checkout →>"
                            }
                        }] if payload.url else [])
                    ]
                }
            )
            return response.status_code == 200
        except Exception as e:
            logger.error(f"Webhook send error: {e}")
            return False


class ConsoleNotifier(NotificationProvider):
    """Console output for testing"""
    
    async def send(self, payload: NotificationPayload) -> bool:
        print("\n" + "=" * 60)
        print(f"📢 {payload.title}")
        print("-" * 60)
        print(payload.message)
        if payload.url:
            print(f"\n🔗 {payload.url}")
        print("=" * 60 + "\n")
        return True


class NotificationManager:
    """Manages multiple notification providers"""
    
    def __init__(self, config: NotificationsConfig):
        self.providers: list[NotificationProvider] = []
        
        # Always add console notifier
        self.providers.append(ConsoleNotifier())
        
        # Add configured providers
        if config.email.enabled and config.email.sendgrid_api_key and config.email.address:
            self.providers.append(EmailNotifier(
                api_key=config.email.sendgrid_api_key,
                to_address=config.email.address
            ))
            logger.info("Email notifications enabled")
        elif config.email.enabled:
            logger.warning("Email notifications enabled but missing address or API key")
        
        if (
            config.sms.enabled
            and config.sms.twilio_account_sid
            and config.sms.twilio_auth_token
            and config.sms.twilio_from_number
            and config.sms.phone
        ):
            self.providers.append(SMSNotifier(
                account_sid=config.sms.twilio_account_sid,
                auth_token=config.sms.twilio_auth_token,
                from_number=config.sms.twilio_from_number,
                to_number=config.sms.phone
            ))
            logger.info("SMS notifications enabled")
        elif config.sms.enabled:
            logger.warning("SMS notifications enabled but missing Twilio config")
        
        if config.webhook.enabled and config.webhook.url:
            self.providers.append(WebhookNotifier(config.webhook.url))
            logger.info("Webhook notifications enabled")
        elif config.webhook.enabled:
            logger.warning("Webhook notifications enabled but missing URL")
    
    async def notify_success(self, attempt: ReservationAttempt):
        """Send success notification"""
        payload = NotificationPayload(
            title="🎉 CAMPSITE SECURED!",
            message=(
                f"Successfully added to cart!\n\n"
                f"Site: {attempt.campsite_secured.name if attempt.campsite_secured else 'Unknown'}\n"
                f"Dates: {attempt.target.arrival_date} to {attempt.target.departure_date}\n\n"
                f"⚠️ Complete checkout within 15 minutes!"
            ),
            url=attempt.checkout_url,
            urgency="high",
            attempt=attempt
        )
        await self._send_all(payload)
    
    async def notify_failure(self, attempt: ReservationAttempt):
        """Send failure notification"""
        payload = NotificationPayload(
            title="❌ Reservation Failed",
            message=(
                f"Unable to secure campsite.\n\n"
                f"Error: {attempt.error_message or 'Unknown'}\n"
                f"Attempts made: {attempt.attempts_made}"
            ),
            urgency="normal",
            attempt=attempt
        )
        await self._send_all(payload)
    
    async def notify_captcha(self, url: str):
        """Notify user that CAPTCHA intervention is needed"""
        payload = NotificationPayload(
            title="🤖 CAPTCHA Required",
            message="Human verification required. Please solve the CAPTCHA to continue.",
            url=url,
            urgency="high"
        )
        await self._send_all(payload)
    
    async def notify_starting(self, attempt: ReservationAttempt):
        """Notify that reservation attempt is starting"""
        payload = NotificationPayload(
            title="🚀 Reservation Attempt Starting",
            message=(
                f"Beginning reservation attempt for:\n"
                f"Campground ID: {attempt.target.campground_id}\n"
                f"Dates: {attempt.target.arrival_date} to {attempt.target.departure_date}"
            ),
            urgency="normal"
        )
        await self._send_all(payload)
    
    async def _send_all(self, payload: NotificationPayload):
        """Send notification through all providers"""
        results = await asyncio.gather(
            *[p.send(payload) for p in self.providers],
            return_exceptions=True
        )
        
        success_count = sum(1 for r in results if r is True)
        logger.info(f"Notifications sent: {success_count}/{len(self.providers)} successful")
