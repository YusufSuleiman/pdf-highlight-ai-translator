"""Application settings and configuration management."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from pdfhl_trans.utils.logger import get_logger

logger = get_logger("config.settings")

DEFAULT_CONFIG_DIR = Path.home() / ".config" / "pdfhl-trans"
CONFIG_FILENAME = "config.json"


class ConfigurationError(Exception):
    """Raised when required configuration is missing or invalid."""


class AppConfig(BaseModel):
    """Unified configuration for pdfhl-trans.
    
    Combines persistent user preferences (saved to JSON) with ephemeral 
    runtime arguments (like paths and debug flags).
    """

    # ── Persistent Settings ────────────────────────────────────────────
    api_key: str = Field(default="")
    default_language: str = Field(default="ar")
    default_context_sentences: int = Field(default=2)
    gemini_model: str = Field(default="gemini-2.0-flash")

    # ── Runtime Arguments ──────────────────────────────────────────────
    pdf_path: Path | None = Field(default=None, exclude=True)
    output_path: Path | None = Field(default=None, exclude=True)
    target_language: str | None = Field(default=None, exclude=True)
    context_sentences: int | None = Field(default=None, exclude=True)
    target_colors: list[str] | None = Field(default=None, exclude=True)
    
    cache_dir: Path = Field(
        default_factory=lambda: Path.home() / ".pdfhl_trans", exclude=True
    )
    verbose: bool = Field(default=False, exclude=True)
    debug: bool = Field(default=False, exclude=True)

    def resolve_output_path(self) -> Path:
        """Return the resolved, absolute output path based on pdf_path if missing."""
        if self.output_path is not None:
            return self.output_path.resolve()
        if self.pdf_path is not None:
            stem = self.pdf_path.stem
            suffix = self.pdf_path.suffix or ".pdf"
            return (self.pdf_path.parent / f"{stem}_translated{suffix}").resolve()
        raise ConfigurationError("No PDF path or output path provided.")

    # ── Configuration Management ───────────────────────────────────────

    @classmethod
    def load(cls, config_dir: Path | None = None) -> AppConfig:
        """Load persistent configuration from the JSON file.

        Args:
            config_dir: Optional override for the config directory.

        Returns:
            A new AppConfig instance populated from disk.
        """
        config_dir = config_dir or DEFAULT_CONFIG_DIR
        config_path = config_dir / CONFIG_FILENAME

        data: dict[str, Any] = {}
        if config_path.exists():
            try:
                raw = config_path.read_text(encoding="utf-8")
                data = json.loads(raw)
                logger.debug("Loaded config from %s", config_path)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Failed to read config file: %s", exc)

        # Environment variable overrides
        env_key = os.environ.get("GEMINI_API_KEY")
        if env_key:
            data["api_key"] = env_key

        return cls(**data)

    def save(self, config_dir: Path | None = None) -> None:
        """Save persistent configuration to the JSON file."""
        config_dir = config_dir or DEFAULT_CONFIG_DIR
        config_path = config_dir / CONFIG_FILENAME

        try:
            config_dir.mkdir(parents=True, exist_ok=True)
            # Dump only fields not marked `exclude=True`
            json_data = self.model_dump_json(indent=2)
            config_path.write_text(json_data + "\n", encoding="utf-8")
        except OSError as exc:
            logger.error("Failed to save config: %s", exc)

    def is_configured(self) -> bool:
        """Check whether an API key is available."""
        env_key = os.environ.get("GEMINI_API_KEY")
        return bool(env_key or self.api_key)

    def get_active_api_key(self) -> str:
        """Return the active API key, preferring environment over stored."""
        env_key = os.environ.get("GEMINI_API_KEY")
        return env_key or self.api_key

    def get_masked_key(self) -> str:
        """Return the API key with middle characters masked for display."""
        key = self.get_active_api_key()
        if not key:
            return "(not set)"
        if len(key) <= 8:
            return key[:2] + "***" + key[-2:]
        return key[:4] + "..." + key[-4:]
