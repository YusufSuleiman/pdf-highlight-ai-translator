#!/usr/bin/env python3
"""pdfhl-trans — PDF Highlight Contextual Translator.

Entry point for the command-line tool. Launches the interactive CLI
or processes arguments for batch/export modes.
"""

from __future__ import annotations


def main() -> None:
    """Application entry point."""
    from pdfhl_trans.cli.interactive_cli import InteractiveCLI

    cli = InteractiveCLI()
    cli.run()


if __name__ == "__main__":
    main()
