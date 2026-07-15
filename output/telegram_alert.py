import requests
from core.logger import get_logger

logger = get_logger(__name__)


class TelegramAlert:

    def __init__(self, bot_token: str, chat_id: str):

        self.bot_token = bot_token

        self.chat_id = chat_id

        self.base_url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    def send(self, message: str, level: str = "INFO", raw: bool = False):

        text = message if raw else f"[{level}] {message}"

        payload = {
            "chat_id": self.chat_id,
            "text": text,
        }

        try:

            requests.post(self.base_url, data=payload)

            logger.info("Telegram alert sent")

        except Exception as e:

            logger.error(f"Telegram send failed: {e}")
