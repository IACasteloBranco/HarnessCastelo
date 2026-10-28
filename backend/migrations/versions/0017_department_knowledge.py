"""Add encrypted department knowledge documents and pgvector chunks."""

from alembic import op
import sqlalchemy as sa
from pgvector.sqlalchemy import Vector


revision = "0017_department_knowledge"
down_revision = "0016_reliable_profile_context"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.create_table(
        "department_documents",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("organization_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("department_id", sa.Uuid(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("mime_type", sa.String(128), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("created_by", sa.Uuid(as_uuid=True), sa.ForeignKey("employees.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["organization_id", "department_id"],
            ["departments.organization_id", "departments.id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("organization_id", "department_id", "sha256",
                            name="uq_department_documents_content"),
    )
    op.create_index("ix_department_documents_scope", "department_documents",
                    ["organization_id", "department_id", "created_at"])
    op.create_table(
        "department_document_chunks",
        sa.Column("id", sa.Uuid(as_uuid=True), primary_key=True),
        sa.Column("document_id", sa.Uuid(as_uuid=True),
                  sa.ForeignKey("department_documents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("text_ciphertext", sa.LargeBinary(), nullable=False),
        sa.Column("embedding", Vector(384), nullable=False),
        sa.UniqueConstraint("document_id", "ordinal"),
    )
    op.create_index("ix_department_document_chunks_document_id", "department_document_chunks",
                    ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_department_document_chunks_document_id", table_name="department_document_chunks")
    op.drop_table("department_document_chunks")
    op.drop_index("ix_department_documents_scope", table_name="department_documents")
    op.drop_table("department_documents")
