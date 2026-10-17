"""Application configuration module."""
import os
from typing import List
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime application settings with environment variable support."""
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Market Data API
    API_BASE_URL: str = Field(default="https://quotexfeed.lovable.app", description="Base REST URL for market feed")
    API_WS_URL: str = Field(default="wss://quotexfeed.lovable.app", description="WebSocket base URL")
    
    # Storage
    DATABASE_URL: str = Field(
        default="sqlite+aiosqlite:///quotex_bot.db",
        description="Async database connection string (PostgreSQL or SQLite)"
    )

    # Telegram Notification
    TELEGRAM_BOT_TOKEN: str = Field(default="", description="Telegram Bot API token")
    TELEGRAM_CHAT_ID: str = Field(default="", description="Telegram channel or chat ID")

    # Time and Engine Parameters
    DISPLAY_TIMEZONE: str = Field(default="Asia/Karachi", description="Display timezone for messages")
    CANDLE_INTERVAL: str = Field(default="1m", description="Analysis candle interval")
    EXPIRY_SECONDS: int = Field(default=60, description="Signal duration in seconds")
    SIGNAL_LEAD_SECONDS: int = Field(default=12, description="Target seconds before candle open to signal")
    NOTIFICATION_WINDOW_START: int = Field(default=45, description="Min second within minute to dispatch signal (:45)")
    NOTIFICATION_WINDOW_END: int = Field(default=52, description="Max second within minute to dispatch signal (:52)")

    # Strategy & Scoring
    MIN_SETUP_SCORE: float = Field(default=75.0, description="Minimum score (0-100) to qualify for broadcast")
    SCAN_INTERVAL_SECONDS: float = Field(default=1.0, description="Evaluation tick interval")
    MAX_ACTIVE_SIGNALS: int = Field(default=1, description="Maximum concurrent active signals allowed globally")

    # Data Quality Tolerances
    DATA_STALE_SECONDS: float = Field(default=5.0, description="Seconds without ticks before marking pair stale")
    ENTRY_QUOTE_TOLERANCE_SECONDS: float = Field(default=4.0, description="Allowed deviation around entry timestamp")
    EXPIRY_QUOTE_TOLERANCE_SECONDS: float = Field(default=6.0, description="Allowed deviation around expiry timestamp")
    RESULT_TIMEOUT_SECONDS: float = Field(default=75.0, description="Seconds before marking outcome UNVERIFIED")

    # Web & Server Settings
    PORT: int = Field(default=8080, description="Port for HTTP health server")
    HOST: str = Field(default="0.0.0.0", description="Host to bind HTTP server")
    LOG_LEVEL: str = Field(default="INFO", description="Log level")
    KILL_SWITCH_ACTIVE: bool = Field(default=False, description="Pause new signal dispatches")
    PAPER_MODE: bool = Field(default=True, description="Dry run mode for honest recordkeeping")

    # Martingale / MTG settings
    MARTINGALE_ENABLED: bool = Field(default=True, description="Enable martingale mtg1 automation")
    MARTINGALE_BASE_STAKE: float = Field(default=1.0, description="Base stake for martingale")
    MARTINGALE_MAX_STEPS: int = Field(default=3, description="Maximum martingale steps")
    MARTINGALE_MAX_STAKE: float = Field(default=100.0, description="Maximum stake allowed for martingale")
    MARTINGALE_MODE: str = Field(default="fixed", description="'fixed' or 'percentage' stake mode")

    # Configurable Symbol List (defaults to 48 canonical OTC pairs)
    ACTIVE_SYMBOLS: List[str] = [
        "AUDCAD-OTC", "AUDCHF-OTC", "AUDJPY-OTC", "AUDNZD-OTC", "AUDUSD-OTC", "BRLUSD-OTC",
        "CADCHF-OTC", "CADJPY-OTC", "CHFJPY-OTC", "EURAUD-OTC", "EURCAD-OTC", "EURCHF-OTC",
        "EURGBP-OTC", "EURJPY-OTC", "EURNZD-OTC", "EURSGD-OTC", "EURUSD-OTC", "GBPAUD-OTC",
        "GBPCAD-OTC", "GBPCHF-OTC", "GBPJPY-OTC", "GBPNZD-OTC", "GBPUSD-OTC", "NZDCAD-OTC",
        "NZDCHF-OTC", "NZDJPY-OTC", "NZDUSD-OTC", "USDARS-OTC", "USDBDT-OTC", "USDCAD-OTC",
        "USDCHF-OTC", "USDCOP-OTC", "USDDZD-OTC", "USDEGP-OTC", "USDIDR-OTC", "USDINR-OTC",
        "USDJPY-OTC", "USDMXN-OTC", "USDPKR-OTC", "USDZAR-OTC", "AXP-OTC", "BOI-OTC",
        "FB-OTC", "INT-OTC", "JNJ-OTC", "MCD-OTC", "MSFT-OTC", "BTC-OTC"
    ]


settings = Settings()
