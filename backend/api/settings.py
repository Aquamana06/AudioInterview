from pathlib import Path
import os

from dotenv import load_dotenv

from config import load_config


BACKEND_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(BACKEND_ROOT / ".env")


def setting(name: str, default: str = "") -> str:
    return os.getenv(name, default)


def database_path() -> Path:
    value = Path(setting("DATABASE_PATH", load_config("db")["database"]["path"]))
    return value if value.is_absolute() else (BACKEND_ROOT / value).resolve()
