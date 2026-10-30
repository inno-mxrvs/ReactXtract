# ReactXtract

ReactXtract is a Django application for extracting structured chemical reaction data from literature PDFs. It follows the same server-rendered Django/client-static setup as `Returned-Mail-AI-Web-App`, adapted to this project's chemistry requirements.

For detailed Windows installation, configuration, operation, update, and troubleshooting instructions, see [USER_GUIDE.md](USER_GUIDE.md).

## Pipeline

1. Upload one or more article/supporting-information PDFs.
2. Convert each PDF to a durable UTF-8 `.txt` file with original page boundaries, column-aware reading order, and detectable tables represented as explicit rows.
3. Find candidate pages in the generated text using section keywords plus scheme, reaction-condition, procedure, and repeated-yield signals, then feed selected text-file page chunks to AI. Attach only the corresponding PDF pages that still require visual interpretation.
4. Consolidate exact duplicates locally using normalized reaction IDs, product names, source pages, and field values. Send only ambiguous duplicate pairs to AI for a decision; clearly distinct records never enter a consolidation prompt.
5. Present extracted reactions as a signed, temporary review; no extracted field values are written to SQLite yet.
6. Save reaction records only when the reviewer clicks **Save work**. The browser warns before refresh or navigation; confirming departure discards the temporary job, audit rows, and uploaded draft files.

Saved jobs, source-document references, token usage, and estimated cost remain available for audit. Abandoned temporary extractions are removed rather than listed as saved records.

Processing and temporary-review jobs are never shown in Saved records. Leaving for Records, home, or another extraction requests cooperative cancellation of active AI work; after the current API call returns, the job, usage rows, document rows, uploaded PDFs, and generated text files are deleted. Interrupted processing jobs are removed by stale-job cleanup.

The processing overlay shows a live elapsed timer. The exact server-side extraction duration is stored in milliseconds on the job, while `completed_at` records when the reviewer clicks **Save work** and the reactions are committed to SQLite. Both values are displayed in Saved records and included in job exports.

Consolidation is evidence-preserving: AI can only classify an ambiguous pair and cannot rewrite a reaction. Confirmed merges are performed locally, and every selected value keeps the confidence, quote, source page, and bounding box returned with that original extracted value. AI-confirmed matches below the conservative 90% threshold remain separate.

`ReactXtract_Strict_Instructions_updated.txt` is loaded at extraction time and is the source of truth for the AI prompt and candidate-page keywords. It expands the extraction contract with Reaction temperature, Type of reaction description, and Yield. `ReactXtract_Strict_Instructions.txt` and `ReactXtract_Instructions.txt` remain available as prior-rule references but are not loaded by extraction. The application stores confidence and page evidence for every extracted field.

The files under `lookup list/` are optional, non-exhaustive local vocabularies. After AI extraction, an exact solvent name or synonym is normalized to its canonical solvent name, while values absent from the lookup are retained unchanged. `ReagCat.txt` is shared by Reagents and Catalysts: `WORKNAME` supplies matching aliases and `MNAME` supplies the canonical output when present. A record without `MNAME` is tagged but its extracted value is retained, and ambiguous aliases are never normalized. Recognized reaction-condition phrases are tagged without rewriting the extracted condition text. Products, Starting materials, Reaction time, Reaction pressure, and Number of reaction stages have no local lookup normalization. Lookup codes and matches appear in the review workspace and exports. The lookup files are never added to the AI request, so they add no prompt tokens and never act as validation gates.

Before returning a reaction, the model performs a role check for products, starting materials, reagents, catalysts, and solvents. Each populated role must be supported by evidence for that specific transformation; work-up and purification chemicals are excluded, and ambiguous roles are not guessed.

Extracted field values preserve chemical typography with Unicode subscripts (for example, `Na₂SO₄` and `CH₂Cl₂`). A conservative local formatter repairs formula indices flattened by PDF text layers while leaving compound IDs, locants, measurements, and exact evidence quotes unchanged.

The review workspace uses PyMuPDF to render cited pages and highlight the words matching the selected extracted field. List fields show one clickable **Highlight value** chip per product, starting material, reagent, catalyst, or solvent, allowing a reviewer to highlight one value instead of the complete field. These chips update as the reviewer edits a field. Evidence quotes anchor the correct passage, Unicode chemical subscripts are normalized to the PDF text layer for matching, and the stored bounding box is used only when textual matching is unavailable. The original PDF remains available from the viewer footer.

## Setup (Windows PowerShell)

For automatic Windows setup, double-click `setup.cmd`. It creates `.venv`, installs `requirements.txt`, and copies `.env.example` to `.env` when needed. Configure the API credentials in `.env`, then double-click `runserver.cmd`; it applies migrations, checks Django, and starts the app at `http://127.0.0.1:8000/`.

The equivalent manual commands are:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure either the standard OpenAI variables or the Azure OpenAI variables. `AI_PDF_CHUNK_PAGES` and `AI_KEYWORD_CONTEXT_PAGES` control the page-window size and token usage. `AI_INPUT_MODE` accepts `hybrid` (default), `text`, or `vision`; hybrid uses native PyMuPDF text/tables plus targeted visual pages.

Column-aware extraction groups positioned text blocks by reading column and saves the result under `media/extracted_text/`. The review workspace provides an **Extracted text** download for each document. PyMuPDF tables are included only when a valid multi-row, multi-column structure is recovered; captioned tables that cannot be reconstructed, image tables, schemes, and sparse image pages automatically remain in the visual subset.

```powershell
py server\manage.py migrate
py server\manage.py runserver
```

Open `http://127.0.0.1:8000/`.

## Cost configuration

`AI_INPUT_COST_PER_MILLION` and `AI_OUTPUT_COST_PER_MILLION` are deliberately environment-controlled. Set them to the rates for your selected model/deployment. Every model call stores prompt, completion, total tokens, and estimated USD cost.

