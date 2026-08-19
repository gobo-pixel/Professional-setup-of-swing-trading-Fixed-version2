import requests
from core.logger import get_logger

logger = get_logger(__name__)


class TelegramAlert:

    def __init__(self, bot_token: str, chat_id: str):
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.base_url = (
            f"https://api.telegram.org/bot{bot_token}/sendMessage"
        )

    def send(
        self,
        message: str,
        level: str = "INFO",
        raw: bool = False,
    ):
        text = message if raw else f"[{level}] {message}"

        payload = {
            "chat_id": self.chat_id,
            "text": text,
        }

        try:
            response = requests.post(
                self.base_url,
                data=payload,
                timeout=20,
            )

            print(f"Telegram HTTP status: {response.status_code}")
            print(f"Telegram API response: {response.text}")

            response.raise_for_status()

            result = response.json()

            if not result.get("ok"):
                raise RuntimeError(
                    f"Telegram API rejected message: {result}"
                )

            logger.info("Telegram alert sent successfully")

        except Exception as e:
            logger.error(f"Telegram send failed: {e}")
            raise
