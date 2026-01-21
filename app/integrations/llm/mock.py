"""Mock LLM provider for demos (no API key needed)."""
from __future__ import annotations

import json
from typing import Optional

from .base import DocumentInput, LLMCapabilities, LLMProvider


class MockProvider:
    """Mock provider that returns deterministic demo data."""

    def name(self) -> str:
        return "mock"
    
    def model_name(self) -> str:
        return "mock-demo"

    def capabilities(self) -> LLMCapabilities:
        return LLMCapabilities(
            supports_pdf_url=True,  # Pretend to support for demo purposes
            supports_pdf_file=True,
            supports_json_mode=True,
        )

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        document: Optional[DocumentInput] = None,
        temperature: float = 0.2,
        max_tokens: int = 2000,
    ) -> str:
        """Return a deterministic demo response."""
        example = {
            "paper": {
                "title": "Self-assembling peptide hydrogel for drug delivery",
                "doi": "10.1234/example.doi",
                "url": "https://example.org/paper.pdf",
                "source": "demo",
                "year": 2024,
                "authors": ["Doe, J.", "Smith, A."],
            },
            "entities": [
                {
                    "type": "peptide",
                    "peptide": {
                        "sequence_one_letter": "FTRK",
                        "sequence_three_letter": "Phe-Thr-Arg-Lys",
                        "n_terminal_mod": "Ac-",
                        "c_terminal_mod": "-NH2",
                        "is_hydrogel": True,
                    },
                    "labels": ["self-assembly", "hydrogel"],
                    "morphology": ["nanofiber", "hydrogel network"],
                    "conditions": {
                        "ph": 7.4,
                        "concentration": 2.5,
                        "concentration_units": "mg/mL",
                        "temperature_c": 25.0,
                    },
                    "thresholds": {"cac": 0.15, "cgc": 1.0, "mgc": None},
                    "validation_methods": ["CD", "TEM", "FTIR", "DLS"],
                    "process_protocol": "Dissolve peptide in PBS (pH 7.4), heat to 50C for 10 min, cool to room temperature; gelation observed within 5 minutes.",
                    "reported_characteristics": ["viscoelastic", "transparent hydrogel", "shear-thinning"],
                    "molecule": None,
                }
            ],
            "comment": "Demo extraction with a single self-assembling peptide hydrogel example.",
        }
        return json.dumps(example, ensure_ascii=False, indent=2)
