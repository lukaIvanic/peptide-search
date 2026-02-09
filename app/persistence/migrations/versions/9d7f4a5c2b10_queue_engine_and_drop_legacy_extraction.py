"""queue engine tables and remove legacy extraction table

Revision ID: 9d7f4a5c2b10
Revises: 23d3f1cf037f
Create Date: 2026-02-09 22:05:00.000000

"""
from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import json
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "9d7f4a5c2b10"
down_revision: Union[str, Sequence[str], None] = "4a5b6c7d8e9f"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _table_exists(inspector: sa.Inspector, table_name: str) -> bool:
    return table_name in inspector.get_table_names()


def _index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table_name)} if _table_exists(inspector, table_name) else set()


def _ensure_queue_tables(inspector: sa.Inspector) -> None:
    if not _table_exists(inspector, "queue_job"):
        op.create_table(
            "queue_job",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("source_fingerprint", sa.String(), nullable=False),
            sa.Column("status", sa.String(), nullable=False, server_default=sa.text("'queued'")),
            sa.Column("claimed_by", sa.String(), nullable=True),
            sa.Column("claim_token", sa.String(), nullable=True),
            sa.Column("attempt", sa.Integer(), nullable=False, server_default=sa.text("0")),
            sa.Column("available_at", sa.DateTime(), nullable=False),
            sa.Column("claimed_at", sa.DateTime(), nullable=True),
            sa.Column("finished_at", sa.DateTime(), nullable=True),
            sa.Column("payload_json", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.Column("updated_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["extraction_run.id"]),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("run_id", name="uq_queue_job_run_id"),
        )

    if not _table_exists(inspector, "active_source_lock"):
        op.create_table(
            "active_source_lock",
            sa.Column("source_fingerprint", sa.String(), nullable=False),
            sa.Column("run_id", sa.Integer(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["run_id"], ["extraction_run.id"]),
            sa.PrimaryKeyConstraint("source_fingerprint"),
        )


def _ensure_queue_indexes(inspector: sa.Inspector) -> None:
    queue_indexes = _index_names(inspector, "queue_job")
    if "ix_queue_job_run_id" not in queue_indexes:
        op.create_index("ix_queue_job_run_id", "queue_job", ["run_id"], unique=False)
    if "ix_queue_job_source_fingerprint" not in queue_indexes:
        op.create_index("ix_queue_job_source_fingerprint", "queue_job", ["source_fingerprint"], unique=False)
    if "ix_queue_job_status" not in queue_indexes:
        op.create_index("ix_queue_job_status", "queue_job", ["status"], unique=False)
    if "ix_queue_job_claimed_by" not in queue_indexes:
        op.create_index("ix_queue_job_claimed_by", "queue_job", ["claimed_by"], unique=False)
    if "ix_queue_job_claim_token" not in queue_indexes:
        op.create_index("ix_queue_job_claim_token", "queue_job", ["claim_token"], unique=False)
    if "ix_queue_job_available_at" not in queue_indexes:
        op.create_index("ix_queue_job_available_at", "queue_job", ["available_at"], unique=False)
    if "ix_queue_job_claimed_at" not in queue_indexes:
        op.create_index("ix_queue_job_claimed_at", "queue_job", ["claimed_at"], unique=False)
    if "ix_queue_job_finished_at" not in queue_indexes:
        op.create_index("ix_queue_job_finished_at", "queue_job", ["finished_at"], unique=False)

    lock_indexes = _index_names(inspector, "active_source_lock")
    if "ix_active_source_lock_run_id" not in lock_indexes:
        op.create_index("ix_active_source_lock_run_id", "active_source_lock", ["run_id"], unique=False)


def _fingerprint(url: str) -> str:
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()


def _backfill_queue_jobs(inspector: sa.Inspector) -> None:
    if not _table_exists(inspector, "extraction_run"):
        return
    bind = op.get_bind()
    run_columns = {col["name"] for col in inspector.get_columns("extraction_run")}
    select_columns = ["id", "paper_id", "pdf_url", "model_provider", "status", "created_at"]
    if "prompt_id" in run_columns:
        select_columns.append("prompt_id")
    if "prompt_version_id" in run_columns:
        select_columns.append("prompt_version_id")
    rows = bind.execute(
        sa.text(
            f"""
            SELECT {", ".join(select_columns)}
            FROM extraction_run
            WHERE status IN ('queued', 'fetching', 'provider', 'validating')
            """
        )
    ).mappings().all()

    now = datetime.now(UTC)
    for row in rows:
        run_id = row.get("id")
        pdf_url = (row.get("pdf_url") or "").strip()
        if not run_id or not pdf_url:
            continue

        fp = _fingerprint(pdf_url)

        existing_lock = bind.execute(
            sa.text("SELECT source_fingerprint FROM active_source_lock WHERE source_fingerprint = :fp"),
            {"fp": fp},
        ).first()
        if not existing_lock:
            bind.execute(
                sa.text(
                    """
                    INSERT INTO active_source_lock (source_fingerprint, run_id, created_at)
                    VALUES (:fp, :run_id, :created_at)
                    """
                ),
                {"fp": fp, "run_id": run_id, "created_at": row.get("created_at") or now},
            )

        existing_job = bind.execute(
            sa.text("SELECT id FROM queue_job WHERE run_id = :run_id"),
            {"run_id": run_id},
        ).first()
        payload = {
            "run_id": run_id,
            "paper_id": row.get("paper_id") or 0,
            "pdf_url": pdf_url,
            "pdf_urls": None,
            "title": "",
            "provider": row.get("model_provider") or "openai",
            "prompt_id": row.get("prompt_id"),
            "prompt_version_id": row.get("prompt_version_id"),
        }
        if existing_job:
            bind.execute(
                sa.text(
                    """
                    UPDATE queue_job
                    SET source_fingerprint = :fp,
                        status = 'queued',
                        claimed_by = NULL,
                        claim_token = NULL,
                        claimed_at = NULL,
                        finished_at = NULL,
                        available_at = :available_at,
                        updated_at = :updated_at
                    WHERE run_id = :run_id
                    """
                ),
                {
                    "fp": fp,
                    "available_at": row.get("created_at") or now,
                    "updated_at": now,
                    "run_id": run_id,
                },
            )
            continue

        bind.execute(
            sa.text(
                """
                INSERT INTO queue_job (
                    run_id,
                    source_fingerprint,
                    status,
                    claimed_by,
                    claim_token,
                    attempt,
                    available_at,
                    claimed_at,
                    finished_at,
                    payload_json,
                    created_at,
                    updated_at
                ) VALUES (
                    :run_id,
                    :source_fingerprint,
                    'queued',
                    NULL,
                    NULL,
                    0,
                    :available_at,
                    NULL,
                    NULL,
                    :payload_json,
                    :created_at,
                    :updated_at
                )
                """
            ),
            {
                "run_id": run_id,
                "source_fingerprint": fp,
                "available_at": row.get("created_at") or now,
                "payload_json": json.dumps(payload),
                "created_at": row.get("created_at") or now,
                "updated_at": now,
            },
        )


def _migrate_legacy_extraction_table(inspector: sa.Inspector) -> None:
    if not _table_exists(inspector, "extraction"):
        return

    bind = op.get_bind()
    run_columns = {col["name"] for col in inspector.get_columns("extraction_run")}
    extraction_rows = bind.execute(sa.text("SELECT * FROM extraction ORDER BY id ASC")).mappings().all()
    if not extraction_rows:
        op.drop_table("extraction")
        return

    now = datetime.utcnow()
    for row in extraction_rows:
        created_at = row.get("created_at") or now
        run_values = {
            "paper_id": row.get("paper_id"),
            "parent_run_id": None,
            "baseline_case_id": None,
            "baseline_dataset": None,
            "status": "stored",
            "failure_reason": None,
            "prompts_json": None,
            "prompt_id": None,
            "prompt_version_id": None,
            "raw_json": row.get("raw_json"),
            "comment": None,
            "model_provider": row.get("model_provider"),
            "model_name": row.get("model_name"),
            "batch_id": None,
            "input_tokens": None,
            "output_tokens": None,
            "reasoning_tokens": None,
            "total_tokens": None,
            "extraction_time_ms": None,
            "source_text_hash": None,
            "prompt_version": "legacy-import",
            "pdf_url": None,
            "created_at": created_at,
        }
        insert_columns = [name for name in run_values.keys() if name in run_columns]
        placeholders = ", ".join(f":{name}" for name in insert_columns)
        column_names = ", ".join(insert_columns)
        run_result = bind.execute(
            sa.text(
                f"""
                INSERT INTO extraction_run ({column_names})
                VALUES ({placeholders})
                """
            ),
            {name: run_values[name] for name in insert_columns},
        )
        run_id = run_result.lastrowid
        if not run_id:
            continue

        bind.execute(
            sa.text(
                """
                INSERT INTO extraction_entity (
                    run_id,
                    entity_index,
                    entity_type,
                    peptide_sequence_one_letter,
                    peptide_sequence_three_letter,
                    n_terminal_mod,
                    c_terminal_mod,
                    is_hydrogel,
                    chemical_formula,
                    smiles,
                    inchi,
                    labels,
                    morphology,
                    ph,
                    concentration,
                    concentration_units,
                    temperature_c,
                    cac,
                    cgc,
                    mgc,
                    validation_methods,
                    process_protocol,
                    reported_characteristics
                ) VALUES (
                    :run_id,
                    0,
                    :entity_type,
                    :peptide_sequence_one_letter,
                    :peptide_sequence_three_letter,
                    :n_terminal_mod,
                    :c_terminal_mod,
                    :is_hydrogel,
                    :chemical_formula,
                    :smiles,
                    :inchi,
                    :labels,
                    :morphology,
                    :ph,
                    :concentration,
                    :concentration_units,
                    :temperature_c,
                    :cac,
                    :cgc,
                    :mgc,
                    :validation_methods,
                    :process_protocol,
                    :reported_characteristics
                )
                """
            ),
            {
                "run_id": run_id,
                "entity_type": row.get("entity_type"),
                "peptide_sequence_one_letter": row.get("peptide_sequence_one_letter"),
                "peptide_sequence_three_letter": row.get("peptide_sequence_three_letter"),
                "n_terminal_mod": row.get("n_terminal_mod"),
                "c_terminal_mod": row.get("c_terminal_mod"),
                "is_hydrogel": row.get("is_hydrogel"),
                "chemical_formula": row.get("chemical_formula"),
                "smiles": row.get("smiles"),
                "inchi": row.get("inchi"),
                "labels": row.get("labels"),
                "morphology": row.get("morphology"),
                "ph": row.get("ph"),
                "concentration": row.get("concentration"),
                "concentration_units": row.get("concentration_units"),
                "temperature_c": row.get("temperature_c"),
                "cac": row.get("cac"),
                "cgc": row.get("cgc"),
                "mgc": row.get("mgc"),
                "validation_methods": row.get("validation_methods"),
                "process_protocol": row.get("process_protocol"),
                "reported_characteristics": row.get("reported_characteristics"),
            },
        )

    op.drop_table("extraction")


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    _ensure_queue_tables(inspector)
    inspector = sa.inspect(op.get_bind())
    _ensure_queue_indexes(inspector)
    inspector = sa.inspect(op.get_bind())
    _backfill_queue_jobs(inspector)
    inspector = sa.inspect(op.get_bind())
    _migrate_legacy_extraction_table(inspector)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not _table_exists(inspector, "extraction"):
        op.create_table(
            "extraction",
            sa.Column("id", sa.Integer(), nullable=False),
            sa.Column("paper_id", sa.Integer(), nullable=True),
            sa.Column("entity_type", sa.String(), nullable=True),
            sa.Column("peptide_sequence_one_letter", sa.String(), nullable=True),
            sa.Column("peptide_sequence_three_letter", sa.String(), nullable=True),
            sa.Column("n_terminal_mod", sa.String(), nullable=True),
            sa.Column("c_terminal_mod", sa.String(), nullable=True),
            sa.Column("chemical_formula", sa.String(), nullable=True),
            sa.Column("smiles", sa.String(), nullable=True),
            sa.Column("inchi", sa.String(), nullable=True),
            sa.Column("labels", sa.String(), nullable=True),
            sa.Column("morphology", sa.String(), nullable=True),
            sa.Column("ph", sa.Float(), nullable=True),
            sa.Column("concentration", sa.Float(), nullable=True),
            sa.Column("concentration_units", sa.String(), nullable=True),
            sa.Column("temperature_c", sa.Float(), nullable=True),
            sa.Column("is_hydrogel", sa.Boolean(), nullable=True),
            sa.Column("cac", sa.Float(), nullable=True),
            sa.Column("cgc", sa.Float(), nullable=True),
            sa.Column("mgc", sa.Float(), nullable=True),
            sa.Column("validation_methods", sa.String(), nullable=True),
            sa.Column("process_protocol", sa.String(), nullable=True),
            sa.Column("reported_characteristics", sa.String(), nullable=True),
            sa.Column("raw_json", sa.String(), nullable=True),
            sa.Column("model_name", sa.String(), nullable=True),
            sa.Column("model_provider", sa.String(), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=False),
            sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
            sa.PrimaryKeyConstraint("id"),
        )
        with op.batch_alter_table("extraction") as batch_op:
            batch_op.create_index(batch_op.f("ix_extraction_paper_id"), ["paper_id"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_entity_type"), ["entity_type"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_peptide_sequence_one_letter"), ["peptide_sequence_one_letter"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_n_terminal_mod"), ["n_terminal_mod"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_c_terminal_mod"), ["c_terminal_mod"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_chemical_formula"), ["chemical_formula"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_ph"), ["ph"], unique=False)
            batch_op.create_index(batch_op.f("ix_extraction_is_hydrogel"), ["is_hydrogel"], unique=False)

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "active_source_lock"):
        with op.batch_alter_table("active_source_lock") as batch_op:
            if "ix_active_source_lock_run_id" in _index_names(inspector, "active_source_lock"):
                batch_op.drop_index("ix_active_source_lock_run_id")
        op.drop_table("active_source_lock")

    inspector = sa.inspect(bind)
    if _table_exists(inspector, "queue_job"):
        with op.batch_alter_table("queue_job") as batch_op:
            for index_name in [
                "ix_queue_job_finished_at",
                "ix_queue_job_claimed_at",
                "ix_queue_job_available_at",
                "ix_queue_job_claim_token",
                "ix_queue_job_claimed_by",
                "ix_queue_job_status",
                "ix_queue_job_source_fingerprint",
                "ix_queue_job_run_id",
            ]:
                if index_name in _index_names(inspector, "queue_job"):
                    batch_op.drop_index(index_name)
        op.drop_table("queue_job")
