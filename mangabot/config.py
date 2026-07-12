from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os


ROOT_DIR = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT_DIR / "data" / "mangabot.sqlite3"
TOKEN_FILE = ROOT_DIR / "bot_token.txt"


@dataclass(frozen=True)
class Settings:
    bot_token: str
    db_path: Path
    check_interval_seconds: int
    search_limit: int


def load_settings() -> Settings:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token and TOKEN_FILE.exists():
        token = TOKEN_FILE.read_text(encoding="utf-8").strip()

    if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
        raise RuntimeError(
            "Не найден токен бота. Заполните bot_token.txt или задайте TELEGRAM_BOT_TOKEN."
        )

    interval_minutes_raw = os.getenv("CHECK_INTERVAL_MINUTES", "15").strip()
    try:
        interval_minutes = max(1, int(interval_minutes_raw))
    except ValueError as exc:
        raise RuntimeError("CHECK_INTERVAL_MINUTES должен быть целым числом.") from exc

    search_limit_raw = os.getenv("SEARCH_LIMIT", "6").strip()
    try:
        search_limit = min(10, max(3, int(search_limit_raw)))
    except ValueError as exc:
        raise RuntimeError("SEARCH_LIMIT должен быть целым числом.") from exc

    db_path = Path(os.getenv("MANGABOT_DB_PATH", str(DEFAULT_DB_PATH))).expanduser()

    return Settings(
        bot_token=token,
        db_path=db_path,
        check_interval_seconds=interval_minutes * 60,
        search_limit=search_limit,
    )

