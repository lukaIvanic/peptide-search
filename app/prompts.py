from __future__ import annotations

from pathlib import Path
from textwrap import dedent
from typing import Optional

from .config import settings


SCHEMA_SPEC = dedent(
	"""
	Produce a JSON object with the following structure (do not include any extra fields):

	{
	  "paper": {
	    "title": string|null,
	    "doi": string|null,
	    "url": string|null,
	    "source": string|null,
	    "year": number|null,
	    "authors": [string, ...]
	  },
	  "entities": [
	    {
	      "type": "peptide" | "molecule",
	      "peptide": {
	        "sequence_one_letter": string|null,
	        "sequence_three_letter": string|null,
	        "n_terminal_mod": string|null,
	        "c_terminal_mod": string|null,
	        "is_hydrogel": boolean|null
	      } | null,
	      "molecule": {
	        "chemical_formula": string|null,
	        "smiles": string|null,
	        "inchi": string|null
	      } | null,
	      "labels": [string, ...],
	      "morphology": [string, ...],
	      "conditions": {
	        "ph": number|null,
	        "concentration": number|null,
	        "concentration_units": string|null,
	        "temperature_c": number|null
	      } | null,
	      "thresholds": {
	        "cac": number|null,
	        "cgc": number|null,
	        "mgc": number|null
	      } | null,
	      "validation_methods": [string, ...],
	      "process_protocol": string|null,
	      "reported_characteristics": [string, ...],
	      "evidence": {
	        "field.path": [
	          {
	            "quote": string,
	            "section": string|null,
	            "page": number|null
	          },
	          ...
	        ],
	        ...
	      } | null
	    },
	    ...
	  ],
	  "comment": string|null
	}

	Conventions:
	- Peptide sequences must be written from N-terminus to C-terminus.
	- If N-terminus is modified, use 'Ac-' to denote acetylation; if free, assume -NH2.
	- If C-terminus is modified, use '-NH2' to denote amidation; if free, assume -COOH / -OH.
	- Morphology terms should be from common supramolecular forms (e.g., micelle, vesicle, fibril, nanofiber, nanotube, nanosheet, nanoribbon, nanosphere, amyloid-like).
	- Validation methods: use standard abbreviations (CD, TEM, FTIR, ATR, XRD, AFM, SEM, DLS, SLS, MD, AA-MD, CG-MD).
	- If data is not reported, put null, not a guess.
	- The "comment" field is for a brief (1 sentence) explanation: what was extracted, or why entities is empty (e.g., "Review article without specific sequences", "Paper discusses applications but no new peptides synthesized", "Extracted 3 peptide sequences with full experimental conditions").
	- Include an "evidence" map for any non-null fields you extracted, using field paths like "peptide.sequence_one_letter", "conditions.concentration", "validation_methods".
	"""
).strip()


def read_definitions_text(path: Optional[Path] = None) -> str:
	file_path = path or settings.DEFINITIONS_PATH
	try:
		text = file_path.read_text(encoding="utf-8")
		return text.strip()
	except Exception:
		return ""


def build_system_prompt(override_text: Optional[str] = None) -> str:
	if override_text:
		return override_text.strip()

	defs = read_definitions_text() if settings.INCLUDE_DEFINITIONS else ""
	intro = dedent(
		"""
		You are an expert scientific literature analyst focused on peptides and lab-synthesized molecules.
		Extract structured data precisely and return STRICT JSON ONLY. No markdown, no commentary.
		If an item is not reported, return null for that field.
		"""
	).strip()

	if defs:
		return f"{intro}\n\nDomain definitions and conventions:\n{defs}\n"
	return intro


def build_user_prompt(paper_meta_hint: str, paper_text: str) -> str:
	return dedent(
		f"""
		Task:
		- Read the following scientific text (may include abstract, methods, or full text).
		- Identify peptides and/or molecules reported.
		- Extract sequences, terminal modifications, conditions (pH, concentration, temperature), morphology, hydrogel formation,
		  validation methods, thresholds (CAC/CGC/MGC), process/protocol, and reported characteristics.
		- When possible, extract molecular identifiers (chemical formula, SMILES, InChI) for non-peptide molecules.
		- Provide evidence snippets for each extracted field using the "evidence" map in the schema.

		Important:
		- Follow the SCHEMA precisely.
		- Output strictly valid JSON. Do not include code fences.
		- Do not invent data; use null where not specified.

		Schema:
		{SCHEMA_SPEC}

		Paper metadata (hints from user/system; may be partial):
		{paper_meta_hint}

		Text to analyze:
		{paper_text}
		"""
	).strip()


def build_followup_prompt(prior_json: str, instruction: str, pdf_url: Optional[str] = None) -> str:
	pdf_line = f"PDF URL (context only, do not fetch): {pdf_url}" if pdf_url else "PDF URL: null"
	return dedent(
		f"""
		Task:
		- You previously extracted JSON for this paper. Review it and apply the user instruction below.
		- Return a FULL JSON payload that matches the schema (not a diff).
		- Keep existing correct fields unless the instruction explicitly changes them.
		- Provide evidence snippets for each extracted field using the "evidence" map.

		User instruction:
		{instruction}

		Prior extraction JSON:
		{prior_json}

		{pdf_line}

		Schema:
		{SCHEMA_SPEC}
		"""
	).strip()


