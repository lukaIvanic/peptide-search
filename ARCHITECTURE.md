# Peptide Literature Extractor — Architecture

## Overview

This document describes the main data flows and module responsibilities in the Peptide Literature Extractor project.

## Directory Structure

```
app/
├── config.py               # Environment configuration
├── db.py                   # Engine/session initialization + init_db()
├── main.py                 # FastAPI bootstrap + router registration + static serving
├── api/
│   └── routers/            # Domain routers
│       ├── system_router.py
│       ├── search_router.py
│       ├── extraction_router.py
│       ├── papers_router.py
│       ├── runs_router.py
│       ├── metadata_router.py
│       └── baseline_router.py
├── prompts.py              # Schema spec + prompt builders
├── schemas.py              # Pydantic request/response models
├── services/               # Use-case orchestration
│   ├── search_service.py   # Multi-source search with dedupe + observability
│   └── extraction_service.py # Extraction pipeline orchestration
├── integrations/           # External I/O adapters
│   ├── document/           # PDF/HTML fetching and text extraction
│   │   └── extractor.py
│   └── llm/                # LLM provider adapters
│       ├── base.py         # DocumentInput + capabilities + protocol
│       ├── openai.py       # OpenAI (Responses API, Chat Completions)
│       ├── deepseek.py     # DeepSeek (OpenAI-compatible)
│       └── mock.py         # Mock provider for demos
└── persistence/            # Database layer
    ├── models.py           # SQLModel table definitions (new + legacy)
    ├── repository.py       # Paper/Run/Entity persistence helpers
    └── migrations/         # Alembic migrations

public/                     # Static frontend
├── index.html
├── app.js                  # Dashboard orchestration entry
├── baseline.js             # Baseline page orchestration entry
├── js/
│   ├── api.js              # API client module
│   ├── state.js            # Application state
│   └── renderers.js        # DOM rendering functions
│   ├── dashboard/paper_filters.js  # Dashboard filter state + CSV helpers
│   └── baseline/helpers.js         # Baseline shared constants/helpers
└── styles.css

cli/                        # Batch processing CLI
└── batch.py                # Typer CLI for batch extraction
```

## Main Data Flows

### 1. Search Flow

```
User Query
    │
    ▼
GET /api/search?q=...
    │
    ▼
search_all_free_sources()
    │
    ├──► search_pmc()
    ├──► search_arxiv()
    ├──► search_europe_pmc()
    └──► search_semantic_scholar()
    │
    ▼
Dedupe by DOI/URL + Sort by reliability
    │
    ▼
SearchResponse (list of SearchItem)
```

### 2. Interactive Extraction Flow

```
User provides URL or uploads PDF
    │
    ▼
POST /api/extract or POST /api/extract-file
    │
    ▼
run_extraction() / run_extraction_from_file()
    │
    ├──► DocumentInput.from_url() / DocumentInput.from_file() / DocumentInput.from_text()
    │       │
    │       ▼
    │    DocumentExtractor.fetch_and_extract_text() (if provider can't process PDF directly)
    │
    ├──► build_system_prompt()
    ├──► build_user_prompt()
    │
    ├──► Provider.generate()
    │       │
    │       ▼
    │    JSON response
    │
    ├──► Validate with ExtractionPayload schema
    │
    └──► PaperRepository.upsert() + ExtractionRepository.save_extraction()
            │
            ├──► Upsert Paper
            ├──► Create ExtractionRun (run-level metadata)
            └──► Create ExtractionEntity (per entity)
    │
    ▼
ExtractResponse
```

### 3. Batch Extraction Flow (CLI)

```
Input file (URLs/DOIs, one per line)
    │
    ▼
cli/batch.py extract --input urls.txt
    │
    ▼
For each URL/DOI:
    │
    ├──► Check if already extracted (dedupe)
    │
    ├──► run_extraction() (same as interactive)
    │
    └──► Log progress/errors
    │
    ▼
Summary: extracted N, skipped M, failed K
```

## Module Responsibilities

