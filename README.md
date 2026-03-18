# pdfhl-trans

> **PDF Highlight Contextual Translator** — Extract highlighted text from PDFs, translate it using Google Gemini AI with full contextual awareness, and write translations back into annotation notes.

[![Python](https://img.shields.io/badge/python-3.9%2B-blue?logo=python)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Powered by Gemini](https://img.shields.io/badge/Powered%20by-Gemini%20AI-4285F4?logo=google)](https://aistudio.google.com/)
[![PyMuPDF](https://img.shields.io/badge/PDF-PyMuPDF-orange)](https://pymupdf.readthedocs.io/)

---

## ✨ Features

| Feature | Description |
|---|---|
| 🔍 **Highlight Extraction** | Accurately extracts text from PDF highlight annotations |
| 🌐 **Contextual Translation** | Sends surrounding sentences to Gemini for context-aware results |
| ✏️ **Annotation Writing** | Writes translations directly into PDF annotation notes |
| 🎨 **Color Filtering** | Pick exactly which highlight colors to translate — save API costs |
| ⚡ **Dynamic Models** | Auto-fetches available Gemini models based on your API key |
| 🧵 **Multi-threaded** | Async API calls drastically reduce total processing time |
| 🔄 **Smart RTL Repair** | Fixes Bi-Directional (Arabic/Hebrew) text extraction issues |
| 💾 **Translation Cache** | Thread-safe SQLite cache — no duplicate API calls |
| 📁 **Batch Processing** | Select multiple PDFs interactively from any directory |
| 📊 **CSV Export** | Export highlights and translations to a CSV file |
| 🛡️ **Pydantic Config** | Robust unified config at `~/.config/pdfhl-trans/config.json` |
| 🖥️ **Rich CLI** | Beautiful interactive terminal UI with live progress |

---

## 📦 Installation

### Method 1: `pipx` ✅ Recommended

[`pipx`](https://pypa.github.io/pipx/) is the standard way to install Python CLI tools on modern Linux.

```bash
# Install pipx if needed
sudo apt install pipx
pipx ensurepath          # adds ~/.local/bin to PATH (re-open terminal after)

# Install pdfhl-trans directly from the repo
pipx install git+https://github.com/YusufSuleiman/pdf-highlight-ai-translator.git

# Or from a local clone
git clone https://github.com/YusufSuleiman/pdf-highlight-ai-translator.git
pipx install ./pdfhl-trans/

# Run
pdfhl-trans
```

### Method 2: pip + virtual environment

```bash
git clone https://github.com/YusufSuleiman/pdf-highlight-ai-translator.git
cd pdfhl-trans
python3 -m venv .venv
source .venv/bin/activate
pip install .
pdfhl-trans
```

### Method 3: Development / editable mode

```bash
git clone https://github.com/YusufSuleiman/pdf-highlight-ai-translator.git
cd pdfhl-trans
pip install -e .
```

---

## 🚀 First Run

On first launch, the tool will ask for your Gemini API key:

```
╭─────────────────────────────────╮
│   pdfhl-trans  v1.0             │
│   PDF Highlight Translator      │
╰─────────────────────────────────╯

No API key found. Let's set one up first.

Get a free key at: https://aistudio.google.com/apikey

API key > _
```

The key is saved to `~/.config/pdfhl-trans/config.json` and reused on every run.

You can also set it via environment variable (takes priority over config file):

```bash
export GEMINI_API_KEY='your-key-here'
```

---

## 📖 Usage

### Interactive Menu (default)

```bash
pdfhl-trans
```

```
Main Menu
  1) Translate a PDF
  2) Batch translate (directory)
  3) Configure API key
  4) Settings
  5) Exit
```

### Direct Mode

```bash
pdfhl-trans document.pdf -l ar -c 2 -o translated.pdf
```

### Batch Mode

```bash
pdfhl-trans --batch ./papers/
```

### Export to CSV

```bash
pdfhl-trans document.pdf --export results.csv
```

### All CLI Options

| Flag | Description | Default |
|---|---|---|
| `pdf` | Path to PDF file | *(interactive)* |
| `-l, --language` | Target language code | `ar` |
| `-c, --context` | Context sentences count | `2` |
| `-o, --output` | Output PDF path | `<name>_translated.pdf` |
| `--batch DIR` | Process all PDFs in a directory | — |
| `--export CSV` | Export highlights + translations to CSV | — |
| `--model` | Gemini model ID to use | `gemini-2.0-flash` |
| `-v, --verbose` | Verbose output | off |
| `--debug` | Debug output | off |

---

## ⚙️ Configuration

Settings are stored at `~/.config/pdfhl-trans/config.json`.

| Key | Description | Default |
|---|---|---|
| `api_key` | Gemini API key | — |
| `default_language` | Target language code | `ar` |
| `default_context_sentences` | Context window size | `2` |
| `gemini_model` | Gemini model ID | `gemini-2.0-flash` |

You can manage settings from the interactive menu (option 4) or edit the JSON file directly.

---

## 🏗️ Architecture

```
pdfhl_trans/
├── main.py                          # Entry point
├── cli/
│   └── interactive_cli.py           # Interactive menu, batch, export logic
├── config/
│   └── settings.py                  # AppConfig — Pydantic unified config
├── core/
│   ├── highlight_extractor.py       # Highlight + surrounding context extraction
│   ├── annotation_writer.py         # Write translations back to PDF annotations
│   └── pdf_processor.py             # Multithreaded pipeline orchestrator
├── translation/
│   ├── base_translator.py           # Abstract translator interface
│   └── gemini_translator.py         # Gemini API client logic
├── cache/
│   └── translation_cache.py         # Thread-safe SQLite translation cache
└── utils/
    ├── logger.py                    # Rich-based structured logging
    └── text_utils.py                # Smart RTL (Arabic/Hebrew) text repair
```

---

## 🔑 API Key

This tool uses the [Google Gemini API](https://aistudio.google.com/). You need a free API key:

1. Go to [https://aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **Create API key**
3. Run `pdfhl-trans` — it will prompt you to enter the key on first launch

---

## 📋 Requirements

- Python **3.9+**
- Linux (tested on Ubuntu/Debian)
- A [Google Gemini API key](https://aistudio.google.com/apikey) (free tier available)

Dependencies are installed automatically:

| Package | Purpose |
|---|---|
| `PyMuPDF` | PDF reading and annotation writing |
| `google-genai` | Gemini AI API client |
| `questionary` | Interactive terminal prompts |
| `python-bidi` | RTL text direction repair |
| `pydantic` | Config validation |
| `rich` | Beautiful terminal output |

---

## 📄 License

This project is licensed under the **MIT License** — see [LICENSE](LICENSE) for details.
