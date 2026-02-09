"""create core tables for alembic-only lifecycle

Revision ID: 0f1a2b3c4d5e
Revises:
Create Date: 2026-02-09 22:22:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
import sqlmodel.sql.sqltypes


# revision identifiers, used by Alembic.
revision: str = "0f1a2b3c4d5e"
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "paper",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("title", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("doi", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("url", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("source", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("year", sa.Integer(), nullable=True),
        sa.Column("authors_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("paper", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_paper_title"), ["title"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_doi"), ["doi"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_source"), ["source"], unique=False)
        batch_op.create_index(batch_op.f("ix_paper_year"), ["year"], unique=False)

    op.create_table(
        "extraction",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("paper_id", sa.Integer(), nullable=True),
        sa.Column("entity_type", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("peptide_sequence_one_letter", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("peptide_sequence_three_letter", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("n_terminal_mod", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("c_terminal_mod", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("chemical_formula", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("smiles", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("inchi", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("labels", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("morphology", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("ph", sa.Float(), nullable=True),
        sa.Column("concentration", sa.Float(), nullable=True),
        sa.Column("concentration_units", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("temperature_c", sa.Float(), nullable=True),
        sa.Column("is_hydrogel", sa.Boolean(), nullable=True),
        sa.Column("cac", sa.Float(), nullable=True),
        sa.Column("cgc", sa.Float(), nullable=True),
        sa.Column("mgc", sa.Float(), nullable=True),
        sa.Column("validation_methods", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("process_protocol", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("reported_characteristics", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("raw_json", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("model_name", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("model_provider", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["paper_id"], ["paper.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("extraction", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_extraction_paper_id"), ["paper_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_entity_type"), ["entity_type"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_peptide_sequence_one_letter"), ["peptide_sequence_one_letter"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_n_terminal_mod"), ["n_terminal_mod"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_c_terminal_mod"), ["c_terminal_mod"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_chemical_formula"), ["chemical_formula"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_ph"), ["ph"], unique=False)
        batch_op.create_index(batch_op.f("ix_extraction_is_hydrogel"), ["is_hydrogel"], unique=False)

    op.create_table(
        "base_prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("description", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("base_prompt", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_base_prompt_name"), ["name"], unique=False)
        batch_op.create_index(batch_op.f("ix_base_prompt_is_active"), ["is_active"], unique=False)

    op.create_table(
        "prompt_version",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("prompt_id", sa.Integer(), nullable=False),
        sa.Column("version_index", sa.Integer(), nullable=False),
        sa.Column("content", sqlmodel.sql.sqltypes.AutoString(), nullable=False),
        sa.Column("notes", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_by", sqlmodel.sql.sqltypes.AutoString(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["prompt_id"], ["base_prompt.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    with op.batch_alter_table("prompt_version", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_prompt_version_prompt_id"), ["prompt_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("prompt_version", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_prompt_version_prompt_id"))
    op.drop_table("prompt_version")

    with op.batch_alter_table("base_prompt", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_base_prompt_is_active"))
        batch_op.drop_index(batch_op.f("ix_base_prompt_name"))
    op.drop_table("base_prompt")

    with op.batch_alter_table("extraction", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_extraction_is_hydrogel"))
        batch_op.drop_index(batch_op.f("ix_extraction_ph"))
        batch_op.drop_index(batch_op.f("ix_extraction_chemical_formula"))
        batch_op.drop_index(batch_op.f("ix_extraction_c_terminal_mod"))
        batch_op.drop_index(batch_op.f("ix_extraction_n_terminal_mod"))
        batch_op.drop_index(batch_op.f("ix_extraction_peptide_sequence_one_letter"))
        batch_op.drop_index(batch_op.f("ix_extraction_entity_type"))
        batch_op.drop_index(batch_op.f("ix_extraction_paper_id"))
    op.drop_table("extraction")

    with op.batch_alter_table("paper", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_paper_year"))
        batch_op.drop_index(batch_op.f("ix_paper_source"))
        batch_op.drop_index(batch_op.f("ix_paper_doi"))
        batch_op.drop_index(batch_op.f("ix_paper_title"))
    op.drop_table("paper")
