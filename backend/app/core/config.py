"""
config.py — Application settings loaded from environment / .env file.

PRODUCTION CHECKLIST:
  1. Set SECRET_KEY to a random 64-char hex string:
       python3 -c "import secrets; print(secrets.token_hex(32))"
  2. Set DEBUG=false
  3. Set ALLOWED_ORIGINS to your actual frontend URL only
  4. Set DATABASE_URL to a real DB (PostgreSQL recommended for production)
  5. Never commit .env to git (it is already in .gitignore)
"""

import json
import secrets
from typing import List

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── App ──────────────────────────────────────────────────────────────────
    APP_NAME:    str  = "Retail Behavior Intelligence System"
    APP_VERSION: str  = "2.0.0"
    # IMPORTANT: set DEBUG=false in production
    DEBUG:       bool = False
    # IMPORTANT: override with a real secret — python3 -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY:  str  = ""

    # ── CORS — restrict to your actual frontend domain in production ─────────
    # Example: '["https://your-domain.pages.dev"]'
    ALLOWED_ORIGINS: str = '["http://localhost:3000","http://localhost:5173","http://localhost:8000"]'

    # ── Database ─────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./rbis.db"

    # ── Redis (optional) ─────────────────────────────────────────────────────
    REDIS_URL:  str  = "redis://localhost:6379/0"
    USE_REDIS:  bool = False

    # ── Storage ───────────────────────────────────────────────────────────────
    STORAGE_BACKEND:     str = "local"
    LOCAL_STORAGE_PATH:  str = "./data"
    S3_BUCKET_NAME:      str = ""
    S3_REGION:           str = ""
    AWS_ACCESS_KEY_ID:   str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # ── Video ─────────────────────────────────────────────────────────────────
    NUM_CAMERAS:    int = 5
    FRAME_WIDTH:    int = 1280
    FRAME_HEIGHT:   int = 720
    TARGET_FPS:     int = 25
    PROCESSING_FPS: int = 5
    USE_GPU:        bool = False

    # ── Suspicion scoring ─────────────────────────────────────────────────────
    SCORE_PICK_ITEM:        int = 10
    SCORE_HOLD_ITEM_PER_10S: int = 5
    SCORE_MULTI_ITEM:       int = 10
    SCORE_AVOID_REGISTER:   int = 15
    SCORE_MOVE_TO_EXIT:     int = 20
    SCORE_RETURN_ITEM:      int = -15
    SCORE_COMPLETE_CHECKOUT: int = -50
    SCORE_IDLE_PER_10S:     int = -1
    THRESHOLD_WATCH:        int = 31
    THRESHOLD_HIGH:         int = 61

    # ── Alerts ────────────────────────────────────────────────────────────────
    ALERT_CLIP_SECONDS_BEFORE: int = 10
    ALERT_CLIP_SECONDS_AFTER:  int = 10

    # ── Notifications (leave blank to disable) ───────────────────────────────
    TWILIO_ACCOUNT_SID:  str = ""
    TWILIO_AUTH_TOKEN:   str = ""
    TWILIO_FROM_NUMBER:  str = ""
    SENDGRID_API_KEY:    str = ""
    ALERT_EMAIL_FROM:    str = ""
    ALERT_EMAIL_TO:      str = ""
    # Tiered routing: CRITICAL/high-confidence alerts page this number by SMS
    # immediately; everything else goes to email only. Keeps the person who
    # gets paged at 2am to the alerts that actually warrant it.
    ALERT_SMS_TO:        str = ""

    # ── Reports ───────────────────────────────────────────────────────────────
    REPORT_GENERATION_HOUR:   int = 23
    REPORT_GENERATION_MINUTE: int = 55

    # ── Data retention ────────────────────────────────────────────────────────
    # Structurally enforces the privacy stance (behavioral signals only — no
    # PII, no biometric identity) rather than leaving it as policy alone.
    # Tracking data older than this is purged daily: Person/Event/SuspicionScore/
    # HeatmapPoint/SensorEvent rows and their associated snapshot/clip files.
    # Alerts are kept 2x as long by default (they're the record a business
    # needs to justify an action already taken) — see ALERT_RETENTION_DAYS.
    DATA_RETENTION_DAYS:      int  = 30
    ALERT_RETENTION_DAYS:     int  = 60
    RETENTION_PURGE_HOUR:     int  = 3    # run overnight, low-traffic
    RETENTION_PURGE_MINUTE:   int  = 15

    # ── AI / YOLOv8 ──────────────────────────────────────────────────────────────
    # Set AI_ENABLED=true in .env to activate real camera detection.
    # When false (default) the system runs in simulation-only mode.
    AI_ENABLED:        bool  = False
    YOLO_MODEL_PATH:   str   = ""          # auto-downloaded to data/ if blank
    AI_FRAME_SKIP:     int   = 3           # process every Nth frame
    AI_CONFIDENCE:     float = 0.40        # min YOLO detection confidence

    # ── JWT Auth ──────────────────────────────────────────────────────────────────
    JWT_ALGORITHM:         str = "HS256"
    JWT_ACCESS_EXPIRES_M:  int = 60        # access token lifetime (minutes)
    JWT_REFRESH_EXPIRES_D: int = 7         # refresh token lifetime (days)

    # ── WebSocket limits ──────────────────────────────────────────────────────
    WS_MAX_CONNECTIONS: int = 100   # refuse connections above this
    WS_MAX_MESSAGE_SIZE: int = 65536  # 64 KB max incoming WS message

    # ── Rate limiting (requests per minute per IP) ────────────────────────────
    RATE_LIMIT_PER_MINUTE: int = 300

    # ── Validators ────────────────────────────────────────────────────────────

    @model_validator(mode="after")
    def ensure_secret_key(self) -> "Settings":
        """Auto-generate a secret key if none provided — warns in production."""
        if not self.SECRET_KEY:
            import logging
            key = secrets.token_hex(32)
            object.__setattr__(self, "SECRET_KEY", key)
            logging.getLogger(__name__).warning(
                "SECRET_KEY not set — generated ephemeral key. "
                "Set SECRET_KEY in .env for a persistent key."
            )
        return self

    @property
    def allowed_origins_list(self) -> List[str]:
        try:
            return json.loads(self.ALLOWED_ORIGINS)
        except Exception:
            return ["http://localhost:3000"]

    @property
    def is_sqlite(self) -> bool:
        return "sqlite" in self.DATABASE_URL

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
