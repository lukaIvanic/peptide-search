from __future__ import annotations

import argparse
import json
import time
from collections import Counter
from typing import Dict, List, Optional

import httpx


def _request(client: httpx.Client, method: str, path: str, json_body: Optional[dict] = None) -> dict:
    url = client.base_url.join(path)
    resp = client.request(method, url, json=json_body)
    resp.raise_for_status()
    return resp.json()


def _poll_cases(
    client: httpx.Client,
    dataset: str,
    timeout_s: int,
    poll_interval_s: float,
) -> List[dict]:
    started = time.time()
    while True:
        payload = _request(client, "GET", f"/api/baseline/cases?dataset={dataset}")
        cases = payload.get("cases", [])
        statuses = [c.get("latest_run", {}).get("status") for c in cases if c.get("latest_run")]
        if statuses and all(status in {"stored", "failed"} for status in statuses):
            return cases
        if time.time() - started > timeout_s:
            return cases
        time.sleep(poll_interval_s)


def main() -> None:
    parser = argparse.ArgumentParser(description="Baseline benchmark smoke test.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--provider", default="mock", choices=["mock", "openai"])
    parser.add_argument("--dataset", default="catalytic_non_prot")
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--interval", type=float, default=5.0)
    parser.add_argument("--seed-shadow", action="store_true")
    parser.add_argument("--shadow-limit", type=int, default=20)
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=60.0) as client:
        print(f"Fetching baseline cases for dataset={args.dataset}")
        cases_payload = _request(client, "GET", f"/api/baseline/cases?dataset={args.dataset}")
        cases = cases_payload.get("cases", [])
        if not cases:
            raise RuntimeError("No baseline cases found for dataset.")

        if args.seed_shadow:
            print("Seeding shadow runs (development only).")
            _request(client, "POST", "/api/baseline/shadow-seed", {
                "dataset": args.dataset,
                "limit": args.shadow_limit,
                "force": False,
            })

        print(f"Enqueuing baseline runs (provider={args.provider})")
        enqueue_resp = _request(client, "POST", "/api/baseline/enqueue", {
            "provider": args.provider,
            "dataset": args.dataset,
            "force": False,
        })
        print(json.dumps({
            "total": enqueue_resp.get("total"),
            "enqueued": enqueue_resp.get("enqueued"),
            "skipped": enqueue_resp.get("skipped"),
        }, indent=2))

        print("Polling for completion...")
        cases = _poll_cases(client, args.dataset, args.timeout, args.interval)
        status_counts = Counter(
            (case.get("latest_run", {}).get("status") or "none")
            for case in cases
        )
        print("Status counts:", dict(status_counts))

        sample = next((case for case in cases if case.get("latest_run")), None)
        if not sample:
            raise RuntimeError("No cases with latest runs found.")

        case_id = sample["id"]
        print(f"Fetching latest run for case: {case_id}")
        run_payload = _request(client, "GET", f"/api/baseline/cases/{case_id}/latest-run")
        run = run_payload.get("run", {})
        raw_json = run.get("raw_json")
        if run.get("status") == "stored":
            if not isinstance(raw_json, dict):
                raise RuntimeError("Stored run has invalid raw_json.")
        print("Smoke test complete.")


if __name__ == "__main__":
    main()
