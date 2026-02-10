import os
from dotenv import load_dotenv
from pathlib import Path

# Load environment variables from a stable project root.
PROJECT_ROOT = Path(__file__).parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def _as_bool(name: str, default: bool = False) -> bool:
	raw = os.getenv(name)
	if raw is None:
		return default
	return raw.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
	"""Application configuration loaded from environment variables."""

	# Core
	APP_NAME: str = os.getenv("APP_NAME", "Peptide Literature Extractor")
	ENV: str = os.getenv("ENV", "development")

	# Database
	DB_URL: str = os.getenv("DB_URL", "sqlite:///peptide_search.db")

	# LLM provider selection: 'mock' | 'openai' | 'openai-full' | 'openai-mini' | 'openai-nano' | 'deepseek'
	LLM_PROVIDER_RAW: str | None = os.getenv("LLM_PROVIDER")
	LLM_PROVIDER: str | None = LLM_PROVIDER_RAW.lower() if LLM_PROVIDER_RAW else None

	# DeepSeek
	DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
	DEEPSEEK_MODEL: str = os.getenv("DEEPSEEK_MODEL", "deepseek-chat")

	# OpenAI
	OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
	OPENAI_MODEL: str = os.getenv("OPENAI_MODEL", "gpt-4o")
	OPENAI_MODEL_MINI: str = os.getenv("OPENAI_MODEL_MINI", "gpt-5-mini")
	OPENAI_MODEL_NANO: str = os.getenv("OPENAI_MODEL_NANO", "gpt-5-nano")

	# Prompting config
	MAX_TOKENS: int = int(os.getenv("MAX_TOKENS", "2000"))
	TEMPERATURE: float = float(os.getenv("TEMPERATURE", "0.2"))

	# Definitions file (in-project) to include in the prompt
	DEFINITIONS_PATH: Path = PROJECT_ROOT / "Peptide LLM" / "definitions_for_llms.md"
	INCLUDE_DEFINITIONS: bool = os.getenv("INCLUDE_DEFINITIONS", "true").lower() == "true"

	# Static files directory
	STATIC_DIR: Path = PROJECT_ROOT / "public"

	# Queue settings
	QUEUE_CONCURRENCY: int = int(os.getenv("QUEUE_CONCURRENCY", "128"))
	QUEUE_CLAIM_TIMEOUT_SECONDS: int = int(os.getenv("QUEUE_CLAIM_TIMEOUT_SECONDS", "300"))
	QUEUE_MAX_ATTEMPTS: int = int(os.getenv("QUEUE_MAX_ATTEMPTS", "3"))
	QUEUE_ENGINE_VERSION: str = os.getenv("QUEUE_ENGINE_VERSION", "v2")

	# CORS
	CORS_ORIGINS: str = os.getenv("CORS_ORIGINS", "")

	# Access gate
	ACCESS_GATE_ENABLED: bool = _as_bool("ACCESS_GATE_ENABLED", False)
	ACCESS_GATE_USERNAME: str = os.getenv("ACCESS_GATE_USERNAME", "")
	ACCESS_GATE_PASSWORD: str = os.getenv("ACCESS_GATE_PASSWORD", "")

	def __init__(self) -> None:
		allowed = (
			"openai",
			"openai-full",
			"openai-mini",
			"openai-nano",
			"deepseek",
			"mock",
		)
		if not self.LLM_PROVIDER:
			raise RuntimeError(
				"LLM_PROVIDER is required. Set it to one of: "
				"openai, openai-full, openai-mini, openai-nano, deepseek, mock."
			)
		if self.LLM_PROVIDER not in allowed:
			raise RuntimeError(
				f"Unknown LLM_PROVIDER '{self.LLM_PROVIDER}'. "
				"Expected one of: openai, openai-full, openai-mini, openai-nano, deepseek, mock."
			)
		if self.QUEUE_ENGINE_VERSION not in {"v2"}:
			raise RuntimeError(
				f"Unsupported QUEUE_ENGINE_VERSION '{self.QUEUE_ENGINE_VERSION}'. Expected: v2."
			)
		if self.ACCESS_GATE_ENABLED and (
			not self.ACCESS_GATE_USERNAME or not self.ACCESS_GATE_PASSWORD
		):
			raise RuntimeError(
				"ACCESS_GATE_ENABLED=true requires ACCESS_GATE_USERNAME and ACCESS_GATE_PASSWORD."
			)


settings = Settings()
