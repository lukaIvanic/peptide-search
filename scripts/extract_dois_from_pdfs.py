#!/usr/bin/env python3
"""
Extract DOIs from PDF files to help create the mapping.
Tries multiple methods: metadata, first page text, filename patterns.
"""

import json
import re
import sys
from pathlib import Path

try:
    import fitz  # PyMuPDF
    HAS_PYMUPDF = True
except ImportError:
    HAS_PYMUPDF = False
    print("PyMuPDF not installed. Install with: pip install pymupdf")

# Paths
WORKSPACE = Path(__file__).resolve().parent.parent
DOWNLOADED_PAPERS = WORKSPACE / "Peptide LLM" / "Datasets" / "downloaded_papers"

# DOI regex pattern
DOI_PATTERN = re.compile(r'10\.\d{4,}/[^\s\]>\)"\']+', re.IGNORECASE)


def extract_doi_from_pdf(pdf_path):
    """Try to extract DOI from a PDF file."""
    if not HAS_PYMUPDF:
        return None, "PyMuPDF not installed"
    
    try:
        doc = fitz.open(pdf_path)
        
        # Method 1: Check metadata
        metadata = doc.metadata
        if metadata:
            for key in ['doi', 'subject', 'keywords', 'title']:
                value = metadata.get(key, '')
                if value:
                    match = DOI_PATTERN.search(value)
                    if match:
                        return clean_doi(match.group()), f"metadata.{key}"
        
        # Method 2: Search first few pages
        for page_num in range(min(3, len(doc))):
            page = doc[page_num]
            text = page.get_text()
            
            # Look for DOI patterns
            matches = DOI_PATTERN.findall(text)
            if matches:
                # Return the first valid-looking DOI
                for doi in matches:
                    cleaned = clean_doi(doi)
                    if is_valid_doi(cleaned):
                        return cleaned, f"page_{page_num + 1}"
        
        doc.close()
        return None, "not_found"
        
    except Exception as e:
        return None, f"error: {str(e)[:50]}"


def clean_doi(doi):
    """Clean up a DOI string."""
    doi = doi.strip()
    # Remove trailing punctuation
    doi = re.sub(r'[.,;:\]>\)]+$', '', doi)
    # Remove common suffixes
    doi = re.sub(r'\.pdf$', '', doi, flags=re.IGNORECASE)
    return doi


def is_valid_doi(doi):
    """Basic validation of DOI format."""
    if not doi or len(doi) < 10:
        return False
    if not doi.startswith('10.'):
        return False
    if '/' not in doi:
        return False
    return True


def scan_pdfs():
    """Scan all PDFs and try to extract DOIs."""
    results = []
    
    if not DOWNLOADED_PAPERS.exists():
        print(f"Error: {DOWNLOADED_PAPERS} does not exist")
        return results
    
    pdf_files = list(DOWNLOADED_PAPERS.rglob("*.pdf"))
    print(f"Found {len(pdf_files)} PDF files\n")
    
    for pdf_path in sorted(pdf_files):
        rel_path = pdf_path.relative_to(WORKSPACE)
        filename = pdf_path.name
        
        doi, source = extract_doi_from_pdf(pdf_path)
        
        results.append({
            "filename": filename,
            "path": str(rel_path),
            "doi": doi,
            "source": source,
        })
        
        status = f"[OK] {doi}" if doi else f"[--] ({source})"
        print(f"  {filename:<30} {status}")
    
    return results


def main():
    if not HAS_PYMUPDF:
        print("\nTo extract DOIs, install PyMuPDF:")
        print("  pip install pymupdf")
        sys.exit(1)
    
    print("Scanning PDFs for DOIs...\n")
    results = scan_pdfs()
    
    # Summary
    found = [r for r in results if r["doi"]]
    not_found = [r for r in results if not r["doi"]]
    
    print(f"\n{'='*60}")
    print(f"Summary: {len(found)}/{len(results)} DOIs extracted")
    print(f"{'='*60}")
    
    if found:
        print("\nExtracted DOIs:")
        for r in found:
            print(f"  {r['filename']:<30} -> {r['doi']}")
    
    if not_found:
        print(f"\nCould not extract ({len(not_found)} files):")
        for r in not_found:
            print(f"  {r['filename']:<30} ({r['source']})")
    
    # Save results
    output_path = WORKSPACE / "scripts" / "extracted_dois.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    print(f"\nResults saved to: {output_path}")


if __name__ == "__main__":
    main()
