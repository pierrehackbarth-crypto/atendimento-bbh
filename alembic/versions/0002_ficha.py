"""ficha de atendimento no servidor próprio: documentos, versões e anexos"""
from alembic import op
import sqlalchemy as sa

revision = "0002_ficha"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("store_docs",
                    sa.Column("collection", sa.String(40), primary_key=True),
                    sa.Column("doc_id", sa.String(120), primary_key=True),
                    sa.Column("data", sa.JSON(), nullable=False),
                    sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("updated_by", sa.String(32), nullable=True))
    op.create_table("store_versions",
                    sa.Column("collection", sa.String(40), primary_key=True),
                    sa.Column("version", sa.Integer(), nullable=False))
    op.create_table("assets",
                    sa.Column("id", sa.String(32), primary_key=True),
                    sa.Column("storage_key", sa.String(80), nullable=True),
                    sa.Column("name", sa.String(255), nullable=False),
                    sa.Column("mime", sa.String(100), nullable=False),
                    sa.Column("size", sa.Integer(), nullable=False),
                    sa.Column("created_by", sa.String(32), nullable=False),
                    sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
                    sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))


def downgrade():
    op.drop_table("assets")
    op.drop_table("store_versions")
    op.drop_table("store_docs")
