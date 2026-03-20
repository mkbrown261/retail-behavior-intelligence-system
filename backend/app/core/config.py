from pydantic_settings import BaseSettings
from pydantic import field_validator
from typing import List
import json


class Settings(BaseSettings):
    # App
    APP_NAME: str = "Retail Behavior Intelligence System"
    APP_VERSION: str = "2.0.0"
    DEBUG: bool = True
    SECRET_KEY: str = "rbis-secret"
    ALLOWED_ORIGINS: str = '["http://localhost:3000","http://localhost:5173"]'

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./rbis.db"

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"
    USE_REDIS: bool = False

    # Storage
    STORAGE_BACKEND: str = "local"
    LOCAL_STORAGE_PATH: str = "./data"
    S3_BUCKET_NAME: str = ""
    S3_REGION: str = ""
    AWS_ACCESS_KEY_ID: str = ""
    AWS_SECRET_ACCESS_KEY: str = ""

    # Video
    NUM_CAMERAS: int = 5
    FRAME_WIDTH: int = 1280
    FRAME_HEIGHT: int = 720
    TARGET_FPS: int = 25
    PROCESSING_FPS: int = 5
    USE_GPU: bool = False

    # Scoring
    SCORE_PICK_ITEM: int = 10
    SCORE_HOLD_ITEM_PER_10S: int = 5
    SCORE_MULTI_ITEM: int = 10
    SCORE_AVOID_REGISTER: int = 15
    SCORE_MOVE_TO_EXIT: int = 20
    SCORE_RETURN_ITEM: int = -15
    SCORE_COMPLETE_CHECKOUT: int = -50
    SCORE_IDLE_PER_10S: int = -1
    THRESHOLD_WATCH: int = 31
    THRESHOLD_HIGH: int = 61

    # Alerts
    ALERT_CLIP_SECONDS_BEFORE: int = 10
    ALERT_CLIP_SECONDS_AFTER: int = 10

    # Notifications
    TWILIO_ACCOUNT_SID: str = ""
    TWILIO_AUTH_TOKEN: str = ""
    TWILIO_FROM_NUMBER: str = ""
    SENDGRID_API_KEY: str = ""
    ALERT_EMAIL_FROM: str = ""
    ALERT_EMAIL_TO: str = ""

    # Reports
    REPORT_GENERATION_HOUR: int = 23
    REPORT_GENERATION_MINUTE: int = 55

    @property
    def allowed_origins_list(self) -> List[str]:
        try:
            return json.loads(self.ALLOWED_ORIGINS)
        except Exception:
            return ["http://localhost:3000"]

    class Config:
        env_file = ".env"
        extra = "allow"


settings = Settings()
