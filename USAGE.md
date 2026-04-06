# How to use the Job Application Assistant

## Start the app

From the folder that *contains* the `job_app_assistant` package (not necessarily inside it), run:

```bash
python -m job_app_assistant
```

## First-time setup

1. Open the **Settings** tab (or use fields on **Input & Analysis**): set your **OpenAI API key** if it is not already in the `OPENAI_API_KEY` environment variable.
2. Choose a **personal library** folder with your resumes and notes (PDF, DOCX, or TXT). The app reads these files when analyzing jobs and generating documents.

## Typical workflow

### 1. Input & Analysis

- Paste a job description, or **fetch** it from a URL, or **open** a PDF/DOCX/TXT posting.
- Optionally enter **Job title** and **Company** (helps prompts and export filenames).
- Click **Run analysis** to get a pros/cons–style report based on the posting and your library.

### 2. Documents

- Click **Generate resume & cover letter**.
- Edit the text in the previews if you want changes.
- Use **Download resume (.docx)…** and **Download cover letter (.docx)…** to save Word files.

### 3. Optional tabs

- **HR research**: research using the company and job context from the analysis tab.
- **Chat**: ask questions with the same job and library context.

## Save your work

Use **File → Save Application…** to save a JSON workspace (job text, company/title, analysis, drafts, HR research). Use **File → Open Application…** to load it later. Chat history and local settings are not stored in that file.

## Tips

- Keep your library folder up to date so analysis and drafts match what you can back up in an interview.
- Do not commit `settings.json` if it holds your API key.
