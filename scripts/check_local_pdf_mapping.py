#!/usr/bin/env python3
"""Report local PDF mapping coverage for deployment visibility.

Non-zero exit is only used for malformed mapping JSON. Missing files are warnings.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check mapped local PDF files that exist on disk.")
    parser.add_argument(
        "--mapping",
        default="app/baseline/data/local_pdfs.json",
        help="Path to local_pdfs.json (default: app/baseline/data/local_pdfs.json)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=15,
        help="Max number of missing-file examples to print",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    mapping_path = (repo_root / args.mapping).resolve()

    if not mapping_path.exists():
        print(f"[local-pdf-check] Mapping file not found: {mapping_path}")
        return 0

    try:
        payload = json.loads(mapping_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[local-pdf-check] Failed to parse JSON: {mapping_path}: {exc}")
        return 2

    total_paths = 0
    present = 0
    missing = []

    for doi, entry in payload.items():
        if not isinstance(entry, dict):
            continue
        for key in ("main", "supplementary"):
            paths = entry.get(key) or []
            if not isinstance(paths, list):
                continue
            for raw in paths:
                total_paths += 1
                candidate = Path(str(raw))
                full_path = candidate if candidate.is_absolute() else (repo_root / candidate)
                if full_path.exists():
                    present += 1
                else:
                    missing.append((doi, key, str(candidate)))

    print(f"[local-pdf-check] mapping={mapping_path}")
    print(f"[local-pdf-check] total_paths={total_paths} present={present} missing={len(missing)}")

    if missing:
        print("[local-pdf-check] Missing examples:")
        for doi, key, path in missing[: max(0, args.limit)]:
            print(f"  - doi={doi} kind={key} path={path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
