from __future__ import annotations

from datetime import datetime
from typing import Optional

from sqlmodel import SQLModel, Field


class Paper(SQLModel, table=True):
	id: Optional[int] = Field(default=None, primary_key=True)
	title: str = Field(index=True)
	doi: Optional[str] = Field(default=None, index=True)
	url: Optional[str] = Field(default=None)
	source: Optional[str] = Field(default=None, index=True)  # crossref, pubmed, arxiv, manual
	year: Optional[int] = Field(default=None, index=True)
	authors_json: Optional[str] = Field(default=None)  # JSON-encoded list of authors
	created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


class Extraction(SQLModel, table=True):
	id: Optional[int] = Field(default=None, primary_key=True)
	paper_id: Optional[int] = Field(default=None, index=True, foreign_key="paper.id")

	# High-signal fields for quick filtering
	entity_type: Optional[str] = Field(default=None, index=True)  # peptide | molecule
	peptide_sequence_one_letter: Optional[str] = Field(default=None, index=True)
	peptide_sequence_three_letter: Optional[str] = Field(default=None)
	n_terminal_mod: Optional[str] = Field(default=None, index=True)
	c_terminal_mod: Optional[str] = Field(default=None, index=True)
	chemical_formula: Optional[str] = Field(default=None, index=True)
	smiles: Optional[str] = Field(default=None)
	inchi: Optional[str] = Field(default=None)
	labels: Optional[str] = Field(default=None)  # JSON list of labels
	morphology: Optional[str] = Field(default=None)  # JSON list of morphologies

	# Conditions & thresholds
	ph: Optional[float] = Field(default=None, index=True)
	concentration: Optional[float] = Field(default=None)
	concentration_units: Optional[str] = Field(default=None)
	temperature_c: Optional[float] = Field(default=None)
	is_hydrogel: Optional[bool] = Field(default=None, index=True)
	cac: Optional[float] = Field(default=None)
	cgc: Optional[float] = Field(default=None)
	mgc: Optional[float] = Field(default=None)

	# Methods and protocol
	validation_methods: Optional[str] = Field(default=None)  # JSON list of methods
	process_protocol: Optional[str] = Field(default=None)
	reported_characteristics: Optional[str] = Field(default=None)  # JSON list

	# Raw model output for traceability
	raw_json: Optional[str] = Field(default=None)
	model_name: Optional[str] = Field(default=None)
	model_provider: Optional[str] = Field(default=None)

	created_at: datetime = Field(default_factory=datetime.utcnow, nullable=False)


