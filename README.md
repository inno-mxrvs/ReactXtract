# ReactXtract

ReactXtract is a Django application for extracting structured chemical reaction data from literature PDFs. It follows the same server-rendered Django/client-static setup as `Returned-Mail-AI-Web-App`, adapted to this project's chemistry requirements.

For detailed Windows installation, configuration, operation, update, and troubleshooting instructions, see [USER_GUIDE.md](USER_GUIDE.md).

For field-level human evaluation, use [ReactXtract_Per_File_Product_Accuracy_Template.xlsx](ReactXtract_Per_File_Product_Accuracy_Template.xlsx). Saved database records can be exported directly into this workbook structure, with one worksheet per source PDF and exactly one review block per extracted product. Records-page search, status, and processed-date filters also limit the Excel export.

## Pipeline

1. Upload one or more article/supporting-information PDFs.
2. Convert each PDF to a durable UTF-8 `.txt` file with original page boundaries, column-aware reading order, and detectable tables represented as explicit rows.
3. Find candidate pages using section keywords plus scheme, reaction-condition, procedure, and repeated-yield signals. A page containing reaction content before a References heading remains eligible. Adaptive chunking separates reaction-dense visual pages into bounded, non-overlapping chunks that can run concurrently. Hybrid mode sends native text plus bounded 180-DPI reaction-scheme crops instead of complete visual PDF pages.
4. Consolidate exact duplicates locally using normalized reaction IDs, product names, source pages, and field values. Send only ambiguous duplicate pairs to AI for a decision; clearly distinct records never enter a consolidation prompt.
5. Present extracted reactions as a signed, temporary review; no extracted field values are written to SQLite yet.
6. Save reaction records only when the reviewer clicks **Save work**. The browser warns before refresh or navigation; confirming departure discards the temporary job, audit rows, and uploaded draft files.

Saved jobs, source-document references, token usage, and estimated cost remain available for audit. Abandoned temporary extractions are removed rather than listed as saved records.

Processing and temporary-review jobs are never shown in Saved records. Leaving for Records, home, or another extraction requests cooperative cancellation of active AI work; after the current API call returns, the job, usage rows, document rows, uploaded PDFs, and generated text files are deleted. Interrupted processing jobs are removed by stale-job cleanup.

The processing overlay shows a live elapsed timer. ReactXtract stores the AI/local extraction duration separately from the end-to-end duration measured from job creation until the reviewer clicks **Save work**. `completed_at` records when the reactions are committed to SQLite. Extraction time, total time to save, total tokens, and total processing cost are displayed or included in the per-file Excel export.

Consolidation is evidence-preserving: AI can only classify an ambiguous pair and cannot rewrite a reaction. Confirmed merges are performed locally, and every selected value keeps the confidence, quote, source page, and bounding box returned with that original extracted value. AI-confirmed matches below the conservative 90% threshold remain separate.

`ReactXtract_Strict_Instructions_updated.txt` is loaded at extraction time and is the source of truth for the AI prompt and candidate-page keywords. It expands the extraction contract with Reaction temperature, Type of reaction description, and Yield. `ReactXtract_Strict_Instructions.txt` and `ReactXtract_Instructions.txt` remain available as prior-rule references but are not loaded by extraction. The application stores confidence and page evidence for every extracted field.

The files under `lookup list/` are optional, non-exhaustive local vocabularies. After AI extraction, exact names and synonyms are displayed using the canonical lookup name; unmatched values remain unchanged. `ReagCat.txt` is preferred for Reagents and Catalysts, with the solvent vocabulary used as an identity-name fallback when appropriate. `WORKNAME` supplies matching aliases and `MNAME` supplies the canonical output when present. A ReagCat record without `MNAME` is tagged but retained, and ambiguous aliases are never normalized. Recognized reaction-condition phrases are rewritten to their approved lookup display names. Products, Starting materials, Reaction time, Reaction pressure, and Number of reaction stages have no local lookup normalization. Lookup codes and matches appear in the review workspace and exports. The lookup files are never added to the AI request, so they add no prompt tokens and never act as validation gates.

