"""Write translations back into PDF highlight annotation notes."""

from __future__ import annotations

import fitz  # PyMuPDF

from pdfhl_trans.utils.logger import get_logger

logger = get_logger("core.annotation_writer")


class AnnotationWriter:
    """Writes translated text into the ``content`` (note) field of annotations.

    This class locates an annotation by its cross-reference ID and updates
    its popup/note content with the provided translation string.
    """

    @staticmethod
    def write_translation(
        doc: fitz.Document,
        annot_xref: int,
        translation: str,
    ) -> bool:
        """Write a translation into the note field of a highlight annotation.

        Args:
            doc: The open PyMuPDF document (will be mutated).
            annot_xref: The cross-reference ID of the annotation.
            translation: The translated text to write.

        Returns:
            True if the annotation was found and updated, False otherwise.
        """
        for page_index in range(len(doc)):
            page = doc[page_index]
            for annot in page.annots():
                if annot.xref == annot_xref:
                    try:
                        info = annot.info
                        info["content"] = translation
                        annot.set_info(info)
                        annot.update()
                        logger.debug(
                            "Wrote translation to annotation xref=%d on page %d",
                            annot_xref,
                            page_index + 1,
                        )
                        return True
                    except Exception as exc:
                        logger.error(
                            "Failed to write annotation xref=%d: %s",
                            annot_xref,
                            exc,
                        )
                        return False

        logger.warning("Annotation xref=%d not found in document", annot_xref)
        return False
