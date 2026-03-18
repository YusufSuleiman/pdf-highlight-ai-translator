"""Orchestrates the full PDF highlight → translate → annotate pipeline."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import fitz  # PyMuPDF

from pdfhl_trans.cache.translation_cache import TranslationCache
from pdfhl_trans.config.settings import AppConfig
from pdfhl_trans.core.annotation_writer import AnnotationWriter
from pdfhl_trans.core.highlight_extractor import HighlightData, HighlightExtractor
from pdfhl_trans.translation.base_translator import BaseTranslator
from pdfhl_trans.translation.gemini_translator import GeminiQuotaExhaustedError
from pdfhl_trans.utils.logger import get_logger

# Type alias for the progress callback
_ProgressCallback = Callable[[int, int, int, HighlightData], None]

logger = get_logger("core.pdf_processor")


@dataclass
class ProcessingResult:
    """Statistics and output from a single PDF processing run.

    Attributes:
        total_highlights: Number of highlights found.
        translated: Number of new translations performed.
        cached: Number of translations retrieved from cache.
        failed: Number of highlights that failed to translate.
        output_path: Path where the modified PDF was saved.
        highlights: List of all extracted highlight data.
        translations: Mapping of original text to translations.
    """

    total_highlights: int = 0
    absolute_total_highlights: int = 0
    translated: int = 0
    cached: int = 0
    failed: int = 0
    output_path: Path | None = None
    highlights: list[HighlightData] = field(default_factory=list)
    translations: dict[str, str] = field(default_factory=dict)


class PDFProcessor:
    """Orchestrates the highlight extraction and translation pipeline."""

    def __init__(
        self,
        translator: BaseTranslator,
        cache: TranslationCache,
        settings: AppConfig,
    ) -> None:
        """Initialise the processor with its dependencies.

        Args:
            translator: Translation backend to use.
            cache: Translation cache instance.
            settings: Application settings.
        """
        self._translator = translator
        self._cache = cache
        self._settings = settings
        self._extractor = HighlightExtractor(
            context_sentences=settings.context_sentences,
        )
        self._writer = AnnotationWriter()

    def extract_highlights(self, pdf_path: Path) -> list[HighlightData]:
        """Extract highlights from a PDF without processing them.

        Args:
            pdf_path: Path to the PDF file.

        Returns:
            List of extracted highlight data.

        Raises:
            FileNotFoundError: If the PDF does not exist.
            RuntimeError: If the PDF cannot be opened.
        """
        self._validate_pdf(pdf_path)
        doc = fitz.open(str(pdf_path))
        try:
            return self._extractor.extract_highlights(doc)
        finally:
            doc.close()

    def process(
        self,
        pdf_path: Path,
        progress_callback: _ProgressCallback | None = None,
    ) -> ProcessingResult:
        """Run the full extraction → translation → annotation pipeline.

        Args:
            pdf_path: Path to the input PDF file.
            progress_callback: Optional callable invoked for each highlight,
                               signature: ``(current: int, filtered_total: int, absolute_total: int, highlight: HighlightData) -> None``.

        Returns:
            A :class:`ProcessingResult` with statistics and data.

        Raises:
            FileNotFoundError: If the PDF does not exist.
            RuntimeError: If the PDF cannot be opened or saved.
        """
        self._validate_pdf(pdf_path)

        doc = fitz.open(str(pdf_path))
        try:
            highlights = self._extractor.extract_highlights(doc)
            result = ProcessingResult(
                total_highlights=len(highlights),
                output_path=self._settings.resolve_output_path(),
                highlights=highlights,
            )

            if not highlights:
                logger.warning("No highlights found in %s", pdf_path.name)
                return result

            import concurrent.futures

            # Filter highlights by color if requested
            target_colors = self._settings.target_colors
            if target_colors:
                target_colors_upper = [c.upper() for c in target_colors]
                filtered_highlights = [
                    hl for hl in highlights if hl.color.upper() in target_colors_upper
                ]
                logger.info(
                    "Filtered highlights down to %d (matching colors: %s)",
                    len(filtered_highlights),
                    ", ".join(target_colors),
                )
            else:
                filtered_highlights = highlights
                
            absolute_total = len(highlights)
            filtered_total = len(filtered_highlights)
            result.total_highlights = filtered_total
            result.absolute_total_highlights = absolute_total

            futures = {}
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                for hl in filtered_highlights:
                    futures[executor.submit(self._translate_highlight, hl)] = hl

                for idx, future in enumerate(concurrent.futures.as_completed(futures), start=1):
                    hl = futures[future]
                    try:
                        translation = future.result()
                    except Exception as exc:
                        logger.error("Translation thread failed: %s", exc, exc_info=True)
                        translation = None

                    if progress_callback:
                        # The text displayed will be randomly ordered as they complete, which is fine
                        progress_callback(idx, filtered_total, absolute_total, hl)

                    if translation:
                        self._writer.write_translation(doc, hl.annot_xref, translation)
                        result.translations[hl.text] = translation
                    else:
                        result.failed += 1

            # Update cache stats
            result.cached = self._cache.hits
            result.translated = result.total_highlights - result.cached - result.failed

            # Save output
            output_path = self._settings.resolve_output_path()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            doc.save(str(output_path))
            logger.info("Saved translated PDF to %s", output_path)

            return result
        finally:
            doc.close()

    def _translate_highlight(self, hl: HighlightData) -> str | None:
        """Translate a single highlight, using cache when available.

        Args:
            hl: The highlight data to translate.

        Returns:
            The translated string, or None on failure.
        """
        target_lang = self._settings.target_language

        # Hash combining text and its full context to avoid bad cache hits
        context_key = f"{hl.context_before}|{hl.text}|{hl.context_after}"

        # Check cache first
        cached = self._cache.get(context_key, target_lang)
        if cached is not None:
            logger.debug("Using cached translation for: %.50s…", hl.text)
            return cached

        try:
            translation = self._translator.translate(
                text=hl.text,
                context_before=hl.context_before,
                context_after=hl.context_after,
                target_language=target_lang,
            )
            self._cache.put(context_key, target_lang, translation)
            return translation
        except GeminiQuotaExhaustedError:
            # Re-raise so the pipeline fails immediately instead of retrying everything
            raise
        except Exception as exc:
            logger.error(
                "Translation failed for highlight on page %d: %s",
                hl.page_number,
                exc,
            )
            return None

    @staticmethod
    def _validate_pdf(pdf_path: Path) -> None:
        """Validate that the PDF file exists and is readable.

        Args:
            pdf_path: Path to validate.

        Raises:
            FileNotFoundError: If the file does not exist.
            ValueError: If the file is not a PDF.
        """
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF file not found: {pdf_path}")
        if not pdf_path.is_file():
            raise ValueError(f"Not a file: {pdf_path}")
        if pdf_path.suffix.lower() != ".pdf":
            raise ValueError(f"Not a PDF file: {pdf_path}")
