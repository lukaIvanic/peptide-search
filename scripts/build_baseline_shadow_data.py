from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional


ROOT = Path(__file__).resolve().parents[1]
BASELINE_DIR = ROOT / "app" / "baseline" / "data"
SHADOW_DIR = ROOT / "app" / "baseline" / "data_shadow"
SHADOW_DIR.mkdir(parents=True, exist_ok=True)

SHADOW_SCHEMA_VERSION = "v1-shadow"


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")


def _mutate_sequence(seq: Optional[str]) -> str:
    if not seq:
        return "X"
    cleaned = str(seq).replace(" ", "")
    if len(cleaned) == 1:
        return "X" if cleaned != "X" else "A"
    last = cleaned[-1]
    replacement = "A" if last != "A" else "G"
    return cleaned[:-1] + replacement


def _mutation_type(case_id: str) -> str:
    bucket = int(hashlib.sha256(case_id.encode("utf-8")).hexdigest(), 16) % 100
    if bucket < 70:
        return "match"
    if bucket < 80:
        return "seq_mismatch"
    if bucket < 85:
        return "label_mismatch"
    if bucket < 90:
        return "terminal_mismatch"
    if bucket < 94:
        return "empty_entities"
    if bucket < 97:
        return "extra_entity"
    return "molecule_entity"


def _build_peptide_entity(case: Dict[str, Any], seq: Optional[str], labels: List[str]) -> Dict[str, Any]:
    return {
        "type": "peptide",
        "peptide": {
            "sequence_one_letter": seq,
            "sequence_three_letter": None,
            "n_terminal_mod": case.get("n_terminal"),
            "c_terminal_mod": case.get("c_terminal"),
            "is_hydrogel": None,
        },
        "molecule": None,
        "labels": labels,
        "morphology": [],
        "conditions": None,
        "thresholds": None,
        "validation_methods": [],
        "process_protocol": None,
        "reported_characteristics": [],
        "evidence": None,
    }


def _build_molecule_entity() -> Dict[str, Any]:
    return {
        "type": "molecule",
        "peptide": None,
        "molecule": {
            "chemical_formula": "C2H5NO2",
            "smiles": "CC(=O)N",
            "inchi": None,
        },
        "labels": ["molecule"],
        "morphology": [],
        "conditions": None,
        "thresholds": None,
        "validation_methods": [],
        "process_protocol": None,
        "reported_characteristics": [],
        "evidence": None,
    }


def _build_payload(case: Dict[str, Any]) -> Dict[str, Any]:
    mutation = _mutation_type(case["id"])
    sequence = case.get("sequence")
    labels = list(case.get("labels") or [])

    entities: List[Dict[str, Any]] = []
    if mutation == "empty_entities":
        entities = []
    elif mutation == "molecule_entity":
        entities = [_build_molecule_entity()]
    else:
        seq_value = sequence
        if mutation == "seq_mismatch":
            seq_value = _mutate_sequence(sequence)
        if mutation == "label_mismatch":
            labels = ["mismatch-label"] if labels else ["unexpected-label"]
        entity = _build_peptide_entity(case, seq_value, labels)
        if mutation == "terminal_mismatch":
            entity["peptide"]["n_terminal_mod"] = case.get("c_terminal")
            entity["peptide"]["c_terminal_mod"] = case.get("n_terminal")
        entities = [entity]

        if mutation == "extra_entity":
            extra_entity = _build_peptide_entity(case, _mutate_sequence(sequence), ["extra-entity"])
            entities.append(extra_entity)

    payload = {
        "paper": {
            "title": f"Shadow baseline {case['id']}",
            "doi": case.get("doi"),
            "url": case.get("paper_url") or case.get("pdf_url"),
            "source": "shadow",
            "year": None,
            "authors": [],
        },
        "entities": entities,
        "comment": f"Shadow benchmark payload ({mutation}).",
    }
    return {"payload": payload, "mutation": mutation}


def main() -> None:
    index_path = BASELINE_DIR / "index.json"
    if not index_path.exists():
        raise FileNotFoundError("Baseline index.json not found; run build_baseline_data.py first.")

    index = _read_json(index_path)
    cases: List[Dict[str, Any]] = []
    for dataset in index.get("datasets", []):
        dataset_path = BASELINE_DIR / dataset["file"]
        cases.extend(_read_json(dataset_path))

    mutation_counts: Dict[str, int] = {}
    shadow_entries: List[Dict[str, Any]] = []
    for case in cases:
        payload_info = _build_payload(case)
        mutation = payload_info["mutation"]
        mutation_counts[mutation] = mutation_counts.get(mutation, 0) + 1
        shadow_entries.append({
            "case_id": case["id"],
            "dataset": case["dataset"],
            "mutation": mutation,
            "payload": payload_info["payload"],
        })

    shadow_index = {
        "schema_version": SHADOW_SCHEMA_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_total_cases": len(cases),
        "mutation_counts": mutation_counts,
        "file": "shadow_extractions.json",
    }

    _write_json(SHADOW_DIR / "index.json", shadow_index)
    _write_json(SHADOW_DIR / "shadow_extractions.json", shadow_entries)
    print(f"Shadow dataset written to {SHADOW_DIR} ({len(shadow_entries)} cases)")


if __name__ == "__main__":
    main()
