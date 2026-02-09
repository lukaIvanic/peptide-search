"""Batch CLI for extracting peptides from multiple papers.

Usage:
    python -m cli.batch extract --input urls.txt
    python -m cli.batch extract --input urls.txt --output results.json
    python -m cli.batch extract --input urls.txt --skip-existing
    
Input file format (one per line):
    - URLs: https://example.com/paper.pdf
    - DOIs: 10.1234/example.doi
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from typing import Optional
from datetime import datetime

import typer

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from app.config import settings
from app.db import get_session, init_db
from app.services.extraction_service import run_extraction, get_provider
from app.schemas import ExtractRequest
from app.persistence.repository import PaperRepository

app = typer.Typer(
    name="peptide-batch",
    help="Batch extraction CLI for peptide literature analysis.",
)


def _is_doi(line: str) -> bool:
    """Check if the line looks like a DOI."""
    line = line.strip()
    return line.startswith("10.") or line.startswith("doi:")


def _normalize_doi(doi: str) -> str:
    """Normalize a DOI string."""
    doi = doi.strip()
    if doi.startswith("doi:"):
        doi = doi[4:]
    if doi.startswith("https://doi.org/"):
        doi = doi[16:]
    return doi


def _doi_to_url(doi: str) -> str:
    """Convert a DOI to a resolvable URL."""
    return f"https://doi.org/{doi}"


@app.command()
def extract(
    input_file: Path = typer.Option(
        ..., "--input", "-i",
        help="Input file with URLs or DOIs (one per line)",
        exists=True,
        readable=True,
    ),
    output_file: Optional[Path] = typer.Option(
        None, "--output", "-o",
        help="Output JSON file for results (optional)",
    ),
    skip_existing: bool = typer.Option(
        False, "--skip-existing", "-s",
        help="Skip URLs/DOIs that have already been extracted",
    ),
    verbose: bool = typer.Option(
        False, "--verbose", "-v",
        help="Show detailed progress",
    ),
):
    """
    Extract peptide data from a list of papers.
    
    Reads URLs or DOIs from the input file (one per line) and runs
    extraction on each, storing results in the database.
    """
    # Read input file
    lines = input_file.read_text(encoding="utf-8").strip().split("\n")
    items = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _is_doi(line):
            doi = _normalize_doi(line)
            items.append({"type": "doi", "value": doi, "url": _doi_to_url(doi)})
        else:
            items.append({"type": "url", "value": line, "url": line})
    
    if not items:
        typer.echo("No valid URLs or DOIs found in input file.")
        raise typer.Exit(1)
    
    typer.echo(f"Found {len(items)} items to process")
    typer.echo(f"Provider: {settings.LLM_PROVIDER}")
    
    # Run extraction
    asyncio.run(_run_batch_extraction(
        items=items,
        output_file=output_file,
        skip_existing=skip_existing,
        verbose=verbose,
    ))


async def _run_batch_extraction(
    items: list,
    output_file: Optional[Path],
    skip_existing: bool,
    verbose: bool,
):
    """Run batch extraction asynchronously."""
    init_db()
    
    results = []
    stats = {"total": len(items), "extracted": 0, "skipped": 0, "failed": 0}
    
    # Get a session
    session_gen = get_session()
    session = next(session_gen)
    
    try:
        paper_repo = PaperRepository(session)
        
        for i, item in enumerate(items, 1):
            url = item["url"]
            item_type = item["type"]
            value = item["value"]
            
            typer.echo(f"\n[{i}/{len(items)}] Processing {item_type}: {value}")
            
            # Check if already extracted
            if skip_existing:
                if item_type == "doi":
                    existing_paper = paper_repo.find_by_doi(value)
                else:
                    existing_paper = paper_repo.find_by_url(url)
                
                if existing_paper:
                    # A paper existing is not the same as being extracted.
                    # Skip only if it already has at least one extraction run.
                    from sqlmodel import select
                    from app.persistence.models import ExtractionRun

                    has_new = session.exec(
                        select(ExtractionRun.id)
                        .where(ExtractionRun.paper_id == existing_paper.id)
                        .limit(1)
                    ).first()

                    if has_new:
                        typer.echo("  Skipping (already extracted)")
                        stats["skipped"] += 1
                        results.append({
                            "input": value,
                            "status": "skipped",
                            "reason": "already_extracted",
                            "paper_id": existing_paper.id,
                        })
                        continue
                    
                    # Paper exists but has no stored extractions; proceed.
                    typer.echo("  Paper exists but has no stored extractions; extracting anyway.")
            
            # Build request
            req = ExtractRequest(pdf_url=url)
            if item_type == "doi":
                req.doi = value
            
            # Run extraction
            try:
                extraction_id, paper_id, payload = await run_extraction(session, req)
                
                entity_count = len(payload.entities)
                typer.echo(f"  Extracted {entity_count} entities (paper_id={paper_id})")
                
                stats["extracted"] += 1
                results.append({
                    "input": value,
                    "status": "success",
                    "paper_id": paper_id,
                    "extraction_id": extraction_id,  # ExtractionRun.id (new storage)
                    "entity_count": entity_count,
                    "title": payload.paper.title,
                    "comment": payload.comment,
                })
                
                if verbose and payload.entities:
                    for ent in payload.entities:
                        if ent.type == "peptide" and ent.peptide:
                            seq = ent.peptide.sequence_one_letter or ent.peptide.sequence_three_letter
                            typer.echo(f"    - {ent.type}: {seq}")
                        elif ent.type == "molecule" and ent.molecule:
                            typer.echo(f"    - {ent.type}: {ent.molecule.chemical_formula}")
                
            except Exception as e:
                error_msg = str(e)
                typer.echo(f"  Failed: {error_msg[:100]}")
                stats["failed"] += 1
                results.append({
                    "input": value,
                    "status": "failed",
                    "error": error_msg,
                })
    
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass
    
    # Print summary
    typer.echo("\n" + "=" * 50)
    typer.echo("Summary:")
    typer.echo(f"  Total:     {stats['total']}")
    typer.echo(f"  Extracted: {stats['extracted']}")
    typer.echo(f"  Skipped:   {stats['skipped']}")
    typer.echo(f"  Failed:    {stats['failed']}")
    
    # Write output file
    if output_file:
        output_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "provider": settings.LLM_PROVIDER,
            "stats": stats,
            "results": results,
        }
        output_file.write_text(json.dumps(output_data, indent=2, ensure_ascii=False))
        typer.echo(f"\nResults written to: {output_file}")


@app.command()
def info():
    """Show current configuration."""
    typer.echo("Peptide Literature Extractor - Batch CLI")
    typer.echo()
    typer.echo(f"LLM Provider: {settings.LLM_PROVIDER}")
    typer.echo(f"Database:     {settings.DB_URL}")
    
    provider = get_provider()
    caps = provider.capabilities()
    typer.echo()
    typer.echo("Provider Capabilities:")
    typer.echo(f"  - PDF URL support:  {caps.supports_pdf_url}")
    typer.echo(f"  - PDF file support: {caps.supports_pdf_file}")
    typer.echo(f"  - JSON mode:        {caps.supports_json_mode}")


@app.command()
def stats():
    """Show database statistics."""
    init_db()
    session_gen = get_session()
    session = next(session_gen)
    
    from sqlmodel import select, func
    from app.persistence.models import Paper, ExtractionRun, ExtractionEntity
    
    try:
        paper_count = session.exec(select(func.count(Paper.id))).one()
        run_count = session.exec(select(func.count(ExtractionRun.id))).one()
        entity_count = session.exec(select(func.count(ExtractionEntity.id))).one()
        
        typer.echo("Database Statistics:")
        typer.echo(f"  Papers:            {paper_count}")
        typer.echo(f"  Extraction Runs:   {run_count}")
        typer.echo(f"  Entities:          {entity_count}")
    finally:
        try:
            next(session_gen)
        except StopIteration:
            pass


if __name__ == "__main__":
    app()
