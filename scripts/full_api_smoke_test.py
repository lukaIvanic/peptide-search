from __future__ import annotations

import argparse
import json
import time
from typing import Optional
from urllib.parse import quote

import httpx


def _request(client: httpx.Client, method: str, path: str, json_body: Optional[dict] = None) -> dict:
    url = client.base_url.join(path)
    resp = client.request(method, url, json=json_body)
    resp.raise_for_status()
    return resp.json()


def _sleep_brief() -> None:
    time.sleep(1.5)


def main() -> None:
    parser = argparse.ArgumentParser(description="Full API smoke test (mock provider).")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--provider", default="mock", choices=["mock"])
    parser.add_argument("--dataset", default="catalytic_non_prot")
    parser.add_argument("--query", default="self-assembling peptide hydrogel")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        health = _request(client, "GET", "/api/health")
        print("Health:", health)

        search = _request(client, "GET", f"/api/search?q={quote(args.query)}&rows=5")
        print("Search results:", len(search.get("results", [])))

        baseline_cases = _request(client, "GET", f"/api/baseline/cases?dataset={args.dataset}")
        cases = baseline_cases.get("cases", [])
        if not cases:
            raise RuntimeError("No baseline cases found for dataset.")
        case_id = cases[0]["id"]

        enqueue = _request(client, "POST", "/api/baseline/enqueue", {
            "provider": args.provider,
            "dataset": args.dataset,
            "force": False,
        })
        print("Baseline enqueue:", enqueue.get("enqueued"), "enqueued")
        _sleep_brief()

        latest = None
        run = {}
        deadline = time.time() + 300
        while time.time() < deadline:
            latest = _request(client, "GET", f"/api/baseline/cases/{case_id}/latest-run")
            run = latest.get("run", {})
            status = run.get("status")
            if status in {"stored", "failed"}:
                break
            _sleep_brief()

        run_id = run.get("id")
        if not run_id:
            raise RuntimeError("No run_id found for baseline case.")

        run_detail = _request(client, "GET", f"/api/runs/{run_id}")
        print("Run detail status:", run_detail.get("run", {}).get("status"))

        runs_list = _request(client, "GET", f"/api/runs?paper_id={run_detail['paper']['id']}")
        print("Runs list count:", len(runs_list.get("runs", [])))

        run_history = _request(client, "GET", f"/api/runs/{run_id}/history")
        print("Run history count:", len(run_history.get("history", [])))

        if run_detail.get("run", {}).get("status") == "stored":
            followup = _request(client, "POST", f"/api/runs/{run_id}/followup", {
                "instruction": "Confirm key peptide sequence only.",
                "provider": args.provider,
            })
            print("Followup run:", followup.get("extraction_id"))

            edit_payload = run_detail.get("run", {}).get("raw_json") or {}
            edit = _request(client, "POST", f"/api/runs/{run_id}/edit", {
                "payload": edit_payload,
                "reason": "Smoke test edit",
            })
            print("Edit run:", edit.get("extraction_id"))

        papers = _request(client, "GET", "/api/papers")
        print("Papers:", len(papers.get("papers", [])))

        paper_id = run_detail.get("paper", {}).get("id")
        if paper_id:
            _request(client, "GET", f"/api/papers/{paper_id}/extractions")

        if run_detail.get("run", {}).get("pdf_url"):
            _request(client, "POST", "/api/enqueue", {
                "provider": args.provider,
                "papers": [{
                    "title": run_detail.get("paper", {}).get("title") or "Smoke Test Paper",
                    "doi": run_detail.get("paper", {}).get("doi"),
                    "url": run_detail.get("paper", {}).get("url"),
                    "pdf_url": run_detail.get("run", {}).get("pdf_url"),
                    "source": run_detail.get("paper", {}).get("source"),
                    "year": run_detail.get("paper", {}).get("year"),
                    "authors": run_detail.get("paper", {}).get("authors") or [],
                    "force": False,
                }],
            })

        entities = _request(client, "GET", "/api/entities")
        print("Entities:", len(entities.get("items", [])))
        if entities.get("items"):
            entity_id = entities["items"][0]["id"]
            _request(client, "GET", f"/api/entities/{entity_id}")

        _request(client, "GET", "/api/entities/kpis")

        _request(client, "GET", "/api/quality-rules")
        _request(client, "POST", "/api/quality-rules", {"rules": {}})

        _request(client, "GET", "/api/runs/failure-summary")
        _request(client, "GET", "/api/runs/failures")
        _request(client, "POST", "/api/runs/failures/retry", {"days": 1, "limit": 5})

        prompts = _request(client, "GET", "/api/prompts")
        print("Prompts:", len(prompts.get("prompts", [])))

        create_prompt = _request(client, "POST", "/api/prompts", {
            "name": "Smoke Test Prompt",
            "description": "Created by full_api_smoke_test",
            "content": "Return JSON only.",
            "notes": "Smoke test",
            "activate": False,
        })
        prompt_id = create_prompt.get("prompt", {}).get("id")
        if prompt_id:
            _request(client, "POST", f"/api/prompts/{prompt_id}/versions", {
                "content": "Updated prompt content",
                "notes": "Smoke test update",
            })

        print("Full API smoke test complete.")


if __name__ == "__main__":
    main()
