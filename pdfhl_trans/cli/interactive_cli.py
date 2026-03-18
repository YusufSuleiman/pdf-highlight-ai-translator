"""Interactive CLI interface with main menu, key management, and batch/export modes."""

from __future__ import annotations

import argparse
import csv
import sys
import textwrap
from pathlib import Path

import questionary
from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TextColumn,
    TimeElapsedColumn,
)
from rich.table import Table

from pdfhl_trans.cache.translation_cache import TranslationCache
from pdfhl_trans.config.settings import AppConfig, ConfigurationError
from pdfhl_trans.core.highlight_extractor import HighlightData
from pdfhl_trans.core.pdf_processor import PDFProcessor, ProcessingResult
from pdfhl_trans.translation.gemini_translator import GeminiTranslator
from pdfhl_trans.utils.logger import get_logger, setup_logger

console = Console()
logger = get_logger("cli.interactive_cli")


# ── Argument Parser ────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    """Build the argument parser for CLI flags.

    Returns:
        Configured argument parser.
    """
    parser = argparse.ArgumentParser(
        prog="pdfhl-trans",
        description="PDF Highlight Contextual Translator — translate highlighted PDF text using Gemini AI.",
    )
    parser.add_argument(
        "pdf",
        nargs="?",
        help="Path to the PDF file (optional — interactive menu if omitted).",
    )
    parser.add_argument(
        "-l", "--language",
        default=None,
        help="Target language code (default: from config or 'ar').",
    )
    parser.add_argument(
        "-c", "--context",
        type=int,
        default=None,
        help="Number of context sentences before/after highlight (default: 2).",
    )
    parser.add_argument(
        "-o", "--output",
        default=None,
        help="Output PDF file path.",
    )
    parser.add_argument(
        "--batch",
        metavar="DIR",
        default=None,
        help="Batch mode: process all PDFs in the given directory.",
    )
    parser.add_argument(
        "--export",
        metavar="CSV",
        default=None,
        help="Export highlights and translations to a CSV file.",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output.",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug output.",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Gemini model to use (default: from config or 'gemini-2.0-flash').",
    )
    return parser


# ── Main CLI Class ─────────────────────────────────────────────────────


class InteractiveCLI:
    """Drives the interactive command-line experience.

    Provides a main menu with options for translating PDFs, configuring
    the API key, adjusting settings, and running batch/export operations.
    """

    def __init__(self) -> None:
        """Initialise the CLI with a configuration manager."""
        self._parser = build_parser()
        self._config = AppConfig.load()

    def run(self) -> None:
        """Parse arguments and execute the appropriate mode."""
        args = self._parser.parse_args()
        setup_logger(verbose=args.verbose, debug=args.debug)

        try:
            # Direct invocation with a PDF path or --batch flag
            if args.pdf or args.batch:
                self._ensure_api_key()
                if args.batch:
                    self._run_batch(args)
                else:
                    self._run_single_direct(args)
            else:
                # Interactive menu mode
                self._run_interactive_menu(args)
        except ConfigurationError as exc:
            console.print(f"\n[bold red]Configuration Error:[/bold red] {exc}")
            sys.exit(1)
        except KeyboardInterrupt:
            console.print("\n[yellow]Cancelled.[/yellow]")
            sys.exit(0)
        except Exception as exc:
            console.print(f"\n[bold red]Error:[/bold red] {exc}")
            if args.debug:
                console.print_exception()
            sys.exit(1)
        finally:
            self._auto_clear_cache()

    def _auto_clear_cache(self) -> None:
        """Silently clear the translation cache when the application exits."""
        try:
            from pdfhl_trans.cache.translation_cache import TranslationCache

            cache = TranslationCache()
            cache.clear()
            cache.close()
        except Exception:
            pass  # Fail silently on exit

    # ── Interactive Menu ───────────────────────────────────────────────

    def _run_interactive_menu(self, args: argparse.Namespace) -> None:
        """Show the main interactive menu.

        Args:
            args: Parsed CLI arguments (for verbose/debug flags).
        """
        self._print_banner()

        # First-run: ask for API key if not configured
        if not self._config.is_configured():
            console.print(
                "[yellow]No API key found. Let's set one up first.[/yellow]\n"
            )
            self._configure_api_key()

        while True:
            console.print()
            console.print("[bold cyan]Main Menu[/bold cyan]")
            console.print("  [cyan]1)[/cyan] Translate a PDF")
            console.print("  [cyan]2)[/cyan] Batch translate (directory)")
            console.print("  [cyan]3)[/cyan] Configure API key")
            console.print("  [cyan]4)[/cyan] Settings")
            console.print("  [cyan]5)[/cyan] Clear translation cache")
            console.print("  [cyan]6)[/cyan] Exit")
            console.print()

            choice = console.input("[bold cyan]Choose > [/bold cyan]").strip()

            if choice == "1":
                self._ensure_api_key()
                self._run_single_interactive(args)
            elif choice == "2":
                self._ensure_api_key()
                self._run_batch_interactive(args)
            elif choice == "3":
                self._configure_api_key()
            elif choice == "4":
                self._configure_settings()
            elif choice == "5":
                self._clear_cache()
            elif choice == "6":
                console.print("[dim]Goodbye![/dim]")
                break
            else:
                console.print("[red]Invalid choice, please try again.[/red]")

    def _print_banner(self) -> None:
        """Print the application banner."""
        banner_text = r"""[bold cyan]
