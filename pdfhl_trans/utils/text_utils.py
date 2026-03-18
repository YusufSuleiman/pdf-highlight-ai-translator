"""Text manipulation and formatting utilities."""

from __future__ import annotations

import re

from bidi.algorithm import get_display

# Regex to detect if a string contains any Arabic or Hebrew characters
_RTL_RE = re.compile(r"[\u0590-\u05FF\u0600-\u06FF]")

def fix_rtl_text(text: str) -> str:
    """Correct the order of Right-To-Left (RTL) text.

    PDF engines (like PyMuPDF) often extract RTL text (e.g. Arabic, Hebrew)
    in strictly logical (or sometimes visual reverse) order depending on the font.
    This function uses the Unicode Bidirectional Algorithm to correct the
    string for proper reading and processing (especially for LLM translation).

    Args:
        text: The raw extracted text.

    Returns:
        The text with corrected RTL flow if RTL characters are detected,
        otherwise the original text.
    """
    if not text:
        return text

    # Only apply the expensive Bidi algorithm if RTL characters are present
    if _RTL_RE.search(text):
        # get_display() reorganizes the string so that it is in visual order,
        # which usually fixes the "backwards" text issue from PDFs.
        return get_display(text)

    return text
