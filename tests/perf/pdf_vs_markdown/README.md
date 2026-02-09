## PDF vs Markdown Benchmarks

Standalone scripts to compare latency for PDF input vs markdown/text input.

### Prerequisites
- Set `OPENAI_API_KEY` in your environment.
- Set `LLM_PROVIDER=openai-nano` (required by app config).

### PDF benchmark
1) Edit `PDF_PATH` in `pdf_request.py`.
2) Run:
```
python tests/perf/pdf_vs_markdown/pdf_request.py
```

### Markdown benchmark
1) Paste your extracted markdown into `MARKDOWN_TEXT` in `markdown_request.py`.
2) Run:
```
python tests/perf/pdf_vs_markdown/markdown_request.py
```

Both scripts print start/end timestamps, elapsed seconds, and response length.

### Health check
Runs a minimal JSON response to confirm the API key + model work.
```
python tests/perf/pdf_vs_markdown/health_check.py
```