### `app/main.py` — HTTP Bootstrap
- Initializes FastAPI app, startup/shutdown queue wiring, and static frontend routes
- Registers domain routers from `app/api/routers/*`

### `app/api/routers/` — HTTP Domains
- `system_router.py`: health, admin reset, SSE stream
- `search_router.py`: discovery + enqueue
- `extraction_router.py`: single-run extraction and file upload enqueue
- `papers_router.py`: papers list/detail and force re-extract
- `runs_router.py`: run detail/history/retry/failure analytics
- `metadata_router.py`: prompts, quality rules, entities
- `baseline_router.py`: baseline case flows and batch flows

### `app/integrations/llm/` — LLM Providers
- Abstract provider interface (`LLMProvider` protocol)
- `DocumentInput` abstraction (text, URL, or file bytes)
- Provider-specific API calls (OpenAI Responses API, Chat Completions, etc.)
- JSON response cleaning and validation

### `app/services/search_service.py` — Paper Sources + Search Orchestration
- Contains the current per-source search implementations (PMC, arXiv, Europe PMC, Semantic Scholar)
- Combines results, dedupes, sorts by reliability, and logs errors (observability)

### `app/integrations/document/` — Document Processing
- Fetch content from URLs (with browser headers)
- PDF text extraction (pypdf)
- HTML text extraction (BeautifulSoup)
- Content type detection

### `app/services/` — Business Logic
- **Search** (`search_service.py`): orchestrates multi-source search, dedupe, sort, and logs errors
- **Extraction** (`extraction_service.py`): coordinates document input → LLM → validation → persistence
- **Failure reason** (`failure_reason.py`): normalizes and buckets run failures for analytics/drilldown
- **View builders** (`view_builders.py`): shared response payload shaping for prompts/runs
- **Runtime maintenance** (`runtime_maintenance.py`): startup hygiene (backfill + stale-run cancellation)
- **Baseline helpers** (`baseline_helpers.py`): source/keying/grouping utilities for baseline workflows

### `app/persistence/` — Data Layer
- SQLModel table definitions
- Repository pattern for CRUD operations
- Transaction management
- Alembic migrations for schema evolution

### `public/` — Frontend
- Static HTML/CSS/JS served by FastAPI
- Modular JS: API client, state management, renderers
- Tailwind CSS via CDN

### `cli/` — Batch Processing
- Typer CLI for batch extraction
- Progress reporting
- Dedupe/skip already-extracted

## Database Schema

```
┌─────────────────────────────────────────────────────────────┐
│                         Paper                                │
├─────────────────────────────────────────────────────────────┤
│ id | title | doi | url | source | year | authors_json       │
│ created_at                                                   │
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
│ peptide_sequence_three_letter | n_terminal_mod | c_terminal │
│ chemical_formula | smiles | inchi | labels | morphology     │
│ ph | concentration | concentration_units | temperature_c    │
│ is_hydrogel | cac | cgc | mgc | validation_methods          │
│ process_protocol | reported_characteristics                  │
└─────────────────────────────────────────────────────────────┘
```

Notes:
- New extractions are stored in `ExtractionRun` + `ExtractionEntity`.
- Older databases may also have a legacy `Extraction` table. The UI/API will still surface these rows (see `/api/papers/{paper_id}/extractions`).

## Configuration

Environment variables (from `.env`):

| Variable | Description | Default |
|----------|-------------|---------|
| `LLM_PROVIDER` | Provider to use: `mock`, `openai`, `deepseek` | `mock` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model | `gpt-4o` |
| `DEEPSEEK_API_KEY` | DeepSeek API key | — |
| `DEEPSEEK_MODEL` | DeepSeek model | `deepseek-chat` |
| `DB_URL` | SQLite connection string | `sqlite:///peptide_search.db` |
| `MAX_TOKENS` | LLM max output tokens | `2000` |
| `TEMPERATURE` | LLM temperature | `0.2` |
| `INCLUDE_DEFINITIONS` | Include domain definitions in prompt | `true` |
