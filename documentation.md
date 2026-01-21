# Peptide Literature Extractor — System Design Documentation

## Overview

The **Peptide Literature Extractor** is a web-based tool designed to automate the extraction of structured scientific data from academic papers. It searches open-access repositories for papers and then uses Large Language Models (LLMs) to parse and extract key information into a standardized JSON format stored in a database.

**Primary domain focus (what this project is trying to capture):** peptide sequences and their experimentally reported properties — especially **self-assembling peptides** and **peptide-based supramolecular assemblies / hydrogels**. The core fields are designed around peptide identity (sequence + terminal modifications) plus assembly conditions (pH, concentration, temperature), morphology, validation methods, and related thresholds (CAC/CGC/MGC).

**Secondary/optional scope:** the extraction schema also allows recording non-peptide “molecules” (e.g., chemical formula / SMILES / InChI) when papers discuss relevant non-peptide components, but the included domain definitions and reference datasets are peptide-centric (self-assembly/hydrogels, and also labels like catalytic activity, LLPS, antiviral activity).

### High-level goal (the “why”)

The high-level goal (as discussed in this project) is to **turn scattered, unstructured knowledge in scientific papers into a structured dataset** that researchers can search/filter — and that can later be used to support modeling workflows (e.g., training predictors, conditional generation, retrieval-augmented assistants).

In plain terms: **literature → structured peptide data → faster research and better design/selection of candidates for wet-lab work**.

### End-to-end vision (where this repo fits)

This repository is primarily the **literature review automation + structuring** stage:

- **Find papers** (query open-access sources)
- **Fetch paper content** (PDF/HTML)
- **Extract structured fields** (LLM → strict JSON schema)
- **Validate and persist** (schema validation + SQLite storage)
- **Export/use** the dataset downstream (for analysis, modeling, or curation)

Other stages (typically done outside this repo) include training property predictors, running generative design loops, and wet-lab synthesis/validation.

### What molecules we’re targeting (lab relevance)

From the domain definitions and dataset notes included in this project, the most clearly targeted “entities” are:

- **Peptides**, especially **self-assembling peptides** that form supramolecular structures (including **hydrogels**) under specific conditions.

The schema also allows recording non-peptide “molecules” (formula/SMILES/InChI), but that is a secondary capability.

### What makes the final dataset actually useful to researchers

Extraction alone is not enough; usefulness depends on standardization and traceability. A useful research dataset typically needs:

- **Identity clarity**: sequence + terminal modifications (and, if relevant, stereochemistry / non-canonical residues).
- **Experimental context**: pH, concentration (+ units), temperature, buffer/solvent (when reported), morphology, and *how it was validated*.
- **Negative results and missingness**: “not reported” vs “tested and absent” should be distinguishable.
- **Normalization**: canonical units + controlled vocabularies (while keeping original raw values).
- **Provenance**: link each extraction to a paper identifier (DOI/PMID/URL) and retain raw JSON for auditing.
- **Quality control**: schema validation, plausibility checks, and a lightweight human review loop for spot checks/corrections.

### Your role in the group project (what you own)

As discussed: your task is the **automatic extraction pipeline** — converting papers into structured data reliably.

Concretely, that usually means you own:

- **Schema + prompt design** (what fields exist; how “null vs not reported” is handled)
- **Extraction robustness** (PDF/HTML ingestion, table-heavy papers, retries, provider differences)
- **Validation + persistence** (ensuring outputs are parseable, consistent, and stored with provenance)
- **Dataset readiness** (exports, basic normalization hooks, and QA checks that the modeling team can trust)

This is distinct from (but enables) the later work of training models to propose candidate peptides given desired properties.

### Related projects / prior art we looked for (Jan 2026 snapshot)

We searched for similar projects to avoid reinventing common components and to identify trusted datasets/models.

