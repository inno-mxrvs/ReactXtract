# ReactXtract POC — User Installation and Operation Guide

## 1. Purpose

ReactXtract is a proof-of-concept web application that extracts structured chemical-reaction information from literature PDFs. It runs locally on a Windows computer and uses either the OpenAI API or Azure OpenAI for AI-assisted extraction.

This guide explains how to:

1. Install the prerequisites.
2. Download ReactXtract from GitHub.
3. Run the automatic setup.
4. Configure AI credentials.
5. Start and stop the application.
6. Process PDFs and save reviewed records.
7. Pull application updates from GitHub.
8. Resolve common setup and runtime problems.

ReactXtract is currently a local POC. It is not deployed as a centrally hosted production application.

## 2. What Each User Needs

### 2.1 Computer and access

- Windows 10 or Windows 11, 64-bit
- Permission to install software on the computer
- Internet access for downloading dependencies and calling the configured AI service
- Access to the ReactXtract GitHub repository
- One of the following:
  - An OpenAI API key and a compatible model
  - An Azure OpenAI endpoint, API key, and compatible deployment

### 2.2 Software to install

Install the following before downloading ReactXtract:

1. **Git for Windows**
2. **Python 3.12 or Python 3.13, 64-bit**

During Python installation, enable:

- **Add Python to PATH**
- **Install launcher for all users** or the Python launcher option, when available

ReactXtract does not require Tesseract OCR, Node.js, Docker, MySQL, PostgreSQL, or a separate PDF viewer.

## 3. Verify the Prerequisites

Open **Command Prompt** or **PowerShell** and run:

```powershell
git --version
py --version
```

Expected results resemble:

```text
git version 2.x.x.windows.x
Python 3.12.x
```

or:

```text
Python 3.13.x
```

If either command is not recognized, reinstall the missing software and ensure it is added to `PATH`.

## 4. Download ReactXtract from GitHub

### Option A — Clone with a command

Open PowerShell in the parent folder where ReactXtract should be installed, then run:

```powershell
git clone https://github.com/inno-mxrvs/ReactXtract.git
cd ReactXtract
```

### Option B — Clone using GitHub Desktop

1. Open GitHub Desktop.
2. Select **File > Clone repository**.
3. Select or enter `inno-mxrvs/ReactXtract`.
4. Choose a local folder.
5. Select **Clone**.
6. Open the cloned `ReactXtract` folder in File Explorer.

Do not download only individual project files. The complete repository is required because it includes the Django application, database migrations, templates, instruction files, and lookup lists.

## 5. Run the Automatic Setup

In the cloned ReactXtract folder, double-click:

```text
setup.cmd
```

The setup script performs these actions:

1. Opens the ReactXtract repository folder.
2. Creates a local Python virtual environment named `.venv` if it does not exist.
3. Updates `pip` inside the virtual environment.
4. Installs the pinned packages from `requirements.txt`.
5. Creates `.env` from `.env.example` if `.env` does not exist.
6. Preserves an existing `.env` so saved credentials are not overwritten.

Wait for this message:

```text
Setup completed successfully.
Run runserver.cmd to start ReactXtract.
```

Press any key to close the setup window.

### 5.1 Windows security prompt

Windows may display a SmartScreen or security warning for a newly downloaded `.cmd` file. Only continue if the repository was obtained from the approved GitHub source. Depending on organizational policy, select **More info > Run anyway** or request assistance from IT.

### 5.2 Manual setup alternative

If `setup.cmd` cannot be used, open PowerShell in the repository folder and run:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

If PowerShell blocks virtual-environment activation:

```powershell
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1
```

This changes the execution policy only for the current PowerShell window.

## 6. Place the Approved `.env` File from Teams

The project team will send users an approved `.env` file through a Teams message. This file contains the POC configuration required to connect ReactXtract to the approved AI service.

After `setup.cmd` finishes:

1. Open the approved Teams message.
2. Download the attached `.env` file.
3. Open the cloned ReactXtract folder—the folder containing `setup.cmd` and `runserver.cmd`.
4. Copy and paste the downloaded `.env` file directly into that folder.
5. Select **Replace the file in the destination** if Windows reports that `.env` already exists. The existing file was only created from `.env.example` during setup.
6. Confirm that the filename is exactly `.env`, not `.env.txt`, `.env (1)`, or `env`.

If Windows hides file extensions, enable **View > Show > File name extensions** in File Explorer before checking the name.

Do not copy the `.env` file into `.venv`, `server`, or `client`. Its correct location is the ReactXtract repository root:

```text
ReactXtract\
├── .env
├── setup.cmd
├── runserver.cmd
├── requirements.txt
├── client\
└── server\
```

Never commit `.env` to GitHub, forward it to unauthorized people, attach it to another email, or disclose its API keys. The repository already excludes `.env` from Git tracking.

### 6.1 Verify the file

The file can be opened in Notepad to confirm that it contains configuration entries:

```powershell
notepad .env
```

Do not change the values supplied by the project team unless instructed. Close Notepad without saving if no change is required.

### 6.2 Manual configuration reference

