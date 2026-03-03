import json
from pathlib import Path
from typing import Any, Dict

BASE_DIR = Path(__file__).resolve().parent


def _load_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_db_config() -> Dict[str, Any]:
    return _load_json(BASE_DIR / "config_banco.json")


def load_bot_config() -> Dict[str, Any]:
    return _load_json(BASE_DIR / "config_bot.json")
