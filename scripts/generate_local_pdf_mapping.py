#!/usr/bin/env python3
"""
Generate a local PDF mapping file by scanning downloaded_papers folder
and correlating SS_#### numbers to baseline cases.

Usage:
    python scripts/generate_local_pdf_mapping.py [--verify] [--output PATH]
"""

import json
import re
import sys
from pathlib import Path

# Paths
WORKSPACE = Path(__file__).resolve().parent.parent
DOWNLOADED_PAPERS = WORKSPACE / "Peptide LLM" / "Datasets" / "downloaded_papers"
BASELINE_DATA = WORKSPACE / "app" / "baseline" / "data" / "self_assembly.json"
OUTPUT_FILE = WORKSPACE / "app" / "baseline" / "data" / "local_pdfs.json"


def load_baseline_cases():
    """Load self_assembly baseline cases."""
    with open(BASELINE_DATA, "r", encoding="utf-8") as f:
        return json.load(f)


def scan_local_pdfs():
    """Scan downloaded_papers folder for PDFs and other documents."""
    files = []
    if not DOWNLOADED_PAPERS.exists():
        print(f"Warning: {DOWNLOADED_PAPERS} does not exist")
        return files
    
    # Supported extensions
    extensions = {".pdf", ".doc", ".docx", ".zip"}
    
    for path in DOWNLOADED_PAPERS.rglob("*"):
        if path.is_file() and path.suffix.lower() in extensions:
            files.append(path)
    
    return files


def extract_ss_number(filename):
    """Extract SS_#### number from filename like SS_0008_SI.pdf"""
    match = re.search(r"SS_(\d+)", filename, re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def ss_number_to_case_id(ss_num):
    """Convert SS number to baseline case ID."""
    return f"self_assembly:pos:{ss_num}"


def generate_mapping(cases, files, verify_only=False):
    """Generate DOI -> local PDF mapping."""
    # Build case lookup by ID
    case_by_id = {c["id"]: c for c in cases}
    
    # Build DOI -> cases lookup
    doi_to_cases = {}
    for case in cases:
        doi = case.get("doi")
        if doi:
            doi_to_cases.setdefault(doi, []).append(case)
    
    # Process files
    mapping = {}  # DOI -> {main: [], supplementary: []}
    verification_rows = []
    
    for file_path in sorted(files):
        filename = file_path.name
        ss_num = extract_ss_number(filename)
        
        if ss_num is None:
            print(f"Warning: Could not extract SS number from {filename}")
            continue
        
        case_id = ss_number_to_case_id(ss_num)
        case = case_by_id.get(case_id)
        
        if not case:
            print(f"Warning: No baseline case found for {case_id} (from {filename})")
            continue
        
        doi = case.get("doi")
        sequence = case.get("sequence", "")[:30]
        is_si = "_SI" in filename.upper() or "_si" in filename
        rel_path = str(file_path.relative_to(WORKSPACE))
        
        # Add to verification table
        verification_rows.append({
            "ss_num": ss_num,
            "case_id": case_id,
            "doi": doi,
            "sequence": sequence + ("..." if len(case.get("sequence", "")) > 30 else ""),
            "file": filename,
            "type": "SI" if is_si else "Main",
        })
        
        # Add to mapping
        if doi:
            if doi not in mapping:
                mapping[doi] = {"main": [], "supplementary": []}
            
            key = "supplementary" if is_si else "main"
            if rel_path not in mapping[doi][key]:
                mapping[doi][key].append(rel_path)
    
    return mapping, verification_rows


def print_verification_table(rows):
    """Print a verification table."""
    print("\n" + "=" * 100)
    print("VERIFICATION TABLE - Check if DOIs match the expected papers")
    print("=" * 100)
    print(f"{'SS#':<8} {'Case ID':<22} {'Type':<6} {'DOI':<40} {'Sequence':<30}")
    print("-" * 100)
    
    for row in rows:
        print(f"{row['ss_num']:<8} {row['case_id']:<22} {row['type']:<6} {row['doi'] or 'N/A':<40} {row['sequence']:<30}")
    
    print("=" * 100)
    print(f"\nTotal: {len(rows)} files mapped")


def main():
    verify_only = "--verify" in sys.argv
    
    print("Loading baseline cases...")
    cases = load_baseline_cases()
    print(f"Loaded {len(cases)} baseline cases")
    
    print("\nScanning downloaded_papers folder...")
    files = scan_local_pdfs()
    print(f"Found {len(files)} files")
    
    print("\nGenerating mapping...")
    mapping, verification_rows = generate_mapping(cases, files)
    
    # Print verification table
    print_verification_table(verification_rows)
    
    if verify_only:
        print("\n[Verify mode] No files written. Run without --verify to save mapping.")
        return
    
    # Save mapping
    print(f"\nSaving mapping to {OUTPUT_FILE}...")
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(mapping, f, indent=2)
    
    print("Done!")
    print(f"\nMapping saved. {len(mapping)} DOIs mapped to local files.")
    
    # Summary by DOI
    print("\nSummary by DOI:")
    for doi, paths in sorted(mapping.items()):
        main_count = len(paths.get("main", []))
        si_count = len(paths.get("supplementary", []))
        print(f"  {doi}: {main_count} main, {si_count} SI")


if __name__ == "__main__":
    main()