The remaining examples in this section are for project administrators or troubleshooting only. Normal users should use the approved Teams `.env` file.

#### Common local settings

For local POC use:

```dotenv
DJANGO_SECRET_KEY=replace-with-a-private-random-value
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=127.0.0.1,localhost
```

To generate a random Django secret after setup:

```powershell
.\.venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(50))"
```

Copy the generated value to `DJANGO_SECRET_KEY`.

#### Standard OpenAI configuration

Use this configuration when calling the OpenAI API directly:

```dotenv
OPENAI_API_KEY=your-openai-api-key
OPENAI_MODEL=gpt-4.1

AZURE_OPENAI_ENDPOINT=
AZURE_OPENAI_API_KEY=
AZURE_OPENAI_DEPLOYMENT=
```

Important:

- `AZURE_OPENAI_ENDPOINT` must remain empty when using standard OpenAI.
- The selected model must support the Responses API, structured JSON output, and the required PDF/image inputs.
- The API account is responsible for usage charges.

#### Azure OpenAI configuration

Use this configuration when the organization provides Azure OpenAI:

```dotenv
OPENAI_API_KEY=
OPENAI_MODEL=

AZURE_OPENAI_ENDPOINT=https://your-resource.openai.azure.com/
AZURE_OPENAI_API_KEY=your-azure-api-key
AZURE_OPENAI_RESPONSES_API_VERSION=2025-03-01-preview
AZURE_OPENAI_DEPLOYMENT=your-deployment-name
```

Important:

- `AZURE_OPENAI_DEPLOYMENT` is the Azure deployment name, which may differ from the underlying model name.
- Confirm that the deployment supports the Responses API and the required structured and visual inputs.
- When `AZURE_OPENAI_ENDPOINT` contains a value, ReactXtract uses Azure OpenAI instead of standard OpenAI.

#### Extraction settings

The recommended POC defaults are:

```dotenv
AI_PDF_CHUNK_PAGES=10
AI_KEYWORD_CONTEXT_PAGES=1
AI_INPUT_MODE=hybrid
```

Input modes:

- `hybrid` — recommended; sends extracted PyMuPDF text and tables, plus only pages that require visual interpretation
- `text` — sends native PDF text and detected tables without visual PDF pages
- `vision` — uses PDF visual input more extensively and may take longer or cost more

#### Token-cost settings

Configure these values for the selected model or deployment:

```dotenv
AI_INPUT_COST_PER_MILLION=2.00
AI_OUTPUT_COST_PER_MILLION=8.00
```

These values are used for estimates displayed by ReactXtract. They do not control the actual price charged by OpenAI or Azure.

Save and close `.env` after configuration.

## 7. Start ReactXtract

Double-click:

```text
runserver.cmd
```

The script:

1. Verifies that `.venv` exists.
2. Verifies that `.env` exists.
3. Applies all pending Django database migrations.
4. Runs Django system checks.
5. Starts the local development server.

Wait for the message indicating that the server is running, then open:

```text
http://127.0.0.1:8000/
```

The command window must remain open while ReactXtract is being used.

## 8. Stop ReactXtract

Select the server command window and press:

```text
Ctrl+C
```

Confirm termination if Windows asks. Closing the command window also stops the local server.

## 9. Process Literature PDFs

1. Open **New extraction**.
2. Enter an optional literature-set title.
3. Select the main article PDF and all applicable supporting-information PDFs together.
4. Select **Extract reaction data**.
5. Keep the processing page open until extraction finishes.
6. Review every reaction and extracted field.
7. Click an individual value under Products, Starting materials, Reagents, Catalysts, or Solvents to highlight that specific value in the PDF.
8. Correct any extracted field that requires reviewer changes.
9. Select **Save work** only after review.

Important behavior:

- Extracted reaction fields are temporary until **Save work** is selected.
- Refreshing or leaving an unsaved review discards the temporary extraction and associated uploaded files.
- The main article and supporting information should normally be uploaded together.
- A spectra-only supporting-information file may correctly return no reactions because characterization alone does not prove a preparative transformation.

## 10. Saved Records and Exports

Open **Records** to view saved extraction jobs.

Available exports include:

- Reaction CSV
- JSON
- Token-cost CSV
- Export-all CSV

Saved records include extraction values, confidence scores, source evidence, lookup matches, token usage, estimated cost, AI/local extraction time, and total time from job creation until the reviewer selected **Save work**.

### 10.1 Human confidence and accuracy review workbook

Use `ReactXtract_Field_Confidence_Accuracy_Template.xlsx` when conducting a formal human review of extracted fields.

1. Open the workbook and read the **Instructions** sheet.
2. Use one row on **Accuracy Review** for each reaction.
3. Paste each extracted value and its AI confidence score from ReactXtract.
4. Enter **Human Accuracy** from 0% to 100% for every reviewed field.
5. Use 100% for a fully correct field, 0% for an incorrect field, or an intermediate percentage for a partially correct field.
6. Leave Human Accuracy blank when the field was not reviewed or is not applicable.
7. Record corrections or explanations under **Reviewer Comments**.
8. Save a separate working copy named for the literature set and reviewer.

