"""Gemini-powered contextual translation backend."""

from __future__ import annotations

import re
import time

from google import genai

from pdfhl_trans.translation.base_translator import BaseTranslator
from pdfhl_trans.utils.logger import get_logger

logger = get_logger("translation.gemini")

_MAX_RETRIES = 3
_BASE_DELAY = 2.0  # seconds, minimum backoff
_MAX_DELAY = 60.0  # cap the wait to avoid very long hangs

# Regex to parse the suggested retry delay from the API error message
_RETRY_DELAY_RE = re.compile(r"retry.*?(\d+(?:\.\d+)?)s", re.IGNORECASE)


class GeminiTranslationError(Exception):
    """Raised when Gemini translation fails after retries."""


class GeminiQuotaExhaustedError(GeminiTranslationError):
    """Raised when the daily/project API quota is fully exhausted."""


class GeminiTranslator(BaseTranslator):
    """Translates text using the Google Gemini API with contextual prompting.

    The prompt includes surrounding sentences so that Gemini can produce
    an accurate, context-aware translation, but instructs the model to
    return **only** the translation of the highlighted text.

    Implements smart retry logic that honours the ``retryDelay`` suggested
    by the API response, and detects daily quota exhaustion early to avoid
    wasting retry attempts.
    """

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash") -> None:
        """Initialise the Gemini translator.

        Args:
            api_key: Google Gemini API key.
            model: Model identifier (default: ``gemini-2.0-flash``).
        """
        self._client = genai.Client(api_key=api_key)
        self._model = model

    def translate(
        self,
        text: str,
        context_before: str,
        context_after: str,
        target_language: str,
    ) -> str:
        """Translate highlighted text with contextual awareness.

        Args:
            text: The exact highlighted text to translate.
            context_before: Preceding context sentences.
            context_after: Following context sentences.
            target_language: Target language code (e.g. ``ar``).

        Returns:
            The translated text.

        Raises:
            GeminiQuotaExhaustedError: If the daily/project quota is exhausted.
            GeminiTranslationError: If all retry attempts fail.
        """
        prompt = self._build_prompt(text, context_before, context_after, target_language)
        logger.debug("Prompt:\n%s", prompt)

        last_error: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._client.models.generate_content(
                    model=self._model,
                    contents=prompt,
                )
                result = (response.text or "").strip()
                if not result:
                    raise GeminiTranslationError("Gemini returned an empty response")
                logger.debug("Translation result: %s", result)
                return result

            except GeminiTranslationError:
                raise
            except Exception as exc:
                error_str = str(exc)
                last_error = exc

                # Detect daily quota exhaustion — do NOT retry, it won't help
                if self._is_daily_quota_exhausted(error_str):
                    raise GeminiQuotaExhaustedError(
                        "Daily API quota exhausted for this key/project.\n"
                        "Your free-tier limit has been reached for today.\n"
                        "Solutions:\n"
                        "  • Wait until tomorrow (quota resets daily)\n"
                        "  • Use a different API key (option 3 in the menu)\n"
                        "  • Try model 'gemini-1.5-flash' which may have\n"
                        "    a separate quota (option 4 → Gemini model)"
                    ) from exc

                # For rate limits (per-minute), honour the suggested delay
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    api_delay = self._parse_retry_delay(error_str)
                    delay = min(max(api_delay, _BASE_DELAY * attempt), _MAX_DELAY)
                else:
                    delay = _BASE_DELAY * (2 ** (attempt - 1))

                logger.warning(
                    "Gemini API attempt %d/%d failed: %.80s — retrying in %.1fs",
                    attempt,
                    _MAX_RETRIES,
                    error_str,
                    delay,
                )
                time.sleep(delay)

        raise GeminiTranslationError(
            f"Translation failed after {_MAX_RETRIES} attempts. "
            f"Last error: {last_error}"
        )

    @staticmethod
    def _is_daily_quota_exhausted(error_str: str) -> bool:
        """Check if the error indicates a daily (non-recoverable) quota limit.

        A per-minute rate limit is recoverable by waiting; a daily or
        project-level quota exhaustion is not recoverable within the session.

        Args:
            error_str: String representation of the API error.

        Returns:
            True if the daily quota is exhausted.
        """
        return (
            "PerDay" in error_str
            and "RESOURCE_EXHAUSTED" in error_str
        )

    @staticmethod
    def _parse_retry_delay(error_str: str) -> float:
        """Extract the ``retryDelay`` seconds suggested by the API error.

        Args:
            error_str: String representation of the API error.

        Returns:
            Suggested delay in seconds, or 0.0 if not found.
        """
        match = _RETRY_DELAY_RE.search(error_str)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return 0.0

    @staticmethod
    def _build_prompt(
        text: str,
        context_before: str,
        context_after: str,
        target_language: str,
    ) -> str:
        """Build the contextual translation prompt.

        Args:
            text: Highlighted text.
            context_before: Sentences before the highlight.
            context_after: Sentences after the highlight.
            target_language: Target language code.

        Returns:
            The full prompt string.
        """
        parts: list[str] = [
            "You are a professional translator. Your task is to translate "
            "ONLY the highlighted text below into the target language.",
            "",
            f"Target language: {target_language}",
            "",
        ]

        if context_before:
            parts.append("=== Context BEFORE the highlighted text ===")
            parts.append(context_before)
            parts.append("")

        parts.append("=== HIGHLIGHTED TEXT (translate this) ===")
        parts.append(text)
        parts.append("")

        if context_after:
            parts.append("=== Context AFTER the highlighted text ===")
            parts.append(context_after)
            parts.append("")

        parts.extend([
            "=== INSTRUCTIONS ===",
            "1. Use the surrounding context to understand meaning and nuance.",
            "2. Translate ONLY the highlighted text — do NOT translate the context.",
            "3. Return ONLY the translation, nothing else.",
            "4. Do NOT include explanations, notes, quotation marks, or labels.",
            "5. Preserve the original formatting and structure.",
        ])

        return "\n".join(parts)
