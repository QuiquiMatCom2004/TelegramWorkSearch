from pydantic_settings import BaseSettings
from pydantic import Field, field_validator
from typing import Optional
import os


class Settings(BaseSettings):
    # Telegram API
    telegram_api_id: int = Field(..., description="Telegram API ID from my.telegram.org")
    telegram_api_hash: str = Field(..., description="Telegram API Hash from my.telegram.org")
    telegram_session_name: str = "telegram_job_search"
    telegram_phone: str = Field(default="", description="Phone number for Telegram login")

    # OpenRouter
    openrouter_api_key: str = Field(..., description="OpenRouter API key")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-3.5-sonnet"
    llm_temperature: float = 0.3

    # Database
    database_url: str = Field(
        default="postgresql+asyncpg://user:pass@localhost/telegram_jobs",
        description="PostgreSQL connection URL"
    )

    # Job Search Channels (space-separated in .env)
    job_channels_str: str = Field(
        default="",
        description="Space-separated list of channel usernames or IDs to monitor",
        alias="JOB_CHANNELS"
    )

    @property
    def job_channels(self) -> list[str]:
        return self.job_channels_str.split() if self.job_channels_str else []

    # Classification
    user_profile: str = Field(
        default="",
        description="Your profile: skills, experience, preferences for job matching"
    )
    min_relevance_score: float = 0.7

    # Scheduler
    fetch_interval_minutes: int = 30

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        extra = "allow"


settings = Settings()