Deterministic post-extraction safeguards reject a percentage as Yield unless its cited quote explicitly contains the word `yield`, sort multiple numeric temperatures into a lowest-to-highest range, reject bare numeric products such as `14`, and prevent numeric compound labels from matching atom assignments such as `H14` or `C14` in characterization text. Explicit product mixtures such as `inseparable mixture of A and B` are split into separate product reaction candidates while retaining their shared source-supported reaction fields.

Before returning a reaction, the model performs a role check for products, starting materials, reagents, catalysts, and solvents. Each populated role must be supported by evidence for that specific transformation; work-up and purification chemicals are excluded, and ambiguous roles are not guessed.

Extracted field values preserve chemical typography with Unicode subscripts (for example, `Na₂SO₄` and `CH₂Cl₂`). A conservative local formatter repairs formula indices flattened by PDF text layers while leaving compound IDs, locants, measurements, and exact evidence quotes unchanged.

The review workspace uses PyMuPDF to render cited pages and highlight the words matching the selected extracted field. List fields show one clickable **Highlight value** chip per product, starting material, reagent, catalyst, or solvent, allowing a reviewer to highlight one value instead of the complete field. These chips update as the reviewer edits a field. Lookup-normalized display values retain their original extracted term for source highlighting, and supported abbreviations such as `Py` locate the exact source word `pyridine`. Highlighting requires complete searchable PDF-word matches, so `acetic anhydride` cannot incorrectly match `acetic` inside another chemical name. Image-only values and AI visual bounding boxes are never highlighted; the viewer only opens their cited page. Evidence quotes anchor searchable text and Unicode chemical subscripts are normalized to the PDF text layer. The original PDF remains available from the viewer footer.

Multistage reactions include an ordered, source-supported `stage_details` breakdown. The reaction tree nests identifiers such as `RX-0001A` and `RX-0001B` under the parent reaction, and the review pane shows each stage's transformation description, starting materials, product or intermediate, confidence, and source evidence. Older records that contain only a numeric stage count display clearly marked placeholders rather than invented stage details.

## Setup (Windows PowerShell)

For automatic Windows setup, double-click `setup.cmd`. It creates `.venv`, installs `requirements.txt`, and creates a placeholder `.env` when needed. Replace that file with the approved `.env` received through Teams, then double-click `runserver.cmd`; it applies migrations, checks Django, and starts the app at `http://127.0.0.1:8000/`.

The equivalent manual commands are:

```powershell
py -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
```

Configure either the standard OpenAI variables or the Azure OpenAI variables. `AI_INPUT_MODE` accepts `hybrid` (default), `text`, or `vision`; hybrid uses native PyMuPDF text/tables plus targeted reaction-scheme crops. Adaptive chunking keeps ordinary small selections together and splits reaction-dense visual inputs according to `AI_REACTION_DENSE_CHUNK_PAGES` (default `2`). `AI_MAX_PARALLEL_REQUESTS` overlaps independent chunks (default `2`). Compatible reasoning deployments default to `AI_REASONING_EFFORT=none`; GPT-5.5 also maps a legacy `minimal` setting to `none`. API attempts time out after `AI_REQUEST_TIMEOUT_SECONDS=300` and retry at most `AI_MAX_RETRIES=1` time. Each attempt stores its status, duration, error, prompt/completion tokens, and reasoning-token count.

Column-aware extraction groups positioned text blocks by reading column and saves the result under `media/extracted_text/`. The review workspace provides an **Extracted text** download for each document. PyMuPDF tables are included only when a valid multi-row, multi-column structure is recovered; captioned tables that cannot be reconstructed, image tables, schemes, and sparse image pages automatically remain in the visual subset.

```powershell
py server\manage.py migrate
py server\manage.py runserver
```

Open `http://127.0.0.1:8000/`.

## Cost configuration

`AI_INPUT_COST_PER_MILLION` and `AI_OUTPUT_COST_PER_MILLION` are deliberately environment-controlled. Set them to the rates for your selected model/deployment. Every model call stores prompt, completion, total tokens, and estimated USD cost.

