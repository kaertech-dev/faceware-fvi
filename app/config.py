import os

from dotenv import load_dotenv

load_dotenv()

def required_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} environment variable is required")
    return value

def env_bool(name: str, default: bool = False) -> bool:
    return os.environ.get(name, str(default)).lower() in {"1", "true", "yes", "on"}

class Config:
    SECRET_KEY = required_env("SECRET_KEY")
    TRAY_LIMIT = 50
    ADMIN_PASSWORD = required_env("ADMIN_PASSWORD")
    SESSION_COOKIE_SECURE = env_bool("SESSION_COOKIE_SECURE", True)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    MAX_CONTENT_LENGTH = 16 * 1024
    FORCE_HTTPS = env_bool("FORCE_HTTPS", True)
    FUN_LOGIN_MESSAGES = env_bool("FUN_LOGIN_MESSAGES", False)

class DBConfig:
    HOST = required_env("DB_HOST")
    USER = required_env("DB_USER")
    PASSWORD = required_env("DB_PASSWORD")
    DATABASE = required_env("DB_NAME")
    PORT = int(required_env("DB_PORT"))
