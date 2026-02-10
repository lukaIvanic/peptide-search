"""Provider registry, alias resolution, and model catalog/discovery."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from ...config import settings
from .base import LLMCapabilities, LLMProvider
from .deepseek import DeepSeekProvider
from .gemini import GeminiProvider
from .mock import MockProvider
from .openai import OpenAIProvider
from .openrouter import OpenRouterProvider


@dataclass(frozen=True)
class ProviderSelection:
    provider_id: str
    model_id: str
    alias_used: Optional[str] = None


@dataclass(frozen=True)
class ProviderDescriptor:
    provider_id: str
    label: str
    required_key_env: Optional[str]
    capabilities: LLMCapabilities
    default_model: str
    curated_models: List[str]
    supports_custom_model: bool
    supports_model_discovery: bool


@dataclass(frozen=True)
class ProviderRefreshWarning:
    provider_id: str
    message: str


class ProviderSelectionError(ValueError):
    def __init__(self, message: str, *, details: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(message)
        self.details = details or {}


_MODEL_CACHE: Dict[str, Dict[str, Any]] = {}


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _iso_z(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _unique_non_empty(values: List[Optional[str]]) -> List[str]:
    output: List[str] = []
    seen: set[str] = set()
    for value in values:
        if value is None:
            continue
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        output.append(normalized)
    return output


def _descriptors() -> Dict[str, ProviderDescriptor]:
    return {
        "openai": ProviderDescriptor(
            provider_id="openai",
            label="OpenAI",
            required_key_env="OPENAI_API_KEY",
            capabilities=LLMCapabilities(
                supports_pdf_url=True,
                supports_pdf_file=True,
                supports_json_mode=True,
            ),
            default_model=settings.OPENAI_MODEL,
            curated_models=_unique_non_empty(
                [settings.OPENAI_MODEL, settings.OPENAI_MODEL_MINI, settings.OPENAI_MODEL_NANO]
            ),
            supports_custom_model=True,
            supports_model_discovery=False,
        ),
        "deepseek": ProviderDescriptor(
            provider_id="deepseek",
            label="DeepSeek",
            required_key_env="DEEPSEEK_API_KEY",
            capabilities=LLMCapabilities(
                supports_pdf_url=False,
                supports_pdf_file=False,
                supports_json_mode=True,
            ),
            default_model=settings.DEEPSEEK_MODEL,
            curated_models=_unique_non_empty([settings.DEEPSEEK_MODEL]),
            supports_custom_model=True,
            supports_model_discovery=False,
        ),
        "gemini": ProviderDescriptor(
            provider_id="gemini",
            label="Gemini",
            required_key_env="GEMINI_API_KEY",
            capabilities=LLMCapabilities(
                supports_pdf_url=False,
                supports_pdf_file=True,
                supports_json_mode=True,
            ),
            default_model=settings.GEMINI_MODEL,
            curated_models=_unique_non_empty([settings.GEMINI_MODEL]),
            supports_custom_model=True,
            supports_model_discovery=True,
        ),
        "openrouter": ProviderDescriptor(
            provider_id="openrouter",
            label="OpenRouter",
            required_key_env="OPENROUTER_API_KEY",
            capabilities=LLMCapabilities(
                supports_pdf_url=True,
                supports_pdf_file=True,
                supports_json_mode=True,
            ),
            default_model=settings.OPENROUTER_MODEL,
            curated_models=_unique_non_empty([settings.OPENROUTER_MODEL]),
            supports_custom_model=True,
            supports_model_discovery=True,
        ),
        "mock": ProviderDescriptor(
            provider_id="mock",
            label="Mock",
            required_key_env=None,
            capabilities=LLMCapabilities(
                supports_pdf_url=True,
                supports_pdf_file=True,
                supports_json_mode=True,
            ),
            default_model="mock-model",
            curated_models=["mock-model"],
            supports_custom_model=False,
            supports_model_discovery=False,
        ),
    }


def _alias_defaults() -> Dict[str, tuple[str, str]]:
    return {
        "openai-full": ("openai", settings.OPENAI_MODEL),
        "openai-mini": ("openai", settings.OPENAI_MODEL_MINI),
        "openai-nano": ("openai", settings.OPENAI_MODEL_NANO),
    }


def supported_provider_ids() -> List[str]:
    descriptors = _descriptors()
    aliases = _alias_defaults()
    return sorted(set(list(descriptors.keys()) + list(aliases.keys())))


def provider_enabled(provider_id: str) -> bool:
    descriptor = _descriptors().get(provider_id)
    if not descriptor:
        return False
    if not descriptor.required_key_env:
        return True
    key_value = getattr(settings, descriptor.required_key_env, None)
    return bool(key_value and str(key_value).strip())


def _resolve_provider_alias(raw_provider: str) -> tuple[str, Optional[str]]:
    key = (raw_provider or "").strip().lower()
    aliases = _alias_defaults()
    if key in aliases:
        canonical, alias_default_model = aliases[key]
        return canonical, alias_default_model
    return key, None


def resolve_provider_selection(
    *,
    provider: Optional[str],
    model: Optional[str] = None,
    default_provider: Optional[str] = None,
    require_enabled: bool = True,
) -> ProviderSelection:
    requested = (provider or default_provider or settings.LLM_PROVIDER or "").strip().lower()
    if not requested:
        raise ProviderSelectionError(
            "LLM provider is required.",
            details={"supported_providers": supported_provider_ids(), "hint": "/api/providers"},
        )

    canonical, alias_default_model = _resolve_provider_alias(requested)
    descriptors = _descriptors()
    descriptor = descriptors.get(canonical)
    if not descriptor:
        raise ProviderSelectionError(
            f"Unknown provider '{requested}'.",
            details={"supported_providers": supported_provider_ids(), "hint": "/api/providers"},
        )

    if require_enabled and not provider_enabled(canonical):
        env_name = descriptor.required_key_env
        raise ProviderSelectionError(
            f"Provider '{canonical}' is disabled because required credentials are missing.",
            details={"required_env": env_name, "hint": "/api/providers"},
        )

    explicit_model = (model or "").strip() or None
    resolved_model = explicit_model or alias_default_model or descriptor.default_model
    if not resolved_model:
        raise ProviderSelectionError(
            f"No model configured for provider '{canonical}'.",
            details={"provider_id": canonical, "hint": "/api/providers"},
        )

    if explicit_model and not descriptor.supports_custom_model:
        curated = set(descriptor.curated_models)
        if explicit_model not in curated:
            raise ProviderSelectionError(
                f"Provider '{canonical}' does not support custom model IDs.",
                details={
                    "provider_id": canonical,
                    "supported_models": descriptor.curated_models,
                    "hint": "/api/providers",
                },
            )

    return ProviderSelection(
        provider_id=canonical,
        model_id=resolved_model,
        alias_used=requested if requested != canonical else None,
    )


def create_provider(selection: ProviderSelection) -> LLMProvider:
    if selection.provider_id == "openai":
        return OpenAIProvider(
            provider_name=selection.provider_id,
            model=selection.model_id,
        )
    if selection.provider_id == "deepseek":
        return DeepSeekProvider(model=selection.model_id)
    if selection.provider_id == "gemini":
        return GeminiProvider(
            provider_name=selection.provider_id,
            model=selection.model_id,
        )
    if selection.provider_id == "openrouter":
        return OpenRouterProvider(
            provider_name=selection.provider_id,
            model=selection.model_id,
        )
    if selection.provider_id == "mock":
        return MockProvider(model=selection.model_id)
    raise ProviderSelectionError(
        f"Unsupported provider '{selection.provider_id}'.",
        details={"supported_providers": supported_provider_ids(), "hint": "/api/providers"},
    )


def provider_catalog() -> Dict[str, Any]:
    descriptors = _descriptors()
    entries: List[Dict[str, Any]] = []
    ttl = int(getattr(settings, "PROVIDER_MODEL_CACHE_TTL_SECONDS", 900))
    for provider_id in sorted(descriptors.keys()):
        descriptor = descriptors[provider_id]
        cache_entry = _MODEL_CACHE.get(provider_id) or {}
        discovered_models = cache_entry.get("discovered_models") or []
        merged = _unique_non_empty(list(descriptor.curated_models) + list(discovered_models))
        entries.append(
            {
                "provider_id": descriptor.provider_id,
                "label": descriptor.label,
                "enabled": provider_enabled(descriptor.provider_id),
                "capabilities": {
                    "supports_pdf_url": descriptor.capabilities.supports_pdf_url,
                    "supports_pdf_file": descriptor.capabilities.supports_pdf_file,
                    "supports_json_mode": descriptor.capabilities.supports_json_mode,
                },
                "default_model": descriptor.default_model,
                "curated_models": merged,
                "supports_custom_model": descriptor.supports_custom_model,
                "supports_model_discovery": descriptor.supports_model_discovery,
                "cache_ttl_seconds": ttl,
                "last_refreshed_at": _iso_z(cache_entry.get("last_refreshed_at")),
            }
        )
    return {"providers": entries}


def _is_cache_fresh(provider_id: str) -> bool:
    ttl_seconds = int(getattr(settings, "PROVIDER_MODEL_CACHE_TTL_SECONDS", 900))
    if ttl_seconds <= 0:
        return False
    entry = _MODEL_CACHE.get(provider_id) or {}
    last = entry.get("last_refreshed_at")
    if not isinstance(last, datetime):
        return False
    return (_now_utc() - last) <= timedelta(seconds=ttl_seconds)


async def _discover_openrouter_models(api_key: str) -> List[str]:
    headers = {"Authorization": f"Bearer {api_key}"}
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
    if resp.status_code != 200:
        raise RuntimeError(f"OpenRouter model discovery failed ({resp.status_code})")
    data = resp.json()
    models = data.get("data", [])
    output: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if isinstance(model_id, str) and model_id.strip():
            output.append(model_id.strip())
    return _unique_non_empty(output)


async def _discover_gemini_models(api_key: str) -> List[str]:
    endpoint = f"https://generativelanguage.googleapis.com/v1beta/models?key={api_key}"
    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.get(endpoint)
    if resp.status_code != 200:
        raise RuntimeError(f"Gemini model discovery failed ({resp.status_code})")
    data = resp.json()
    models = data.get("models", [])
    output: List[str] = []
    for item in models:
        if not isinstance(item, dict):
            continue
        methods = item.get("supportedGenerationMethods") or []
        if methods and "generateContent" not in methods:
            continue
        raw_name = item.get("name")
        if not isinstance(raw_name, str):
            continue
        name = raw_name.strip()
        if not name:
            continue
        if name.startswith("models/"):
            name = name.split("/", 1)[1]
        output.append(name)
    return _unique_non_empty(output)


async def refresh_provider_models(*, force: bool = False) -> Dict[str, Any]:
    warnings: List[ProviderRefreshWarning] = []
    descriptors = _descriptors()
    for provider_id, descriptor in descriptors.items():
        if not descriptor.supports_model_discovery:
            continue
        if not force and _is_cache_fresh(provider_id):
            continue
        if not provider_enabled(provider_id):
            warnings.append(
                ProviderRefreshWarning(
                    provider_id=provider_id,
                    message="Provider is disabled; skipped model discovery.",
                )
            )
            continue

        try:
            if provider_id == "openrouter":
                discovered = await _discover_openrouter_models(settings.OPENROUTER_API_KEY or "")
            elif provider_id == "gemini":
                discovered = await _discover_gemini_models(settings.GEMINI_API_KEY or "")
            else:
                discovered = []
            _MODEL_CACHE[provider_id] = {
                "discovered_models": discovered,
                "last_refreshed_at": _now_utc(),
            }
        except Exception as exc:
            warnings.append(
                ProviderRefreshWarning(
                    provider_id=provider_id,
                    message=str(exc),
                )
            )
    payload = provider_catalog()
    payload["warnings"] = [
        {"provider_id": item.provider_id, "message": item.message} for item in warnings
    ]
    return payload
