from __future__ import annotations

import argparse
import json
from pathlib import Path

from sqlmodel import select

from app.db import session_scope
from app.persistence.models import ExtractionRun, RunStatus
from app.persistence.repository import PaperRepository, ExtractionRepository
from app.schemas import ExtractionPayload


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SHADOW_PATH = ROOT / "app" / "baseline" / "data_shadow" / "shadow_extractions.json"


def load_shadow_entries(path: Path) -> list[dict]:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed shadow baseline runs into the DB.")
    parser.add_argument("--shadow-path", default=str(DEFAULT_SHADOW_PATH))
    parser.add_argument("--dataset", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()

    shadow_path = Path(args.shadow_path)
    if not shadow_path.exists():
        raise FileNotFoundError(f"Shadow dataset not found: {shadow_path}")

    entries = load_shadow_entries(shadow_path)
    if args.dataset:
        entries = [entry for entry in entries if entry.get("dataset") == args.dataset]

    seeded = 0
    skipped = 0

    with session_scope() as session:
        paper_repo = PaperRepository(session)
        extraction_repo = ExtractionRepository(session)

        for entry in entries:
            if args.limit is not None and seeded >= args.limit:
                break
            case_id = entry.get("case_id")
            dataset = entry.get("dataset")
            if not case_id:
                continue

            if not args.force:
                stmt = (
                    select(ExtractionRun)
                    .where(ExtractionRun.baseline_case_id == case_id)
                    .limit(1)
                )
                existing = session.exec(stmt).first()
                if existing:
                    skipped += 1
                    continue

            payload = ExtractionPayload.model_validate(entry.get("payload", {}))
            paper_id = paper_repo.upsert(payload.paper)
            extraction_repo.save_extraction(
                payload=payload,
                paper_id=paper_id,
                provider_name="shadow",
                model_name="shadow-data",
                status=RunStatus.STORED.value,
                baseline_case_id=case_id,
                baseline_dataset=dataset,
            )
            seeded += 1

    print(f"Seeded {seeded} shadow runs (skipped {skipped}).")


if __name__ == "__main__":
    main()
