"""
SundayOS 配置管理
管理所有环境变量和应用配置

支持的 LLM 供应商:
  - ling_studio  : 蚂蚁 Ling Studio（推荐，50万token/天免费，OpenAI兼容）
  - dashscope    : 阿里通义千问（2000次/天免费）
  - openai       : OpenAI 官方（需付费）
  - custom       : 自定义 OpenAI 兼容 API
"""
import os
from typing import Optional, Literal
from pydantic_settings import BaseSettings
from pydantic import Field

# LLM 供应商类型
LLMProvider = Literal["ling_studio", "dashscope", "openai", "custom"]


class Settings(BaseSettings):
    """SundayOS 全局配置"""

    # ========== 应用配置 ==========
    app_name: str = "SundayOS"
    app_version: str = "0.1.0"
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    # ========== API 安全 ==========
    api_key: str = Field(
        default="sunday-os-dev-key-change-in-production",
        alias="SUNDAY_API_KEY",
    )
    cors_origins: list[str] = Field(
        default=["*"],
        alias="CORS_ORIGINS",
    )

    # ========== LLM 供应商配置 ==========
    llm_provider: str = Field(
        default="ling_studio",
        alias="LLM_PROVIDER",
        description="LLM 供应商: ling_studio / dashscope / openai / custom",
    )
    llm_api_key: str = Field(
        default="",
        alias="LLM_API_KEY",
        description="LLM API Key（所有供应商通用此字段）",
    )
    llm_model: str = Field(
        default="Ling-1T",
        alias="LLM_MODEL",
        description="模型名称，根据供应商自动设置默认值",
    )
    llm_base_url: str = Field(
        default="",
        alias="LLM_BASE_URL",
        description="自定义 API Base URL（仅 custom 模式必填）",
    )
    llm_temperature: float = Field(default=0.7, alias="LLM_TEMPERATURE")
    llm_max_tokens: int = Field(default=2000, alias="LLM_MAX_TOKENS")

    # ========== 各供应商预设配置 ==========
    @property
    def provider_config(self) -> dict:
        """根据 llm_provider 返回对应的 API 配置"""
        configs = {
            "ling_studio": {
                "base_url": "https://api.ant-ling.com/v1/",
                "default_model": "Ling-2.6-1T",
                "description": "蚂蚁百灵 — 50万token/天免费，OpenAI兼容",
            },
            "dashscope": {
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "default_model": "qwen-plus",
                "description": "阿里通义千问 — 2000次/天免费，OpenAI兼容模式",
            },
            "openai": {
                "base_url": "https://api.openai.com/v1",
                "default_model": "gpt-4o-mini",
                "description": "OpenAI 官方 — 需付费",
            },
            "custom": {
                "base_url": self.llm_base_url,
                "default_model": self.llm_model or "gpt-3.5-turbo",
                "description": "自定义 OpenAI 兼容 API",
            },
        }
        return configs.get(self.llm_provider, configs["ling_studio"])

    @property
    def effective_base_url(self) -> str:
        """获取实际使用的 Base URL"""
        if self.llm_provider == "custom":
            return self.llm_base_url
        return self.provider_config["base_url"]

    @property
    def effective_model(self) -> str:
        """获取实际使用的模型名"""
        if self.llm_model:
            return self.llm_model
        return self.provider_config["default_model"]

    # ========== 记忆系统配置 ==========
    mem0_api_key: str = Field(default="", alias="MEM0_API_KEY")
    chromadb_host: str = Field(default="localhost", alias="CHROMADB_HOST")
    chromadb_port: int = Field(default=8000, alias="CHROMADB_PORT")
    chromadb_persist_dir: str = Field(
        default="./chroma_data", alias="CHROMADB_PERSIST_DIR"
    )

    # ========== PostgreSQL 配置 ==========
    database_url: str = Field(
        default="postgresql+asyncpg://sunday:sunday@localhost:5432/sundayos",
        alias="DATABASE_URL",
    )
    database_url_sync: str = Field(
        default="postgresql://sunday:sunday@localhost:5432/sundayos",
        alias="DATABASE_URL_SYNC",
    )

    # ========== Redis 配置 ==========
    redis_url: str = Field(default="redis://localhost:6379/0", alias="REDIS_URL")

    # ========== 语音服务配置 ==========
    whisper_api_key: str = Field(default="", alias="WHISPER_API_KEY")
    tts_provider: str = Field(default="edge", alias="TTS_PROVIDER")
    elevenlabs_api_key: str = Field(default="", alias="ELEVENLABS_API_KEY")
    elevenlabs_voice_id: str = Field(
        default="21m00Tcm4TlvDq8ikWAM", alias="ELEVENLABS_VOICE_ID"
    )

    # ========== 用户画像配置 ==========
    user_profile_max_history: int = Field(
        default=100, alias="USER_PROFILE_MAX_HISTORY"
    )
    memory_decay_days: int = Field(
        default=30, alias="MEMORY_DECAY_DAYS"
    )
    memory_importance_threshold: float = Field(
        default=0.5, alias="MEMORY_IMPORTANCE_THRESHOLD"
    )

    # ========== 技能配置 ==========
    weather_api_key: str = Field(default="", alias="WEATHER_API_KEY")
    search_api_key: str = Field(default="", alias="SEARCH_API_KEY")

    # ========== SundayOS 人格配置 ==========
    assistant_name: str = Field(default="Sunday", alias="ASSISTANT_NAME")
    assistant_personality: str = Field(
        default="你是一个温暖、专业、偶尔幽默的AI助手。你的名字是Sunday。"
                "你像朋友一样与用户交流，简洁直接但充满关怀。"
                "你会记住用户的偏好和习惯，主动提供帮助。"
                "你的核心价值是效率优先、主动关怀、尊重隐私。",
        alias="ASSISTANT_PERSONALITY",
    )

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"
        case_sensitive = False


# 全局单例
settings = Settings()
