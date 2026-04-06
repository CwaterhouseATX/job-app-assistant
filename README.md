# AI Job Application Assistant

Desktop app that helps you analyze job postings, draft tailored resumes and cover letters grounded in your own materials, and explore employer context—all with **OpenAI** models and a **PyQt6** GUI.

## Goals

- **Stay factual**: Tie analysis and generated documents to your personal document library and the job description, not invented credentials.
- **Speed up the loop**: Load a posting (URL or file), get a structured pros/cons-style analysis, then generate editable drafts you can export to **DOCX**.
- **Keep context portable**: Save and reopen “workspace” JSON with job text, analysis, drafts, and optional company/title metadata (excluding chat and local settings).

## Architecture (high level)

| Layer | Role |
|--------|------|
| **GUI** (`gui/`) | Tabs: **Input & Analysis**, **Documents** (preview / generate / export), **HR research**, **Chat**, **Settings**. `AppConfig` + JSON hold API key and library path (not committed). |
| **Document intake** (`document_processor.py`) | Plain text from posting URLs (HTTP + HTML), PDF/DOCX/TXT via PyMuPDF / python-docx. |
| **Library** (`library_manager.py`) | Scans a folder of your files and builds context for prompts. |
| **Analysis** (`job_analyzer.py`) | Job-vs-library fit report via `OpenAIClient`. |
| **Generation** (`application_documents.py`, `document_architect.py`) | Resume (Markdown-oriented) and cover letter (plain text), exported to ATS-friendly Word. |
| **HR research** (`hr_researcher.py`) | Optional research flow using company + JD. |
| **Workspace** (`gui/workspace.py`) | Save/load application state as JSON (v1). |

The **OpenAI** integration lives in `openai_client.py` (defaults include low temperature and conservative system instructions). The GUI entry point is `__main__.py`.

## Requirements

- **Python 3.10+** (recommended)
- **OpenAI API key** (or set `OPENAI_API_KEY` in the environment; the app can also store a key in local settings—do not commit that file)

### Dependencies

Install these packages (for example with `pip`):

```text
PyQt6
openai
PyMuPDF
requests
beautifulsoup4
python-docx
```

Example:

```bash
pip install PyQt6 openai PyMuPDF requests beautifulsoup4 python-docx
```

> **Tip:** Add a `requirements.txt` (or `pyproject.toml`) to pin versions for reproducible installs.

## Installation

1. **Clone** the repo. For the run command below, the repository folder should be importable as the package `job_app_assistant` (clone into a directory named `job_app_assistant`, or adjust your `PYTHONPATH`).

2. **Create a virtual environment** (recommended):

   ```bash
   python -m venv .venv
   ```

   - **Windows:** `.venv\Scripts\activate`
   - **macOS / Linux:** `source .venv/bin/activate`

3. **Install dependencies** (see above).

4. **Run the app** from the **parent** directory of the `job_app_assistant` package folder:

   ```bash
   cd /path/to/parent
   python -m job_app_assistant
   ```

   If your checkout path does not match the package name, set `PYTHONPATH` to that parent directory or install the package in editable mode once you add packaging metadata.

## Usage (typical workflow)

1. **Settings / library**  
   Choose your **personal library** folder (PDF, DOCX, TXT resumes and notes). Optionally set an **OpenAI API key** if not using the environment variable.

2. **Input & Analysis**  
   Paste a job description or load one from a **URL** or **file**. Optionally set **Job title** and **Company** (used for prompts and clean export filenames). Run **Run analysis** to get the structured report.

3. **Documents**  
   **Generate resume & cover letter**, edit the previews, then **Download** `.docx` files. Filenames use your company/title metadata when present.

4. **HR research** (optional)  
   Uses company and posting context from the analysis tab.

5. **Chat** (optional)  
   Conversational help grounded in the same job and library context.

6. **File menu**  
   **Save Application…** / **Open Application…** stores or restores workspace JSON (job description, titles, company, analysis, HR research text, resume/cover drafts). Local **settings** and chat history are not included in that file.

## Project layout

```text
job_app_assistant/
  __main__.py           # GUI entry
  __init__.py
  openai_client.py
  document_processor.py
  library_manager.py
  job_analyzer.py
  application_documents.py
  document_architect.py
  hr_researcher.py
  gui/
    main_window.py
    analysis_tab.py
    document_preview_tab.py
    hr_research_tab.py
    chat_tab.py
    settings_tab.py
    workspace.py
    app_config.py
```

## Security & privacy

- **Never commit `settings.json`** if it contains your API key or personal paths (it is listed in `.gitignore`).
- Generated content is only as accurate as your library and the posting; review before sending applications.

## Contributing

Issues and pull requests are welcome. Keep changes focused; avoid committing secrets or machine-specific paths.

## License

Specify your license here (for example MIT, Apache-2.0, or “All rights reserved”). *Replace this line when you add a `LICENSE` file.*

---

**Disclaimer:** This tool uses third-party AI services; usage is subject to OpenAI’s terms and your account billing. This project is not affiliated with OpenAI.