The workbook includes all 12 extraction fields, input validation, color-coded confidence and accuracy cells, and automatic averages per reaction.

## 11. Local Files and Data

Each installation stores its own independent local data:

| Data | Location |
|---|---|
| SQLite database | `server\db.sqlite3` |
| Uploaded PDFs | `media\uploads\` |
| Extracted text | `media\extracted_text\` |
| API and local configuration | `.env` |
| Python virtual environment | `.venv\` |

These records are not synchronized through GitHub. Pulling source-code updates does not combine the databases of different users.

Do not delete `server\db.sqlite3` or the `media` directory if existing local records must be retained. Back up both together when preserving POC data.

## 12. Pull Updates from GitHub

Before updating:

1. Stop ReactXtract with `Ctrl+C`.
2. Ensure important local data is backed up.
3. Do not modify tracked source files unless working as a developer.

Open PowerShell in the ReactXtract folder:

```powershell
git status
git pull
```

If `git status` reports local source-code changes, do not discard them without confirming with the project team.

After a successful pull:

1. Double-click `setup.cmd` again. It updates installed requirements and preserves `.env`.
2. Double-click `runserver.cmd`. It applies new migrations before starting the server.

## 13. Troubleshooting

### 13.1 `git` is not recognized

Git is missing or not on `PATH`.

1. Install Git for Windows.
2. Close and reopen PowerShell.
3. Run `git --version` again.

### 13.2 Python was not found

Install 64-bit Python 3.12 or 3.13 and enable **Add Python to PATH**. Then reopen the command window and rerun `setup.cmd`.

### 13.3 The virtual environment could not be created

Check:

- Python is installed correctly.
- The user can write to the ReactXtract directory.
- Security software is not blocking Python.
- The project is not installed in a read-only or restricted folder.

Delete a partially created `.venv` only when no setup process is running, then rerun `setup.cmd`.

### 13.4 Requirements could not be installed

Check:

- Internet access
- Corporate proxy or firewall rules
- Access to the Python package index
- Available disk space

Rerun `setup.cmd` after the connection issue is resolved.

### 13.5 `.env` was not found

Run `setup.cmd`. If necessary, manually copy:

```powershell
Copy-Item .env.example .env
```

Then configure the required credentials.

### 13.6 Missing OpenAI or Azure OpenAI settings

The application cannot extract reactions without valid AI credentials.

- For standard OpenAI, set `OPENAI_API_KEY` and `OPENAI_MODEL`.
- For Azure, set `AZURE_OPENAI_ENDPOINT`, `AZURE_OPENAI_API_KEY`, and `AZURE_OPENAI_DEPLOYMENT`.
- Do not configure a non-empty Azure endpoint when intending to use standard OpenAI.

Restart `runserver.cmd` after changing `.env`.

### 13.7 Port 8000 is already in use

Stop the other ReactXtract or Django process. If another application must keep port 8000, start ReactXtract manually on another port:

```powershell
.\.venv\Scripts\python.exe server\manage.py runserver 127.0.0.1:8001
```

Then open:

```text
http://127.0.0.1:8001/
```

### 13.8 The browser cannot open ReactXtract

Verify:

- `runserver.cmd` is still open.
- The command window does not show an error.
- The address is exactly `http://127.0.0.1:8000/`.
- A firewall or endpoint-security tool is not blocking local Python connections.

### 13.9 Extraction returns no reactions

Confirm that:

- The main article was uploaded, not only spectra or characterization files.
- Supporting information was uploaded together with the article when applicable.
- The selected PDFs contain an explicit procedure, preparative scheme, or source-supported product-forming transformation.
- The AI credentials and model/deployment are compatible.

ReactXtract intentionally excludes unsupported inference, biological assays, characterization-only entries, work-up steps, and failed reactions.

### 13.10 PDF highlighting does not find a value

The PDF text layer may use different typography or contain the information only in a structure or image. Check the cited page manually using **Original PDF**. Bounding-box evidence is used when available, but not every image-only value has searchable PDF text.

## 14. POC Security and Usage Notes

- ReactXtract uses Django's local development server and must not be exposed directly to the public internet.
- Keep `.env`, API keys, uploaded PDFs, extracted text, and the local database private.
- Confirm that users are authorized to send selected literature content to the configured AI provider.
- API calls may incur costs.
- AI output must be reviewed before saving or using it for downstream decisions.
- Local lookup lists are advisory and non-exhaustive; unlisted source-supported values remain valid.

## 15. Quick Reference

### First installation

```text
1. Install Git and Python 3.12/3.13.
2. Clone https://github.com/inno-mxrvs/ReactXtract.git.
3. Double-click setup.cmd.
4. Configure .env.
5. Double-click runserver.cmd.
6. Open http://127.0.0.1:8000/.
```

### Normal startup

```text
1. Double-click runserver.cmd.
2. Open http://127.0.0.1:8000/.
```

### Stop

```text
Press Ctrl+C in the server window.
```

### Update

```text
1. Stop the server.
2. Run git pull.
3. Run setup.cmd.
4. Run runserver.cmd.
```
