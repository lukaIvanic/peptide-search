#!/usr/bin/env python3
"""
Create a local PDF mapping by extracting DOIs from PDFs and matching to baseline cases.
"""

import json
import re
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("Install PyMuPDF: pip install pymupdf")
    exit(1)

# Paths
WORKSPACE = Path(__file__).resolve().parent.parent
DOWNLOADED_PAPERS = WORKSPACE / "Peptide LLM" / "Datasets" / "downloaded_papers"
BASELINE_DATA = WORKSPACE / "app" / "baseline" / "data" / "self_assembly.json"
OUTPUT_FILE = WORKSPACE / "app" / "baseline" / "data" / "local_pdfs.json"

# DOI regex
DOI_PATTERN = re.compile(r'10\.\d{4,}/[^\s\]>\)"\']+', re.IGNORECASE)


def normalize_doi(doi):
    """Normalize DOI for comparison."""
    if not doi:
        return None
    doi = doi.strip().lower()
    # Remove trailing punctuation
    doi = re.sub(r'[.,;:\]>\)]+$', '', doi)
    # Remove PDF suffix
    doi = re.sub(r'\.pdf$', '', doi, flags=re.IGNORECASE)
    # Remove DCSupplemental suffix
    doi = re.sub(r'/-/dcsupplemental.*$', '', doi, flags=re.IGNORECASE)
    return doi


def extract_doi_from_pdf(pdf_path):
    """Extract DOI from PDF."""
    try:
        doc = fitz.open(pdf_path)
        
        # Check metadata
        metadata = doc.metadata or {}
        for key in ['doi', 'subject', 'keywords', 'title']:
            value = metadata.get(key, '')
            if value:
                match = DOI_PATTERN.search(value)
                if match:
                    doc.close()
                    return normalize_doi(match.group())
        
        # Search first 3 pages
        for page_num in range(min(3, len(doc))):
            text = doc[page_num].get_text()
            matches = DOI_PATTERN.findall(text)
            for doi in matches:
                normalized = normalize_doi(doi)
                if normalized and len(normalized) > 10:
                    doc.close()
                    return normalized
        
        doc.close()
    except Exception as e:
        pass
    return None


def load_baseline_cases():
    """Load baseline cases and build DOI lookup."""
    with open(BASELINE_DATA, "r", encoding="utf-8") as f:
        cases = json.load(f)
    
    # Build DOI -> cases mapping
    doi_to_cases = {}
    for case in cases:
        doi = normalize_doi(case.get("doi"))
        if doi:
            doi_to_cases.setdefault(doi, []).append(case)
    
    return cases, doi_to_cases


def main():
    print("Loading baseline cases...")
    cases, doi_to_cases = load_baseline_cases()
    print(f"  {len(cases)} cases, {len(doi_to_cases)} unique DOIs")
    
    print("\nScanning PDFs...")
    pdf_files = list(DOWNLOADED_PAPERS.rglob("*.pdf"))
    print(f"  {len(pdf_files)} PDF files found")
    
    # Extract DOIs and build mapping
    mapping = {}  # DOI -> {main: [], supplementary: []}
    matched_dois = set()
    unmatched_pdfs = []
    
    for pdf_path in sorted(pdf_files):
        filename = pdf_path.name
        rel_path = str(pdf_path.relative_to(WORKSPACE))
        is_si = "_SI" in filename.upper() or "_si" in filename
        
        doi = extract_doi_from_pdf(pdf_path)
        
        if doi and doi in doi_to_cases:
            matched_dois.add(doi)
            if doi not in mapping:
                mapping[doi] = {"main": [], "supplementary": []}
            
            key = "supplementary" if is_si else "main"
            if rel_path not in mapping[doi][key]:
                mapping[doi][key].append(rel_path)
                print(f"  [OK] {filename:<30} -> {doi[:40]}")
        else:
            unmatched_pdfs.append((filename, doi))
            print(f"  [--] {filename:<30} {'(DOI: ' + doi[:30] + ')' if doi else '(no DOI)'}")
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    print(f"PDFs matched to baseline: {sum(len(v['main']) + len(v['supplementary']) for v in mapping.values())}")
    print(f"Unique DOIs matched: {len(matched_dois)}")
    print(f"Unmatched PDFs: {len(unmatched_pdfs)}")
    
    # Show matched DOIs with case counts
    print(f"\nMatched DOIs ({len(mapping)}):")
    for doi, paths in sorted(mapping.items()):
        case_count = len(doi_to_cases.get(doi, []))
        main_count = len(paths["main"])
        si_count = len(paths["supplementary"])
        print(f"  {doi[:45]:<45} | {case_count} cases | {main_count} main, {si_count} SI")
    
    # Save mapping
    print(f"\nSaving mapping to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)
    
    print("\nDone!")
    
    # Also show what baseline DOIs are missing local PDFs
    baseline_dois = set(doi_to_cases.keys())
    missing = baseline_dois - matched_dois
    if missing:
        print(f"\nBaseline DOIs without local PDFs ({len(missing)}):")
        for doi in sorted(missing)[:10]:
            print(f"  {doi}")
        if len(missing) > 10:
            print(f"  ... and {len(missing) - 10} more")


if __name__ == "__main__":
    main()
