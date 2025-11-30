import os
import logging
from pathlib import Path
from pydantic import field_validator
from pydantic_settings import BaseSettings
from dotenv import load_dotenv
from typing import Optional

# Load environment variables from .env file
load_dotenv()

BASE_DIR = Path(__file__).parent

class Settings(BaseSettings):
    # Bot configuration
    BOT_TOKEN: str
    ADMIN_IDS: list[int]  # List of admin user IDs
    
    # Database
    DATABASE_URL: str = f"sqlite:///{BASE_DIR / 'data' / 'santa.db'}"
    
    # Logging
    LOG_LEVEL: str = "INFO"
    LOG_FILE: Optional[str] = "logs/bot.log"
    LOG_FORMAT: str = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    LOG_MAX_SIZE: int = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT: int = 5
    
    @field_validator('ADMIN_IDS', mode='before')
    @classmethod
    def parse_admin_ids(cls, v):
        if isinstance(v, (int, float)):
            return [int(v)]
        if isinstance(v, str):
            # Remove any whitespace and filter out empty strings
            return [int(admin_id.strip()) for admin_id in v.split(',') if admin_id.strip()]
        if isinstance(v, list):
            return [int(admin_id) for admin_id in v]
        return v

    class Config:
        env_file = '.env'
        extra = 'ignore'

# Create settings instance
settings = Settings()
