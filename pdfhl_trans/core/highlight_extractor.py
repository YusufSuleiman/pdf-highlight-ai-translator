"""Highlight extraction from PDF annotations with surrounding context."""

from __future__ import annotations

import re
from dataclasses import dataclass

import fitz  # PyMuPDF

from pdfhl_trans.utils.logger import get_logger
from pdfhl_trans.utils.text_utils import fix_rtl_text

logger = get_logger("core.highlight_extractor")

# Regex to split text into sentences (handles ., !, ? followed by whitespace)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


@dataclass(frozen=True)
class HighlightData:
    """Represents a single extracted highlight with its context.

    Attributes:
        page_number: 1-indexed page number where the highlight lives.
        text: The exact highlighted text.
        color: The hex color code of the highlight (e.g., '#FFFF00').
        context_before: Surrounding sentences before the highlight.
        context_after: Surrounding sentences after the highlight.
        annot_xref: PyMuPDF cross-reference ID for the annotation.
    """

    page_number: int
    text: str
    color: str
    context_before: str
    context_after: str
    annot_xref: int


class HighlightExtractor:
    """Extracts highlighted text and surrounding context from a PDF document.

    This class iterates over all pages of a PDF, finds annotations of
    subtype ``Highlight``, extracts the text under the highlight quads,
    and gathers configurable surrounding context sentences.
    """

    def __init__(self, context_sentences: int = 2) -> None:
        """Initialise the extractor.

        Args:
            context_sentences: Number of sentences to include as context
                               before and after the highlighted text.
        """
        self._context_sentences = context_sentences

    def extract_highlights(self, doc: fitz.Document) -> list[HighlightData]:
        """Extract all highlights from a document.

        Args:
            doc: An open PyMuPDF document.

        Returns:
            A list of ``HighlightData`` objects for every highlight found.
        """
        highlights: list[HighlightData] = []

        for page_index in range(len(doc)):
            page = doc[page_index]
            page_number = page_index + 1
            page_highlights = self._extract_page_highlights(page, page_number)
            highlights.extend(page_highlights)

        logger.info(
            "Extracted [bold]%d[/bold] highlights from %d pages",
            len(highlights),
            len(doc),
        )
        return highlights

    def _extract_page_highlights(
        self,
        page: fitz.Page,
        page_number: int,
    ) -> list[HighlightData]:
        """Extract highlighted text and context from a single page.

        Args:
            page: A PyMuPDF page object.
            page_number: 1-indexed page number for reporting.

        Returns:
            List of highlights found on this page.
        """
        highlights: list[HighlightData] = []
        for annot in page.annots():
            if annot.type[0] != fitz.PDF_ANNOT_HIGHLIGHT:
                continue

            try:
                highlight_text = self._extract_annot_text(page, annot)
            except Exception:
                logger.warning(
                    "Failed to extract text for annotation on page %d (xref=%d), skipping",
                    page_number,
                    annot.xref,
                )
                continue

            if not highlight_text or not highlight_text.strip():
                logger.debug(
                    "Empty highlight on page %d (xref=%d), skipping",
                    page_number,
                    annot.xref,
                )
                continue

            highlight_text = highlight_text.strip()
            context_before, context_after = self._get_surrounding_context(
                page, annot.rect, highlight_text
            )

            # Fix RTL text direction if present (e.g. Arabic, Hebrew)
            highlight_text = fix_rtl_text(highlight_text)
            context_before = fix_rtl_text(context_before)
            context_after = fix_rtl_text(context_after)

            # Extract highlight color (hex)
            color_hex = "#FFFF00"  # default yellow
            if annot.colors:
                stroke = annot.colors.get("stroke")
                if stroke and len(stroke) == 3:
                    r = int(stroke[0] * 255)
                    g = int(stroke[1] * 255)
                    b = int(stroke[2] * 255)
                    color_hex = f"#{r:02X}{g:02X}{b:02X}"

            highlights.append(
                HighlightData(
                    page_number=page_number,
                    text=highlight_text,
                    color=color_hex,
                    context_before=context_before,
                    context_after=context_after,
                    annot_xref=annot.xref,
                )
            )
            logger.debug(
                "Page %d: extracted highlight (xref=%d) [color=%s]: %.60s…",
                page_number,
                annot.xref,
                color_hex,
                highlight_text,
            )

        return highlights

    @staticmethod
    def _extract_annot_text(page: fitz.Page, annot: fitz.Annot) -> str:
        """Extract text covered by a highlight annotation using its quads.

        In PyMuPDF, ``annot.vertices`` returns a list of ``(x, y)`` tuples.
        Every 4 consecutive tuples define one quad (parallelogram) covering
        one line of highlighted text.

        Args:
            page: The page containing the annotation.
            annot: The highlight annotation.

        Returns:
            The text string covered by the highlight.
        """
        vertices = annot.vertices  # list of (x, y) tuples
        text_parts: list[str] = []

        if vertices and len(vertices) >= 4:
            # Group every 4 (x,y) tuples into one quad
            for i in range(0, len(vertices), 4):
                group = vertices[i : i + 4]
                if len(group) < 4:
                    continue
                try:
                    quad = fitz.Quad(
                        fitz.Point(group[0]),
                        fitz.Point(group[1]),
                        fitz.Point(group[2]),
                        fitz.Point(group[3]),
                    )
                    part = page.get_text("text", clip=quad.rect).strip()
                    if part:
                        text_parts.append(part)
                except Exception:
                    # Fall back to the bounding rect of this group
                    xs = [p[0] for p in group]
                    ys = [p[1] for p in group]
                    rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
                    part = page.get_text("text", clip=rect).strip()
                    if part:
                        text_parts.append(part)

            if text_parts:
                return " ".join(text_parts)

        # Fallback 1: use the annotation's own rect
        rect_text = page.get_text("text", clip=annot.rect).strip()
        if rect_text:
            return rect_text

        # Fallback 2: check if the annotation stores content directly
        info = annot.info
        if info.get("subject"):
            return info["subject"]

        return ""

    def _get_surrounding_context(
        self,
        page: fitz.Page,
        annot_rect: fitz.Rect,
        highlight_text: str,
    ) -> tuple[str, str]:
        """Extract surrounding sentences by expanding the bounding box.

        Text matching fails often in PDFs due to formatting/newlines.
        Expanding the rect geometrically ensures we always get the context.

        Args:
            page: The PyMuPDF page.
            annot_rect: The bounding box of the annotation.
            highlight_text: The highlighted substring.

        Returns:
            Tuple of (context_before, context_after) as strings.
        """
        if self._context_sentences <= 0:
            return ("", "")

        # Expand the rect vertically to capture surrounding lines (~50 pts per context sentence)
        expansion = self._context_sentences * 50
        expanded_rect = fitz.Rect(
            page.rect.x0,  # full width of page
            max(page.rect.y0, annot_rect.y0 - expansion),
            page.rect.x1,  # full width of page
            min(page.rect.y1, annot_rect.y1 + expansion),
        )

        # Extract text from the expanded region
        region_text = page.get_text("text", clip=expanded_rect)
        
        # Clean up the text for sentence splitting
        region_text = " ".join(region_text.split())
        highlight_clean = " ".join(highlight_text.split())

        # Find the highlight within the region text
        pos = region_text.find(highlight_clean)
        
        if pos == -1:
            # Fallback: just return the whole region as "before" context
            # if we still can't exact match it due to heavy hyphenation etc.
            return (region_text.strip(), "")

        before_text = region_text[:pos].strip()
        after_text = region_text[pos + len(highlight_clean) :].strip()

        # Split into sentences
        before_sentences = _SENTENCE_SPLIT.split(before_text) if before_text else []
        after_sentences = _SENTENCE_SPLIT.split(after_text) if after_text else []

        context_before = " ".join(
            before_sentences[-self._context_sentences :]
        ).strip()
        context_after = " ".join(
            after_sentences[: self._context_sentences]
        ).strip()

        return (context_before, context_after)