██╗   ██╗ ██████╗  ██████╗ ██╗  ██╗
╚██╗ ██╔╝██╔═══██╗██╔═══██╗██║  ██║
 ╚████╔╝ ██║   ██║██║   ██║███████║
  ╚██╔╝  ██║   ██║██║   ██║╚════██║
   ██║   ╚██████╔╝╚██████╔╝     ██║
   ╚═╝    ╚═════╝  ╚═════╝      ╚═╝[/bold cyan]

[dim]PDF Highlight Contextual Translator v1.0[/dim]
───────────────────────────────────────────
[bold #E5C07B]✨ Created by Y004 ✨[/bold #E5C07B]"""
        console.print(Panel.fit(banner_text, border_style="cyan"))

    # ── API Key Configuration ──────────────────────────────────────────

    def _configure_api_key(self) -> None:
        """Let the user view and update the stored API key."""
        current = self._config.get_masked_key()
        console.print(f"\n[bold]Current API key:[/bold] [cyan]{current}[/cyan]")

        if current != "(not set)":
            console.print("[dim]Press Enter to keep the current key, or type a new one.[/dim]")

        console.print(
            "[dim]Get a free key at:[/dim] [link=https://aistudio.google.com/apikey]"
            "https://aistudio.google.com/apikey[/link]\n"
        )

        new_key = console.input("[bold cyan]API key > [/bold cyan]").strip()

        if new_key:
            self._config.api_key = new_key
            self._config.save()
            console.print("[green]✓ API key saved.[/green]")
        elif current == "(not set)":
            console.print("[yellow]No key entered. You need an API key to translate.[/yellow]")
        else:
            console.print("[dim]Key unchanged.[/dim]")

    def _ensure_api_key(self) -> None:
        """Ensure an API key is available, prompting if necessary."""
        if not self._config.is_configured():
            console.print("\n[yellow]No API key configured.[/yellow]")
            self._configure_api_key()
            if not self._config.is_configured():
                raise ConfigurationError("Cannot proceed without an API key.")

    # ── Settings Configuration ─────────────────────────────────────────

    def _configure_settings(self) -> None:
        """Let the user view and update default settings."""
        def_lang = str(self._config.default_language)
        def_ctx = int(self._config.default_context_sentences)
        def_model = str(self._config.gemini_model)

        console.print("\n[bold]Current Settings:[/bold]")
        console.print(f"  Target Language : [cyan]{def_lang}[/cyan]")
        console.print(f"  Context Sentences: [cyan]{def_ctx}[/cyan]")
        console.print(f"  Gemini Model     : [cyan]{def_model}[/cyan]\n")

        new_lang = self._ask_string("Target language", default=def_lang)
        new_ctx = self._ask_int("Context sentences", default=def_ctx)
        
        new_model = def_model
        api_key = self._config.get_active_api_key()
        
        if api_key:
            try:
                from google import genai
                client = genai.Client(api_key=api_key)
                
                with console.status("[cyan]Fetching available Gemini models...[/cyan]"):
                    models = [m for m in client.models.list() if "gemini" in m.name.lower()]
                
                if models:
                    choices = []
                    for m in models:
                        model_id = m.name.split("/")[-1]
                        choices.append({"name": f"{m.display_name} ({model_id})", "value": model_id})
                        
                    # Find default choice if it exists
                    default_choice = None
                    for c in choices:
                        if c["value"] == def_model:
                            default_choice = c
                            break
                            
                    if default_choice:
                        selected = questionary.select(
                            "Select Gemini model:",
                            choices=choices,
                            default=default_choice
                        ).ask()
                    else:
                        selected = questionary.select(
                            "Select Gemini model:",
                            choices=choices
                        ).ask()
                    
                    if selected:
                        new_model = selected
                else:
                    new_model = self._ask_string("Gemini model", default=def_model)
            except Exception as e:
                logger.warning(f"Could not fetch models: {e}")
                new_model = self._ask_string("Gemini model", default=def_model)
        else:
            new_model = self._ask_string("Gemini model", default=def_model)

        self._config.default_language = new_lang
        self._config.default_context_sentences = new_ctx
        self._config.gemini_model = new_model
        self._config.save()
        console.print("[green]✓ Settings saved.[/green]")

    # ── Cache Management ───────────────────────────────────────────────

    def _clear_cache(self) -> None:
        """Clear the translation cache after user confirmation."""
        console.print("\n[bold yellow]Warning:[/bold yellow] This will delete all saved translations.")
        console.print("Future translations of the same text will require calling the API again.")
        
        if not self._ask_confirm("Are you sure you want to clear the cache?", default=False):
            console.print("[dim]Cache cleared cancelled.[/dim]")
            return
            
        try:
            # Load cache from default dir or configured dir if we add that later
            cache = TranslationCache()
            count = cache.clear()
            cache.close()
            console.print(f"[green]✓ Successfully deleted {count} cached translations.[/green]")
        except Exception as exc:
            console.print(f"[bold red]Failed to clear cache:[/bold red] {exc}")

    # ── Single PDF Processing ──────────────────────────────────────────

    def _run_single_interactive(self, args: argparse.Namespace) -> None:
        """Interactive flow for translating a single PDF.

        Args:
            args: Parsed CLI arguments.
        """
        pdf_path = self._ask_pdf_path()

        target_lang = self._ask_string(
            "Target language",
            default=str(self._config.default_language or "ar"),
        )
        context_count = self._ask_int(
            "Context sentences",
            default=int(self._config.default_context_sentences or 2),
        )
        default_output = f"{pdf_path.stem}_translated.pdf"
        output_name = self._ask_string("Output file name", default=default_output)
        output_path = (pdf_path.parent / output_name).resolve()
        
        target_colors = self._ask_target_colors([pdf_path])

        settings = self._config.model_copy(
            update={
                "pdf_path": pdf_path,
                "output_path": output_path,
                "target_language": target_lang,
                "context_sentences": context_count,
                "target_colors": target_colors,
                "verbose": args.verbose,
                "debug": args.debug,
            }
        )

        self._execute_translation(settings, pdf_path, export_csv=None)

    def _run_single_direct(self, args: argparse.Namespace) -> None:
        """Process a single PDF from direct CLI arguments.

        Args:
            args: Parsed CLI arguments.
        """
        pdf_path = Path(args.pdf).resolve()
        if not pdf_path.exists():
            console.print(f"[bold red]File not found:[/bold red] {pdf_path}")
            sys.exit(1)

        settings = self._config.model_copy(
            update={
                "pdf_path": pdf_path,
                "output_path": Path(args.output).resolve() if args.output else None,
                "target_language": args.language or self._config.default_language,
                "context_sentences": args.context if args.context is not None else self._config.default_context_sentences,
                "verbose": args.verbose,
                "debug": args.debug,
                "gemini_model": args.model or self._config.gemini_model,
            }
        )

        self._execute_translation(settings, pdf_path, export_csv=args.export)

    def _execute_translation(
        self,
        settings: AppConfig,
        pdf_path: Path,
        export_csv: str | None,
    ) -> None:
        """Run the translation pipeline for a single PDF.

        Args:
            settings: Configured app settings.
            pdf_path: Path to the PDF.
            export_csv: Optional CSV export path.
        """
        translator = GeminiTranslator(
            api_key=settings.get_active_api_key(),
            model=settings.gemini_model,
        )
        cache = TranslationCache(cache_dir=settings.cache_dir)
        processor = PDFProcessor(translator=translator, cache=cache, settings=settings)

        # Preview
        highlights = processor.extract_highlights(pdf_path)
        if not highlights:
            console.print("\n[yellow]No highlights found in this PDF.[/yellow]")
            return

        target_colors = settings.target_colors
        if target_colors:
            target_colors_upper = [c.upper() for c in target_colors]
            filtered_count = sum(1 for hl in highlights if hl.color.upper() in target_colors_upper)
            console.print(f"\n[green]Found [bold]{filtered_count}[/bold] selected highlights out of [bold]{len(highlights)}[/bold] total.[/green]")
        else:
            console.print(f"\n[green]Found [bold]{len(highlights)}[/bold] highlights.[/green]")
            
        if not self._ask_confirm("Proceed with translation?"):
            console.print("[yellow]Cancelled.[/yellow]")
            return

        # Process
        result = self._process_with_progress(processor, pdf_path, show_filter_msg=False)

        # Export
        if export_csv:
            self._export_csv(result, Path(export_csv), pdf_path.name)

        # Summary
        self._print_summary(result)
        cache.close()

    # ── Batch Processing ───────────────────────────────────────────────

    def _run_batch_interactive(self, args: argparse.Namespace) -> None:
        """Interactive batch mode: ask for directory then select files.

        Args:
            args: Parsed CLI arguments.
        """
        console.print(
            "\n[bold]Select a directory for batch translation:[/bold]\n"
            "  Enter a path, or press Enter for current directory\n"
        )
        dir_input = console.input("[bold cyan]Directory path > [/bold cyan]").strip()
        batch_dir = Path(dir_input).resolve() if dir_input else Path.cwd()

        if not batch_dir.is_dir():
            console.print(f"[bold red]Not a directory:[/bold red] {batch_dir}")
            return

        pdf_files = sorted(batch_dir.glob("*.pdf"))
        if not pdf_files:
            console.print(f"[yellow]No PDF files found in {batch_dir}[/yellow]")
            return

        # Use Questionary for interactive multi-selection
        choices = [{"name": f.name, "value": f, "checked": True} for f in pdf_files]
        selected_files = questionary.checkbox(
            "Select PDFs to translate (Space to toggle, Enter to confirm):",
            choices=choices,
        ).ask()

        if not selected_files:
            console.print("[yellow]No files selected. Cancelled.[/yellow]")
            return

        self._process_file_list(selected_files, args)

    def _run_batch(self, args: argparse.Namespace) -> None:
        """Process all PDFs in a directory (direct CLI invocation).

        Args:
            args: Parsed CLI arguments.
        """
        batch_dir = Path(args.batch).resolve()
        if not batch_dir.is_dir():
            console.print(f"[bold red]Not a directory:[/bold red] {batch_dir}")
            sys.exit(1)

        pdf_files = sorted(batch_dir.glob("*.pdf"))
        if not pdf_files:
            console.print(f"[yellow]No PDF files found in {batch_dir}[/yellow]")
            return
            
        self._process_file_list(pdf_files, args)

    def _process_file_list(self, pdf_files: list[Path], args: argparse.Namespace) -> None:
        """Translate a specific list of PDF files.

        Args:
            pdf_files: List of Paths to PDFs.
            args: Parsed CLI arguments.
        """
        console.print(
            f"\n[green]Processing [bold]{len(pdf_files)}[/bold] PDFs...[/green]"
        )

        target_lang = args.language or self._ask_string(
            "Target language",
            default=self._config.default_language,
        )
        context_count = args.context if args.context is not None else self._ask_int(
            "Context sentences",
            default=self._config.default_context_sentences,
        )
        
        target_colors = self._ask_target_colors(pdf_files)

        all_results: list[tuple[Path, ProcessingResult]] = []

        for pdf_file in pdf_files:
            console.print(f"\n[cyan]Processing:[/cyan] {pdf_file.name}")

            output_path = pdf_file.parent / f"{pdf_file.stem}_translated.pdf"
            settings = self._config.model_copy(
                update={
                    "pdf_path": pdf_file,
                    "output_path": output_path,
                    "target_language": target_lang,
                    "context_sentences": context_count,
                    "target_colors": target_colors,
                    "verbose": args.verbose,
                    "debug": args.debug,
                    "gemini_model": args.model or self._config.gemini_model,
                }
            )

            translator = GeminiTranslator(
                api_key=settings.get_active_api_key(),
                model=settings.gemini_model,
            )
            cache = TranslationCache(cache_dir=settings.cache_dir)
            processor = PDFProcessor(translator=translator, cache=cache, settings=settings)

            result = self._process_with_progress(processor, pdf_file, show_filter_msg=True)
            all_results.append((pdf_file, result))
            cache.close()

        # Export all if requested
        if args.export:
            self._export_batch_csv(all_results, Path(args.export))

        # Batch summary
        console.print("\n")
        console.print(
            Panel.fit(
                "[bold green]Batch Processing Complete[/bold green]",
                border_style="green",
            )
        )
        for pdf_file, result in all_results:
            console.print(
                f"  {pdf_file.name}: "
                f"[green]{result.translated}[/green] translated, "
                f"[blue]{result.cached}[/blue] cached, "
                f"[red]{result.failed}[/red] failed"
            )

    # ── Progress Display ───────────────────────────────────────────────

    @staticmethod
    def _process_with_progress(
        processor: PDFProcessor,
        pdf_path: Path,
        show_filter_msg: bool = False,
    ) -> ProcessingResult:
        """Process a PDF with a rich progress bar.

        Args:
            processor: Configured PDF processor.
            pdf_path: Path to the PDF.
            show_filter_msg: Whether to print the selected count out of total count message.

        Returns:
            Processing result.
        """
        progress = Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=console,
        )

        task_id = None

        def on_progress(current: int, filtered_total: int, absolute_total: int, hl: HighlightData) -> None:
            nonlocal task_id
            if task_id is None:
                if show_filter_msg and filtered_total != absolute_total:
                    console.print(f"\n[bold yellow]Found {filtered_total} selected highlights out of {absolute_total} total.[/bold yellow]")
                task_id = progress.add_task("Translating", total=filtered_total)
                
            short_text = textwrap.shorten(hl.text, width=40, placeholder="…")
            progress.update(
                task_id,
                completed=current,
                description=f"Page {hl.page_number} | [cyan]{short_text}[/cyan]",
            )

        with progress:
            result = processor.process(pdf_path, progress_callback=on_progress)

        return result

    @staticmethod
    def _print_summary(result: ProcessingResult) -> None:
        """Print a styled processing summary.

        Args:
            result: The processing result.
        """
        table = Table(title="Processing Summary", border_style="cyan")
        table.add_column("Metric", style="bold")
        table.add_column("Value", justify="right")

        table.add_row("Total highlights", str(result.absolute_total_highlights))
        if getattr(result, "total_highlights", result.absolute_total_highlights) != result.absolute_total_highlights:
            table.add_row("Filtered (Selected)", str(result.total_highlights))
        table.add_row("Translated (API)", f"[green]{result.translated}[/green]")
        table.add_row("From cache", f"[blue]{result.cached}[/blue]")
        table.add_row("Failed", f"[red]{result.failed}[/red]")
        table.add_row("Output file", str(result.output_path))

        console.print()
        console.print(table)
        console.print(
            f"\n[bold green]✓[/bold green] Saved to [cyan]{result.output_path}[/cyan]"
        )

    # ── CSV Export ─────────────────────────────────────────────────────

    @staticmethod
    def _export_csv(
        result: ProcessingResult,
        csv_path: Path,
        filename: str,
    ) -> None:
        """Export highlights and translations to CSV.

        Args:
            result: Processing result.
            csv_path: Path for output CSV.
            filename: Source PDF filename.
        """
        csv_path = csv_path.resolve()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["File", "Page", "Original Text", "Translation"])
            for hl in result.highlights:
                translation = result.translations.get(hl.text, "")
                writer.writerow([filename, hl.page_number, hl.text, translation])
        console.print(f"[green]Exported to:[/green] {csv_path}")

    @staticmethod
    def _export_batch_csv(
        all_results: list[tuple[Path, ProcessingResult]],
        csv_path: Path,
    ) -> None:
        """Export batch results to CSV.

        Args:
            all_results: List of (pdf_path, result) tuples.
            csv_path: Path for output CSV.
        """
        csv_path = csv_path.resolve()
        with open(csv_path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["File", "Page", "Original Text", "Translation"])
            for pdf_path, result in all_results:
                for hl in result.highlights:
                    translation = result.translations.get(hl.text, "")
                    writer.writerow([pdf_path.name, hl.page_number, hl.text, translation])
        console.print(f"[green]Exported batch to:[/green] {csv_path}")

    # ── Interactive Input Helpers ──────────────────────────────────────

    @staticmethod
    def _get_color_name(hex_code: str) -> str:
        """Return a human-readable name for typical highlight hex colors."""
        colors = {
            "#FFFF00": "Yellow",
            "#00FF00": "Green",
            "#0000FF": "Blue",
            "#FF0000": "Red",
            "#FF00FF": "Magenta/Pink",
            "#00FFFF": "Cyan",
            "#FFA500": "Orange",
            "#800080": "Purple",
            "#FFFFFF": "White",
            "#000000": "Black",
        }
        name = colors.get(hex_code.upper())
        if name:
            return f"{name} ({hex_code})"
        return hex_code

    @staticmethod
    def _ask_target_colors(pdfs: list[Path]) -> list[str] | None:
        """Scan PDFs for highlight colors and ask the user to filter.
        
        Args:
            pdfs: List of PDF files to scan for colors.
            
        Returns:
            List of selected hex colors, or None to process all.
        """
        import fitz

        unique_colors = set()
        logger.info("Scanning PDFs for highlight colors...")

        for p in pdfs:
            try:
                doc = fitz.open(p)
                for page in doc:
                    for annot in page.annots():
                        if annot.type[0] == fitz.PDF_ANNOT_HIGHLIGHT:
                            color_hex = "#FFFF00"
                            if annot.colors:
                                stroke = annot.colors.get("stroke")
                                if stroke and len(stroke) == 3:
                                    r = int(stroke[0] * 255)
                                    g = int(stroke[1] * 255)
                                    b = int(stroke[2] * 255)
                                    color_hex = f"#{r:02X}{g:02X}{b:02X}"
                            unique_colors.add(color_hex)
                doc.close()
            except Exception as e:
                logger.warning(f"Failed to scan {p.name} for colors: {e}")
                
        if not unique_colors:
            return None
            
        console.print(f"\n[cyan]Found {len(unique_colors)} unique highlight color(s) in documents.[/cyan]")
        
        if not InteractiveCLI._ask_confirm("Do you want to translate ONLY specific highlight colors?", default=False):
            return None
            
        choices = [
            {
                "name": InteractiveCLI._get_color_name(c), 
                "value": c, 
                "checked": True
            } for c in sorted(unique_colors)
        ]
        
        selected = questionary.checkbox(
            "Select target highlight colors (Space to toggle, Enter to confirm):",
            choices=choices,
        ).ask()
        
        return selected if selected else None

    @staticmethod
    def _ask_pdf_path() -> Path:
        """Ask for a PDF file path interactively.

        Returns:
            Resolved path to the selected PDF.
        """
        console.print(
            "\n[bold]Select a PDF file:[/bold]\n"
            "  Enter a path, or type [cyan]cwd[/cyan] to browse current directory\n"
        )

        while True:
            user_input = console.input("[bold cyan]PDF path > [/bold cyan]").strip()

            if not user_input:
                console.print("[yellow]Please enter a path or 'cwd'.[/yellow]")
                continue

            if user_input.lower() == "cwd":
                return InteractiveCLI._choose_from_cwd()

            path = Path(user_input).resolve()
            if path.exists() and path.is_file():
                return path

            console.print(f"[red]File not found:[/red] {path}")

    @staticmethod
    def _choose_from_cwd() -> Path:
        """List PDFs in the current directory for selection.

        Returns:
            Selected PDF path.
        """
        cwd = Path.cwd()
        pdfs = sorted(cwd.glob("*.pdf"))

        if not pdfs:
            console.print(f"[yellow]No PDF files in {cwd}[/yellow]")
            sys.exit(1)

        console.print(f"\n[bold]PDFs in {cwd}:[/bold]")
        for idx, p in enumerate(pdfs, start=1):
            size_mb = p.stat().st_size / (1024 * 1024)
            console.print(
                f"  [cyan]{idx})[/cyan] {p.name}  [dim]({size_mb:.1f} MB)[/dim]"
            )

        while True:
            choice = console.input("\n[bold cyan]Choose > [/bold cyan]").strip()
            try:
                num = int(choice)
                if 1 <= num <= len(pdfs):
                    return pdfs[num - 1]
            except ValueError:
                pass
            console.print(f"[red]Enter a number between 1 and {len(pdfs)}.[/red]")

    @staticmethod
    def _ask_string(prompt: str, default: str) -> str:
        """Ask for a string with a default."""
        value = console.input(
            f"[bold cyan]{prompt}[/bold cyan] [dim]({default})[/dim] > "
        ).strip()
        return value if value else default

    @staticmethod
    def _ask_int(prompt: str, default: int) -> int:
        """Ask for an integer with a default."""
        while True:
            value = console.input(
                f"[bold cyan]{prompt}[/bold cyan] [dim]({default})[/dim] > "
            ).strip()
            if not value:
                return default
            try:
                return int(value)
            except ValueError:
                console.print("[red]Please enter a valid number.[/red]")

    @staticmethod
    def _ask_confirm(prompt: str, default: bool = True) -> bool:
        """Ask a yes/no question."""
        suffix = "[Y/n]" if default else "[y/N]"
        value = console.input(
            f"[bold cyan]{prompt}[/bold cyan] {suffix} > "
        ).strip().lower()
        if not value:
            return default
        return value in ("y", "yes")
