## Peptide Literature Extractor (Prototype)

Interactive prototype to search open-access scientific literature (PubMed Central, Europe PMC, arXiv, Semantic Scholar), fetch PDFs/HTML, call an LLM to extract structured peptide/molecule data, and store results in a local SQLite database. A lightweight Tailwind UI presents search, extraction, and stored results.

### Project goal (high level)
This repository is the **automatic literature → structured data extraction** component of a broader effort to capture **peptide** knowledge (especially **self-assembling / hydrogel-forming peptides**) in a form that researchers and downstream modeling workflows can use.

For a longer write-up (goal, scope, your role in the group project, and similar/prior projects), see `documentation.md`.

### Features
- Search via PubMed Central (PMC), Europe PMC, arXiv, and Semantic Scholar (open-access sources).
- Paste a PDF/article URL for on-the-fly text extraction (PDF parsed with `pypdf`; HTML parsed with `BeautifulSoup`).
- Modular LLM providers:
  - Mock provider (no API key) for demos.
  - OpenAI provider (Responses API; supports direct PDF URL + PDF upload).
  - DeepSeek provider (OpenAI-compatible chat completions API; text-only).
- Extraction prompt includes domain definitions from `Peptide LLM/definitions_for_llms.md`.
- Structured JSON output validated by Pydantic; key fields persisted in SQLite.
- Simple Tailwind-based web UI.

### Tech
- Backend: FastAPI, SQLModel/SQLAlchemy, httpx
- DB: SQLite (`peptide_search.db` in project root)
- Frontend: static HTML/CSS/JS (Tailwind CDN)

### Setup
1) Requirements
- Python 3.10+ recommended

2) Create and activate a virtual environment (Windows PowerShell):
```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
```

3) Install dependencies:
```powershell
pip install -r requirements.txt
```

4) Configure environment
- Copy `.env.example` to `.env` and adjust values as needed:
  - `LLM_PROVIDER` is required (one of `openai`, `openai-full`, `openai-mini`, `openai-nano`, `deepseek`, `mock`).
  - To use DeepSeek, set `LLM_PROVIDER=deepseek` and `DEEPSEEK_API_KEY=...`.

5) Run the server:
```powershell
.\scripts\dev_server.ps1
```
If you need maximum stability (no hot reloads), use:
```powershell
.\scripts\dev_server_no_reload.ps1
```

6) Open the UI:
- Navigate to `http://localhost:8000` in your browser.

### Frontend config (decoupled hosting)
If you want to host the frontend separately from the API, set the runtime config in `public/app_config.js`:
```js
window.PEPTIDE_APP_CONFIG = {
  apiBase: 'http://localhost:8000/api',
  streamBase: 'http://localhost:8000/api/stream',
};
```
Then set `CORS_ORIGINS` in your `.env` (comma-separated) so the API accepts requests from the frontend origin:
```
CORS_ORIGINS=http://localhost:5173,http://localhost:3000
```

### Usage
- Use the search bar to query open-access sources (e.g., "self-assembling peptide hydrogel").
- Click "Open" to view an article, or click "Extract" to run the extraction pipeline (for URLs that are directly accessible).
- Alternatively, paste a PDF or article URL in the right input and press "Extract".
- The "Latest Extraction" panel shows the structured JSON; "Stored Papers" lists papers with extraction counts.

### UI Tour
- **Dashboard (`/`)**: search, queue extractions, and open paper/run details.
- **Entity Explorer (`/entities`)**: filter across all extracted entities, view evidence gaps, and compare prompt versions.
- **Run Details (`/runs/{id}`)**: inspect prompts, raw JSON, follow-ups, and version history.
- **Run Editor (`/runs/{id}/edit`)**: edit fields and evidence (append-only versions).
- **Help (`/help`)**: quickstart tips and troubleshooting.

### Switching Providers
- Mock (default): no external calls; returns a realistic demo JSON payload.
- OpenAI: set `LLM_PROVIDER=openai` and `OPENAI_API_KEY=...` (supports direct PDF URL and file upload).
- DeepSeek: ensure `DEEPSEEK_API_KEY` is set and optionally pick a model with `DEEPSEEK_MODEL` (defaults to `deepseek-chat`).

### Project Structure
```
app/
  config.py                 # environment/config
  db.py                     # engine/session init + init_db()
  main.py                   # FastAPI app + routes + static serving
  schemas.py                # Pydantic models for API and payloads
  prompts.py                # schema spec + prompt builders + definitions loader
  services/
    search_service.py       # multi-source open-access search (PMC/arXiv/Europe PMC/S2)
    extraction_service.py   # extraction orchestration
  integrations/
    llm/                    # LLM providers (OpenAI/DeepSeek/Mock)
    document/               # PDF/HTML text extraction
  persistence/
    models.py               # SQLModel tables (new + legacy)
    repository.py           # persistence helpers
    migrations/             # Alembic migrations
cli/
  batch.py                  # batch extraction CLI
public/
  index.html                # UI
  app.js                    # UI logic
  js/                       # UI modules
  styles.css                # extra styles
Peptide LLM/
  definitions_for_llms.md   # domain definitions (included in prompts)
alembic.ini                 # Alembic config
```

### Notes
- PDF parsing is inherently imperfect; for best results, use accessible, clean PDFs or HTML full text.
- The schema is intentionally flexible to cover both peptides and general molecules (formula/SMILES/InChI).
- The database stores raw model JSON for traceability alongside key searchable fields.

### Batch Processing CLI

Run extractions on multiple papers from the command line:

```powershell
# Show CLI info and provider capabilities
python -m cli.batch info

# Show database statistics
python -m cli.batch stats

# Extract from a list of URLs/DOIs
python -m cli.batch extract --input urls.txt

# Skip papers already in the database
python -m cli.batch extract --input urls.txt --skip-existing

# Save results to JSON
python -m cli.batch extract --input urls.txt --output results.json
```

Input file format (one per line):
```
https://example.com/paper.pdf
10.1234/example.doi
# Lines starting with # are ignored
```

### Database Migrations

Schema changes are managed with Alembic:

```powershell
# Apply pending migrations
alembic upgrade head

# Create a new migration after model changes
alembic revision --autogenerate -m "Description of changes"

# Show current migration status
alembic current
```

### Architecture

See `ARCHITECTURE.md` for detailed documentation of:
- Module boundaries and responsibilities
- Data flow diagrams
- Database schema
- Configuration options

### Deployment (Render)

For a managed demo deployment with persistent SQLite storage and optional access gate, see `docs/DEPLOY_RENDER.md`.

### Roadmap (optional)
- Improve PDF text extraction (layout parsing, figure/table handling).
- Add additional providers (e.g., Anthropic, Claude) via the same interface.
- Add filters and advanced search on the UI (e.g., pH, morphology, labels).
- Add batch extraction from the web UI with progress tracking.

