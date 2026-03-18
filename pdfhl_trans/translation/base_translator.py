"""Abstract base class for translation backends."""

from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTranslator(ABC):
    """Interface that all translation backends must implement.

    Subclasses provide a concrete ``translate`` method that accepts
    highlighted text with surrounding context and returns the translated
    string for the highlight only.
    """

    @abstractmethod
    def translate(
        self,
        text: str,
        context_before: str,
        context_after: str,
        target_language: str,
    ) -> str:
        """Translate the given text using context for accuracy.

        Args:
            text: The exact highlighted text to translate.
            context_before: Surrounding sentences before the highlight.
            context_after: Surrounding sentences after the highlight.
            target_language: Target language code (e.g. ``ar``, ``fr``).

        Returns:
            The translated text (only the highlighted portion).
        """
        ...
