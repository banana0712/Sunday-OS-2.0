"""
SundayOS — 你的甜心AI助手
简洁、温暖、可爱
"""
import os
from pydantic_settings import BaseSettings
from pydantic import Field


class Settings(BaseSettings):
    """SundayOS 全局配置"""

    app_name: str = "SundayOS"
    app_version: str = "2.0.0"
    debug: bool = Field(default=False, alias="DEBUG")

    # API 安全
    api_key: str = Field(default="sunday-2026", alias="SUNDAY_API_KEY")

    # 豆包(火山引擎)
    llm_api_key: str = Field(default="", alias="LLM_API_KEY")
    llm_model: str = Field(default="doubao-seed-2-0-pro-260215", alias="LLM_MODEL")
    llm_model_pro: str = Field(default="", alias="LLM_MODEL_PRO")
    llm_temperature: float = Field(default=0.8, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=1500, alias="LLM_MAX_TOKENS")

    @property
    def base_url(self) -> str:
        return "https://ark.cn-beijing.volces.com/api/v3"

    # Sunday 人设
    assistant_name: str = Field(default="Sunday", alias="ASSISTANT_NAME")
    assistant_personality: str = Field(
        default="",
        alias="ASSISTANT_PERSONALITY",
    )

    # 邮件推送（Resend HTTP API）
    resend_api_key: str = Field(default="", alias="RESEND_API_KEY")
    resend_from_email: str = Field(default="", alias="RESEND_FROM_EMAIL")
    push_email: str = Field(default="", alias="PUSH_EMAIL")

    # IMAP 接收邮件（iCloud 实时监听）
    imap_password: str = Field(default="", alias="IMAP_PASSWORD")

    # Telegram Bot
    telegram_token: str = Field(default="", alias="TELEGRAM_TOKEN")

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


settings = Settings()
