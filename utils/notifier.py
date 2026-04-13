import logging
from typing import Any

import requests


class TelegramNotifier:
    def __init__(self, bot_token: str, chat_id: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.chat_id = chat_id
        self.session = requests.Session()
        self.session.trust_env = False
        self.session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/123.0.0.0 Safari/537.36"
                )
            }
        )

    def _payload(self, message: str) -> dict[str, Any]:
        return {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }

    def send_message(self, message: str) -> bool:
        logging.info("Sending Telegram notification")
        print("DEBUG TELEGRAM SEND:", message)
        url = f"{self.base_url}/sendMessage"
        try:
            response = self.session.post(
                url,
                data=self._payload(message),
                timeout=15,
            )
            print("TELEGRAM STATUS:", response.status_code, response.text)
            response.raise_for_status()
            data = response.json()
            if not data.get("ok"):
                print("TELEGRAM RESPONSE ERROR:", data)
                return False
            return True
        except Exception as exc:
            print("TELEGRAM ERROR:", exc)
            logging.exception("Telegram notification failed: %s", exc)
            return False
