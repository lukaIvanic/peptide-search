import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from sqlmodel import Session, SQLModel, create_engine, select

from app.persistence.models import QualityRuleConfig
from app.services.quality_service import (
    DEFAULT_RULES,
    compute_entity_quality,
    ensure_quality_rules,
    extract_entity_payload,
)


class QualityServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "quality_rules.db"
        self.engine = create_engine(f"sqlite:///{db_path}", echo=False)
        SQLModel.metadata.create_all(self.engine)
        self.session = Session(self.engine)

    def tearDown(self) -> None:
        self.session.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def test_ensure_quality_rules_creates_default_record(self) -> None:
        rules = ensure_quality_rules(self.session)
        self.assertEqual(rules, DEFAULT_RULES)
        row = self.session.exec(select(QualityRuleConfig)).first()
        self.assertIsNotNone(row)
        self.assertEqual(json.loads(row.rules_json), DEFAULT_RULES)

    def test_ensure_quality_rules_repairs_invalid_json(self) -> None:
        self.session.add(QualityRuleConfig(rules_json="{invalid-json"))
        self.session.commit()

        rules = ensure_quality_rules(self.session)
        self.assertEqual(rules, DEFAULT_RULES)
        row = self.session.exec(select(QualityRuleConfig)).first()
        self.assertEqual(json.loads(row.rules_json), DEFAULT_RULES)

    def test_compute_entity_quality_sets_expected_flags(self) -> None:
        entity_row = SimpleNamespace(
            ph=20,
            temperature_c=250,
            concentration=-1,
            peptide_sequence_one_letter="AXZ",
            peptide_sequence_three_letter=None,
            n_terminal_mod=None,
            c_terminal_mod=None,
            is_hydrogel=None,
            chemical_formula="H2O",
            smiles=None,
            inchi=None,
        )
        payload = {
            "peptide": {"sequence_one_letter": "AXZ"},
            "conditions": {"ph": 20},
            "evidence": {},
        }
        result = compute_entity_quality(entity_row, payload, DEFAULT_RULES)

        self.assertIn("missing_evidence", result["flags"])
        self.assertIn("invalid_ph", result["flags"])
        self.assertIn("invalid_temperature", result["flags"])
        self.assertIn("invalid_concentration", result["flags"])
        self.assertIn("invalid_sequence_chars", result["flags"])
        self.assertIn("peptide_and_molecule_set", result["flags"])

    def test_extract_entity_payload_bounds_checks(self) -> None:
        payload = {"entities": [{"id": 1}, {"id": 2}]}
        self.assertEqual(extract_entity_payload(payload, 0), {"id": 1})
        self.assertEqual(extract_entity_payload(payload, 10), {})
        self.assertEqual(extract_entity_payload(payload, None), {})
        self.assertEqual(extract_entity_payload({"entities": "bad"}, 0), {})


if __name__ == "__main__":
    unittest.main()
