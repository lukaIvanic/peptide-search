from __future__ import annotations

import json
from typing import Any, Dict, List

from sqlmodel import Session, select

from ..persistence.models import ExtractionEntity, QualityRuleConfig
from ..time_utils import utc_now


DEFAULT_RULES: Dict[str, Any] = {
    "rules": {
        "ph_range": {"min": 0, "max": 14, "enabled": True},
        "temperature_c": {"min": -50, "max": 150, "enabled": True},
        "concentration_nonnegative": {"enabled": True},
        "missing_evidence_for_non_null": {"enabled": True},
        "sequence_valid_chars": {"enabled": True, "allowed": "ACDEFGHIKLMNPQRSTVWY"},
        "evidence_quote_required": {"enabled": True},
        "both_peptide_and_molecule": {"enabled": True},
    }
}


def _parse_rules_json(raw: str | None) -> tuple[Dict[str, Any], bool]:
    if not raw:
        return DEFAULT_RULES, False
    try:
        parsed = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return DEFAULT_RULES, False
    if not isinstance(parsed, dict):
        return DEFAULT_RULES, False
    return parsed, True


def get_quality_rules(session: Session) -> Dict[str, Any]:
    row = session.exec(select(QualityRuleConfig)).first()
    parsed, _is_valid = _parse_rules_json(row.rules_json if row else None)
    return parsed


def ensure_quality_rules(session: Session) -> Dict[str, Any]:
    row = session.exec(select(QualityRuleConfig)).first()
    if row:
        parsed, is_valid = _parse_rules_json(row.rules_json)
        if is_valid:
            return parsed
        row.rules_json = json.dumps(DEFAULT_RULES)
        row.updated_at = utc_now()
        session.add(row)
        session.commit()
        return DEFAULT_RULES

    row = QualityRuleConfig(rules_json=json.dumps(DEFAULT_RULES), updated_at=utc_now())
    session.add(row)
    session.commit()
    return DEFAULT_RULES


def update_quality_rules(session: Session, rules: Dict[str, Any]) -> Dict[str, Any]:
    row = session.exec(select(QualityRuleConfig)).first()
    if not row:
        row = QualityRuleConfig(rules_json=json.dumps(rules), updated_at=utc_now())
        session.add(row)
    else:
        row.rules_json = json.dumps(rules)
        row.updated_at = utc_now()
    session.commit()
    return rules


def compute_entity_quality(
    entity_row: ExtractionEntity,
    entity_payload: Dict[str, Any],
    rules: Dict[str, Any],
) -> Dict[str, Any]:
    flags: List[str] = []
    rule_set = rules.get("rules", {})

    missing_fields: List[str] = []
    evidence_coverage = 0

    fields = list_non_null_fields(entity_payload)
    evidence_fields = entity_payload.get("evidence") or {}
    if fields:
        missing_fields = [
            field for field in fields if not has_evidence_for_field(evidence_fields, field)
        ]
        evidence_coverage = int(round((len(fields) - len(missing_fields)) / len(fields) * 100))

    if rule_set.get("missing_evidence_for_non_null", {}).get("enabled") and missing_fields:
        flags.append("missing_evidence")

    if rule_set.get("evidence_quote_required", {}).get("enabled") and has_empty_evidence_quote(
        evidence_fields
    ):
        flags.append("evidence_missing_quote")

    if (
        rule_set.get("both_peptide_and_molecule", {}).get("enabled")
        and has_peptide_data(entity_row)
        and has_molecule_data(entity_row)
    ):
        flags.append("peptide_and_molecule_set")

    ph_rule = rule_set.get("ph_range", {})
    if ph_rule.get("enabled") and entity_row.ph is not None:
        if entity_row.ph < ph_rule.get("min", 0) or entity_row.ph > ph_rule.get("max", 14):
            flags.append("invalid_ph")

    temp_rule = rule_set.get("temperature_c", {})
    if temp_rule.get("enabled") and entity_row.temperature_c is not None:
        if entity_row.temperature_c < temp_rule.get("min", -50) or entity_row.temperature_c > temp_rule.get(
            "max", 150
        ):
            flags.append("invalid_temperature")

    if (
        rule_set.get("concentration_nonnegative", {}).get("enabled")
        and entity_row.concentration is not None
        and entity_row.concentration < 0
    ):
        flags.append("invalid_concentration")

    seq_rule = rule_set.get("sequence_valid_chars", {})
    if seq_rule.get("enabled") and entity_row.peptide_sequence_one_letter:
        allowed = set(seq_rule.get("allowed", ""))
        seq = entity_row.peptide_sequence_one_letter.upper()
        if any(char not in allowed for char in seq):
            flags.append("invalid_sequence_chars")

    return {
        "flags": flags,
        "evidence_coverage": evidence_coverage,
        "missing_evidence_fields": missing_fields,
    }


def list_non_null_fields(entity_payload: Dict[str, Any]) -> List[str]:
    fields: List[str] = []

    peptide = entity_payload.get("peptide") or {}
    for key in [
        "sequence_one_letter",
        "sequence_three_letter",
        "n_terminal_mod",
        "c_terminal_mod",
        "is_hydrogel",
    ]:
        if peptide.get(key) is not None and peptide.get(key) != "":
            fields.append(f"peptide.{key}")

    molecule = entity_payload.get("molecule") or {}
    for key in ["chemical_formula", "smiles", "inchi"]:
        if molecule.get(key):
            fields.append(f"molecule.{key}")

    for key in ["labels", "morphology", "validation_methods", "reported_characteristics"]:
        values = entity_payload.get(key)
        if isinstance(values, list) and values:
            fields.append(key)

    conditions = entity_payload.get("conditions") or {}
    for key in ["ph", "concentration", "concentration_units", "temperature_c"]:
        if conditions.get(key) is not None and conditions.get(key) != "":
            fields.append(f"conditions.{key}")

    thresholds = entity_payload.get("thresholds") or {}
    for key in ["cac", "cgc", "mgc"]:
        if thresholds.get(key) is not None and thresholds.get(key) != "":
            fields.append(f"thresholds.{key}")

    if entity_payload.get("process_protocol"):
        fields.append("process_protocol")

    return fields


def has_evidence_for_field(evidence_fields: Dict[str, Any], field: str) -> bool:
    items = evidence_fields.get(field)
    if not isinstance(items, list):
        return False
    return any(isinstance(item, dict) and item.get("quote") for item in items)


def has_empty_evidence_quote(evidence_fields: Dict[str, Any]) -> bool:
    for items in evidence_fields.values():
        if not isinstance(items, list):
            continue
        for item in items:
            if isinstance(item, dict) and not item.get("quote"):
                return True
    return False


def has_peptide_data(entity_row: ExtractionEntity) -> bool:
    return any(
        [
            entity_row.peptide_sequence_one_letter,
            entity_row.peptide_sequence_three_letter,
            entity_row.n_terminal_mod,
            entity_row.c_terminal_mod,
            entity_row.is_hydrogel is not None,
        ]
    )


def has_molecule_data(entity_row: ExtractionEntity) -> bool:
    return any([entity_row.chemical_formula, entity_row.smiles, entity_row.inchi])


def extract_entity_payload(run_payload: Dict[str, Any], entity_index: int | None) -> Dict[str, Any]:
    if entity_index is None:
        return {}
    entities = run_payload.get("entities")
    if not isinstance(entities, list):
        return {}
    if entity_index < 0 or entity_index >= len(entities):
        return {}
    entity_payload = entities[entity_index]
    return entity_payload if isinstance(entity_payload, dict) else {}