**Paper parsing / PDF-to-structure (helps ingestion and table extraction):**
- [GROBID](https://github.com/kermitt2/grobid) — PDF → TEI XML (metadata, sections, references); commonly used as a foundation.
- [S2ORC doc2json](https://github.com/allenai/s2orc-doc2json) — pipelines for converting papers to a JSON structure (often built on top of GROBID).
- [LayoutParser](https://github.com/Layout-Parser/layout-parser) — layout detection that helps isolate regions/tables for better extraction.

**Domain datasets (useful for validation and/or as training targets):**
- [SAPdb](https://webs.iiitd.edu.in/raghava/sapdb/body.php) — database of self-assembling peptides / nanostructures (high overlap with this project’s “hydrogel/self-assembly” focus).
- [DBAASP](https://dbaasp.org/) — curated antimicrobial peptide activity/structure database.
- [DRAMP](http://dramp.cpu-bioinfor.org/) — curated antimicrobial peptide database.
- [APD](https://aps.unmc.edu/home) — antimicrobial peptide database.

**Extraction toolkits (adjacent approaches, especially for chemistry):**
- [ChemDataExtractor](https://github.com/CambridgeMolecularEngineering/chemdataextractor) — chemical entity/property extraction toolkit (useful patterns even if peptide-focused extraction differs).

**Modeling / generation (downstream of this repo):**
- [ProteinMPNN](https://github.com/dauparas/ProteinMPNN) — structure-conditioned sequence design (inverse folding) for proteins (adjacent to peptide design workflows).
- [RFdiffusion](https://github.com/RosettaCommons/RFdiffusion) — diffusion-based protein design (foundation for many modern protein design pipelines).
- [ProGen2](https://github.com/enijkamp/progen2) and [EvoDiff](https://github.com/microsoft/evodiff) — protein language / diffusion models that are often referenced in sequence generation contexts.

**Not AlphaFold (but related):**
- AlphaFold is a breakthrough in **structure prediction**. It does not directly solve literature extraction or conditional peptide generation, but structure prediction can be a key downstream evaluation step for generated candidates.

### Search plan (queries you can reuse)

When searching for more prior art, it helps to split the problem by stage:

- **Literature → structured paper text**: “PDF to structured XML/JSON scientific papers”, “GROBID”, “doc2json”, “table extraction scientific PDF”
- **Paper text → experimental schema**: “extract experimental conditions pH concentration temperature from papers”, “scientific information extraction hydrogel peptide”
- **Peptide self-assembly/hydrogel datasets**: “self-assembling peptide database hydrogel CGC MGC CAC”
- **Peptide generative modeling**: “conditional peptide generation”, “antimicrobial peptide diffusion model”, “protein language model peptide design”

See **Appendix: Query bank** below for a longer query list and LLM prompt templates.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              USER INTERFACE                                  │
│                         (Tailwind CSS + Vanilla JS)                         │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────────────┐  │
│  │  Search Papers  │  │  Direct URL     │  │  Extraction Results Panel   │  │
│  │  (query input)  │  │  Extraction     │  │  (JSON viewer, key facts)   │  │
│  └────────┬────────┘  └────────┬────────┘  └──────────────▲──────────────┘  │
└───────────┼─────────────────────┼─────────────────────────┼─────────────────┘
            │                     │                         │
            ▼                     ▼                         │
┌─────────────────────────────────────────────────────────────────────────────┐
│                           FASTAPI BACKEND                                    │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         REST API Endpoints                           │    │
│  │  GET  /api/search      - Search open-access repositories            │    │
│  │  POST /api/extract     - Extract data from paper (URL or text)      │    │
│  │  GET  /api/papers      - List stored papers                         │    │
│  │  GET  /api/extractions - List all extractions                       │    │
│  │  GET  /api/health      - Health check & provider info               │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                    │                                         │
│         ┌──────────────────────────┼──────────────────────────┐             │
│         ▼                          ▼                          ▼             │
│  ┌─────────────┐          ┌─────────────────┐         ┌─────────────┐       │
│  │   Search    │          │   Extraction    │         │  Database   │       │
│  │   Service   │          │    Service      │         │   (SQLite)  │       │
│  └──────┬──────┘          └────────┬────────┘         └──────▲──────┘       │
│         │                          │                         │              │
└─────────┼──────────────────────────┼─────────────────────────┼──────────────┘
          │                          │                         │
          ▼                          ▼                         │
┌──────────────────┐      ┌─────────────────────┐              │
│  External APIs   │      │   LLM Providers     │              │
│  ─────────────── │      │   ───────────────   │              │
│  • Europe PMC    │      │   • OpenAI (GPT-5)  │──────────────┘
│  • arXiv         │      │   • DeepSeek        │   (stores extractions)
│  • Semantic Sch. │      │   • Mock (demo)     │
│  • PubMed Central│      └─────────────────────┘
└──────────────────┘
```

---

## Architecture Components

### 1. Frontend (`/public`)

A lightweight single-page application built with vanilla JavaScript and Tailwind CSS.

| File | Purpose |
|------|---------|
| `index.html` | Main HTML structure with search, extraction panel, and results display |
| `app.js` | Client-side logic: API calls, DOM manipulation, result rendering |
| `styles.css` | Custom styles extending Tailwind |

**Key Features:**
- Search input with real-time results from multiple sources
- Direct URL extraction for any accessible PDF/HTML
- Color-coded source badges (Europe PMC, arXiv, etc.)
- JSON viewer with copy functionality
- Extraction comment display (model's explanation)

---

### 2. Backend (`/app`)

A Python FastAPI application providing REST endpoints and orchestrating the extraction pipeline.

#### 2.1 Entry Point (`main.py`)

- Initializes FastAPI app with static file serving
- Defines all REST API endpoints
- Handles database session injection via dependency

#### 2.1.1 Entity Explorer API filters

- `GET /api/entities` supports:
  - `group_by` (optional)
  - `show_missing_key` (boolean)
  - `latest_only` (boolean, latest run overall)
  - `recent_minutes` (integer minutes)
- `GET /api/entities/kpis` supports:
  - `latest_only`
  - `recent_minutes`

#### 2.2 Configuration (`config.py`)

Environment-based configuration loaded from `.env`:

```python
LLM_PROVIDER     # "openai" | "deepseek" | "mock"
OPENAI_API_KEY   # Required for OpenAI
OPENAI_MODEL     # Default: "gpt-4o"
DEEPSEEK_API_KEY # Required for DeepSeek
DB_URL           # SQLite connection string
MAX_TOKENS       # LLM response limit
TEMPERATURE      # LLM creativity (0.0-1.0)
```

#### 2.3 Database Layer (`db.py`, `persistence/models.py`)

**SQLite** database with SQLModel ORM.

**Tables:**
- `Paper` — Stores paper metadata (title, DOI, URL, authors, year)
- `ExtractionRun` — One extraction run; stores the full raw JSON payload + model metadata
- `ExtractionEntity` — One row per extracted entity (peptide or molecule)
- *(Legacy)* `Extraction` — Older schema that may exist in pre-migration databases

```
┌─────────────────────────────────────────────────────────────┐
│                         Paper                                │
├─────────────────────────────────────────────────────────────┤
│ id | title | doi | url | source | year | authors_json       │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ 1:N
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                     ExtractionRun                            │
├─────────────────────────────────────────────────────────────┤
│ id | paper_id | raw_json | comment | model_provider         │
│ model_name | source_text_hash | prompt_version | created_at │
└─────────────────────────────────────────────────────────────┘
                              │
                              │ 1:N
                              ▼
┌─────────────────────────────────────────────────────────────┐
│                    ExtractionEntity                          │
├─────────────────────────────────────────────────────────────┤
│ id | run_id | entity_type | peptide_sequence_one_letter     │
│ n_terminal_mod | c_terminal_mod | chemical_formula | ph     │
│ concentration | morphology | validation_methods             │
│ created_at (via run)                                         │
└─────────────────────────────────────────────────────────────┘
```

#### 2.4 Schemas (`schemas.py`)

Pydantic models for request/response validation:

- `SearchItem` — Paper search result with PDF URL
- `ExtractRequest` — Extraction input (text or URL)
- `ExtractionPayload` — Full extraction output structure
- `ExtractionEntity` — Individual peptide/molecule data

---

### 3. Services (`/app/services`)

#### 3.1 Search Service (`search_service.py`)

Searches multiple open-access repositories in parallel:

| Source | API | PDF Access |
|--------|-----|------------|
| **Europe PMC** | REST API | ✅ Direct PDF URL (most reliable) |
| **arXiv** | Atom XML API | ✅ Direct PDF URL |
| **Semantic Scholar** | Graph API | ✅ openAccessPdf field |
| **PubMed Central** | E-utilities + OA Service | ⚠️ Sometimes requires resolution |

Results are sorted by source reliability (Europe PMC first).

#### 3.2 Extraction Service (`extraction_service.py`)

Orchestrates the extraction pipeline:

```
┌─────────────────┐
│  ExtractRequest │
│  (URL or text)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Is provider OpenAI + PDF URL?      │
│  ─────────────────────────────────  │
│  YES → Use Responses API            │
│        (send PDF URL directly)      │
│  NO  → Extract text locally         │
│        (pypdf + BeautifulSoup)      │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Build prompts with:                │
│  • System prompt (domain defs)      │
│  • User prompt (schema + text)      │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Call LLM Provider                  │
│  → Returns JSON string              │
└────────┬────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────┐
│  Validate & store in database       │
│  → Paper + ExtractionRun + Entity   │
└─────────────────────────────────────┘
```

---

### 4. LLM Providers (`/app/integrations/llm`)

Modular provider system implementing a common interface:

```python
class LLMProvider(Protocol):
    def name(self) -> str: ...
    def model_name(self) -> str: ...
    def capabilities(self) -> LLMCapabilities: ...
    async def generate(system_prompt, user_prompt, document: DocumentInput | None = None, ...) -> str: ...
```

| Provider | File | API | PDF Support |
|----------|------|-----|-------------|
| **OpenAI** | `integrations/llm/openai.py` | Responses API (`/v1/responses`) + Chat Completions | ✅ PDF URL + ✅ PDF upload |
| **DeepSeek** | `integrations/llm/deepseek.py` | Chat Completions | ❌ (text only) |
| **Mock** | `integrations/llm/mock.py` | None (returns demo data) | N/A |

**OpenAI Responses API** enables sending PDF URLs directly:
```python
{
    "role": "user",
    "content": [
        {"type": "input_text", "text": "..."},
        {"type": "input_file", "file_url": "https://...pdf"}
    ]
}
```

---

### 5. Prompts (`prompts.py`)

Builds structured prompts for the LLM:

- **System prompt**: Expert role + domain definitions from `definitions_for_llms.md`
- **User prompt**: Task description + JSON schema + paper text/metadata

**Output Schema** (simplified):
```json
{
  "paper": { "title", "doi", "url", "year", "authors" },
  "entities": [
    {
      "type": "peptide" | "molecule",
      "peptide": { "sequence_one_letter", "n_terminal_mod", "c_terminal_mod", "is_hydrogel" },
      "molecule": { "chemical_formula", "smiles", "inchi" },
      "conditions": { "ph", "concentration", "temperature_c" },
      "morphology": ["fibril", "hydrogel", ...],
      "validation_methods": ["CD", "TEM", "FTIR", ...],
      "thresholds": { "cac", "cgc", "mgc" }
    }
  ],
  "comment": "Brief explanation of what was found or why entities is empty"
}
```

---

### 6. Document Processing (`/app/integrations/document`)

#### PDF/HTML Text Extractor (`extractor.py`)

Fallback text extraction when direct PDF processing isn't available:

- **PDF**: Uses `pypdf` to extract text from all pages
- **HTML**: Uses `BeautifulSoup` with `lxml` parser
- Includes browser-like headers to avoid 403 errors
- Detects unsupported file types (video, images)

---

## Data Flow Example

**User searches "self-assembling peptide hydrogel":**

1. Frontend calls `GET /api/search?q=self-assembling+peptide+hydrogel`
2. Backend queries Europe PMC, arXiv, Semantic Scholar, PMC in parallel
3. Results sorted by source reliability, returned to frontend
4. User clicks "Extract" on a Europe PMC result
5. Frontend calls `POST /api/extract` with `pdf_url`
6. Backend detects OpenAI provider + PDF URL → uses Responses API
7. OpenAI downloads and processes PDF, returns structured JSON
8. Backend validates JSON, stores Paper + ExtractionRun + ExtractionEntity in SQLite
9. Frontend displays extracted data with comment from model

---

## File Structure

```
peptide_search/
├── app/
│   ├── config.py              # Environment configuration
│   ├── db.py                  # Database initialization + init_db()
│   ├── main.py                # FastAPI app + endpoints + static serving
│   ├── prompts.py             # LLM prompt construction
│   ├── schemas.py             # Pydantic request/response models
│   ├── services/
│   │   ├── search_service.py  # Multi-source paper search (and per-source adapters)
│   │   └── extraction_service.py  # Extraction orchestration
│   ├── integrations/
│   │   ├── llm/               # LLM providers (OpenAI/DeepSeek/Mock)
│   │   └── document/          # PDF/HTML text extraction
│   └── persistence/
│       ├── models.py          # SQLModel tables (new + legacy)
│       ├── repository.py      # Persistence helpers
│       └── migrations/        # Alembic migrations
├── cli/
│   └── batch.py               # Batch extraction CLI
├── public/
│   ├── index.html             # Frontend HTML
│   ├── app.js                 # Frontend JavaScript
│   ├── js/                     # Frontend JS modules
│   │   ├── api.js
│   │   ├── state.js
│   │   └── renderers.js
│   └── styles.css             # Custom styles
├── Peptide LLM/
│   ├── definitions_for_llms.md    # Domain definitions for prompts
│   └── Datasets/              # Reference datasets
├── alembic.ini                # Alembic config
├── requirements.txt           # Python dependencies
├── env.example                # Environment template
├── documentation.md           # This file
└── peptide_search.db          # SQLite database (generated)
```

---

## Running the Application

```bash
# 1. Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
source .venv/bin/activate  # Linux/Mac

# 2. Install dependencies
pip install -r requirements.txt

# 3. Configure environment
copy env.example .env
# Edit .env: set LLM_PROVIDER and API key

# 4. Start server
uvicorn app.main:app --reload

# 5. Open browser
# http://localhost:8000
```

---

## Appendix: Literature review workflow (researcher perspective)

This is a practical checklist-style view of what a domain researcher often has to do during literature review before they can *reproduce* or *extend* prior work (adapt for your specific use-case, e.g., hydrogel formation vs antimicrobial activity):

- **Define scope**
  - What property is being optimized (e.g., self-assembly/hydrogel formation, morphology, stability, bioactivity)?
  - What constraints matter (physiological pH, temperature, salt tolerance, cytotoxicity, etc.)?
- **Search and triage**
  - Build query terms, run searches, deduplicate, screen titles/abstracts.
  - Pull full text (prefer structured HTML/XML when available; PDFs often bury key values in tables).
- **Extract what is needed to reproduce**
  - Peptide identity (sequence, terminal modifications, non-canonical residues if present).
  - Experimental conditions (pH, concentration + units, temperature, buffer/solvent, incubation time, triggers).
  - Observations/results (morphology, “hydrogel yes/no”, CAC/CGC/MGC, and validation methods).
  - Protocol details that affect outcomes (mixing, heating/cooling cycles, aging time).
- **Normalize and compare**
  - Convert units, unify vocabulary (“nanofiber” vs “fibril”), and track missingness.
  - Record negative results explicitly when reported.
- **Assess trustworthiness**
  - Look for replication, controls, characterization quality, and whether claims are backed by appropriate methods (e.g., rheology vs vial inversion for gels).

This project’s extractor is meant to automate the most time-consuming parts of that workflow (acquisition + structured extraction), while keeping enough provenance for researchers to verify the result.

## Appendix: Query bank (web search)

Use these across Google/DDG, Semantic Scholar, PubMed, GitHub, and PapersWithCode.

### A) Self-assembling / hydrogel peptide datasets
- `SAPdb self-assembling peptides database hydrogel`
- `self-assembling peptide hydrogel database CGC MGC CAC`
- `peptide hydrogel “critical gelation concentration” dataset`
- `supramolecular peptide hydrogel morphology TEM AFM CD FTIR dataset`

### B) Paper parsing / PDF-to-structure
- `GROBID TEI fulltext extraction scientific PDF`
- `s2orc-doc2json convert pdf to json`
- `ScienceParse AllenAI pdf to json`
- `LayoutParser table extraction PubLayNet`

### C) Scientific information extraction (conditions, tables, entities)
- `extract experimental conditions pH concentration temperature from scientific papers`
- `scientific table information extraction pH concentration`
- `ChemDataExtractor extract chemical properties`

### D) Peptide property databases (validation/training targets)
- `DBAASP download`
- `DRAMP database download`
- `APD antimicrobial peptide database download`
- `LLPS peptide database`
- `antiviral peptide database`

### E) Sequence generation / inverse design (downstream)
- `ProteinMPNN github`
- `RFdiffusion github`
- `ProGen2 github`
- `EvoDiff github`
- `antimicrobial peptide diffusion model github`

## Appendix: Query bank (LLM prompts)

Paste these into your LLM of choice to quickly compile candidate tools (then verify links/licenses manually):

1) **Closest existing projects**
   - “Find open-source or freely available projects that extract structured experimental data about self-assembling peptide hydrogels (sequence, terminal mods, pH, concentration, temperature, morphology, CAC/CGC/MGC). Return a table: name, link, license, I/O formats, last updated.”

2) **Best-in-class PDF → structure**
   - “List the top open-source tools (2026) for converting scientific PDFs into structured text/sections/tables. Compare GROBID vs doc2json vs layout-based approaches; note pros/cons for table-heavy experimental papers.”

3) **Databases to reuse**
   - “List curated peptide databases for self-assembly/hydrogels, antimicrobial/antiviral activity, LLPS, catalytic activity. For each: access method (API/download), license/terms, key fields.”

4) **Modeling approaches**
   - “Given a dataset of peptide sequences + conditions + labels (e.g., self-assembly/hydrogel yes/no), propose modeling approaches for conditional design (predictors + optimization loop vs conditional generative model). Cite example repos/papers.”


