import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from .env if present
load_dotenv()


class Settings:
	"""Application configuration loaded from environment variables."""

	# Core
	APP_NAME: str = os.getenv("APP_NAME", "Peptide Literature Extractor")
	ENV: str = os.getenv("ENV", "development")

	# Database
	DB_URL: str = os.getenv("DB_URL", "sqlite:///peptide_search.db")

	# LLM provider selection: 'mock' | 'openai' | 'deepseek'
	LLM_PROVIDER: str = os.getenv("LLM_PROVIDER", "mock").lower()

	# DeepSeek
	DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
	DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

	# OpenAI
	OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
	OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")

	# Prompting config
	MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2000"))
	TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.2"))

	# Definitions file (in-project) to include in the prompt
	DEFINITIONS_PATH: Path = Path(__file__).parent.parent / "Peptide LLM" / "definitions_for_llms.md"
	INCLUDE_DEFINITIONS: bool = os.getenv("INCLUDE_DEFINITIONS", "true").lower() == "true"

	# Static files directory
	STATIC_DIR: Path = Path(__file__).parent.parent / "public"

	# Queue settings
	QUEUE_CONCURRENCY: int = int(os.getenv("QUEUE_CONCURRENCY", "3"))

	# CORS
	CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")


settings = Settings()


