from __future__ import annotations

from typing import Any, Dict

import httpx


class EvolutionClient:
    def __init__(self, bot_config: Dict[str, Any]) -> None:
        self.base_url = bot_config["evolution"]["base_url"].rstrip("/")
        self.api_key = bot_config["evolution"]["api_key"]
        self.instance = bot_config["evolution"]["instance"]
        self.endpoint_pattern = bot_config["evolution"].get(
            "send_text_endpoint", "/message/sendText/{instance}"
        )

    def send_text(self, number: str, text: str) -> None:
        endpoint = self.endpoint_pattern.format(instance=self.instance)
        url = f"{self.base_url}{endpoint}"
        payload = {
            "number": number,
            "text": text,
        }
        headers = {
            "apikey": self.api_key,
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=20) as client:
            response = client.post(url, json=payload, headers=headers)
            response.raise_for_status()
