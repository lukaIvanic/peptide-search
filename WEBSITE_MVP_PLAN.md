# Website MVP Plan — Peptide Literature Extractor

Purpose
- Define the MVP for a beautiful, interactive local website to: search → select → batch run → watch live progress → inspect details. Future phases add manual review, editing, versioning, richer search/filters, and exports.

Context and constraints (v0.1 MVP)
- Single-user, local only. No deployment, no auth.
- Local SQLite DB. Internal HTTP endpoints are fine (UI talks to backend).
- Sources: start with Europe PMC (working). Simple search only.
- Extraction: PDF-to-provider only (no local text extraction). Provider = OpenAI first (Mock available for demos).
- Results table must show both queued and previously processed papers together; status is the only separator (no explicit "queue/history" bucket).
- Concurrency: in-process queue with adjustable concurrency; default = 3.
- Live progress via SSE. Failures are per-paper, not fatal globally. No auto-retry; allow manual retry.
- Skip already-processed items by default; allow per-item force re-extract (creates a new Run).
- Store prompts, outputs, safe metadata; avoid storing chain-of-thought. "Continue chatting" per paper should open a new provider call with prior context and create a new Run.

Non-goals (for MVP)
- No advanced filters/query builder; no saved searches.
- No manual edit/review UI, versioning visualization, or full entity browser yet.
- No deduping beyond minimal DOI/URL match for badges (we still auto-skip processed).
- No exported datasets; no notifications; no auth; no scheduled jobs.
- No PDF caching beyond whatever already exists; no rate-limit automation.

MVP user journeys (v0.1)
1) Search and select
   - Enter query; see results (source, title, year, link).
   - Badges: "already seen" and "already processed" based on DOI/URL match.
   - Add/remove items to current batch. Already processed are auto-skipped (toggle force re-extract per item).
   - Provider select: OpenAI or Mock (shown on search page only; no separate Settings page in MVP).

2) Run and monitor (single unified table)
   - One results table shows all papers across sessions with a Status column:
     - Queued → Fetching → Provider → Validating → Stored → Failed (and Cancelled if needed).
   - Percent-done indicator based on items completed/total.
   - Live updates via SSE. No emojis; use subtle icons and colors.
   - Click a row to open a paper detail drawer with key metadata and actions:
     - View prompts and raw JSON result.
     - "Retry" (if Failed) or "Force re-extract" (always allowed).
     - "Continue chat" (follow-up instruction) → creates new Run with prior context.
     - "More details / Edit" button navigates to a full detail page (future work).

3) Paper detail page (future-oriented stub)
   - Eventually houses manual review, field editing, version history, and evidence.
   - MVP may route to a placeholder; core work focuses on the drawer and run pipeline.

Provider and extraction
- Target OpenAI Responses API first (PDF URL support). Keep Mock for demos.
- Do not implement local text extraction in MVP; surface failures clearly with reasons.
- Follow-up chat: new provider call with appended instruction and prior result context; store as new Run.

Statuses and failure handling
- Status lifecycle: Queued → Fetching → Provider → Validating → Stored or Failed (Cancelled optional).
- Failure handling: mark Failed immediately with reason (HTTP error, content-type issue, provider error, validation error). No auto-retry; allow manual retry.
- Minimal dedupe: DOI/URL string match to show badges. Auto-skip already processed by default; per-item override.

Data and persistence (MVP)
- Paper: minimal metadata (title, doi, url, source, year, authors if available).
- Run: paper_id, status, raw_json, prompt metadata, provider info, timestamps, failure_reason (nullable).
- "Latest run" is implied by max created_at; UI shows latest by default.
- Entities extraction and editing come later (separable phase).

Concurrency and queue
- In-process queue; default concurrency = 3; adjustable (UI control can be added later).
- No pre-run cost/time estimator in MVP.

Live updates and UX
- SSE stream for table updates and per-row status changes.
- Subtle icons + color coding for statuses (no emojis). Keep layout clean and information-dense but uncluttered.

OpenAI chat continuation
- Allow user to send an instruction on a finished paper to "continue chatting." The backend constructs a new request using prior prompt/result as context and records a new Run.

Open questions (to revisit later)
- Page vs drawer balance: MVP = drawer for quick inspection; later = full page for manual review and history.
- Evidence linking (spans/pages/tables) and provenance view.
- Unit normalization and vocab constraints in prompts vs post-processing.
- Real dedupe/canonicalization beyond DOI/URL (title/author/year fuzzy matches).
- Exports (CSV/JSON/Parquet) and downstream integrations.

Milestones
- v0.1 (this MVP): Search, selection, unified table with live progress, paper detail drawer, follow-up chat to create new runs, auto-skip processed with per-item override, OpenAI/Mock provider choice on search page, SSE updates, concurrency=3.
- v0.2: Full paper page (manual review/editing UI), basic version history view, simple exports (JSON), optional retries/backoff toggle, minimal QA hooks.
- v0.3: Entities browser/editor, advanced filters, real dedupe, caching, dashboards, cost/time estimator, optional notifications.

Checklists (to mark progress as we implement)

Frontend
- [x] Search page
  - [x] Query input, results list (Europe PMC)
  - [x] Badges: seen/processed
  - [x] Add/remove to batch
  - [x] Provider selector (OpenAI/Mock)
- [x] Unified results table
  - [x] Columns: Status, Source, Title, DOI/URL, Last Run At
  - [ ] Percent-done indicator
  - [x] Live updates via SSE
  - [x] Manual Retry / Force re-extract actions
  - [x] Detail drawer with prompts + raw JSON + actions
  - [ ] "More details / Edit" button (routes to placeholder page)
- [x] Minimal icons/colors for statuses (no emojis)

Backend
- [x] Search endpoint (simple Europe PMC; badge counts for seen/processed)
- [x] Batch enqueue endpoint (per paper; force override flag)
- [x] In-process queue with concurrency=3 (configurable)
- [x] Status machine: Queued → Fetching → Provider → Validating → Stored/Failed
- [x] SSE endpoint for live updates
- [x] Retry/Force re-extract endpoints
- [ ] Follow-up chat endpoint → creates new Run with prior context
- [x] Failure reasons surfaced consistently

Data
- [x] Paper model (title, doi, url, source, year, authors_json?)
- [x] Run model (paper_id, status, raw_json, prompts, provider, failure_reason, timestamps)
- [x] Minimal dedupe on DOI/URL for badges; auto-skip processed in enqueue path
- [x] Latest run resolution for table

LLM/Providers
- [x] OpenAI Responses API integration (PDF URL)
- [x] Mock provider
- [x] Prompt assembly including domain definitions (as needed), without chain-of-thought storage
- [ ] Follow-up chat: append instruction/context policy, stored as new Run

Quality and future hooks
- [ ] Validation step placeholder (expand later for QC)
- [x] Clear error taxonomy for failures
- [ ] Optional cancellation (Cancelled status) [later]

Out of scope (confirm later phases)
- [ ] Manual review/editor UI (full page)
- [ ] Version history visualization
- [ ] Entities extraction/editor
- [ ] Advanced search/filters, saved searches
- [ ] Exports, notifications, scheduling, caching, robust dedupe

Changelog
- 2026-01-11: Initial MVP plan captured from discussion and decisions.
- 2026-01-11: Part 1 completed (search, enqueue, SSE, queue, unified table).
- 2026-01-11: Part 2 completed (drawer with prompts/JSON, retry, force re-extract).
