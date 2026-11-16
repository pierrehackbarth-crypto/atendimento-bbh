"""módulo amarelo (Controle de Prazos): equipe de cada pessoa nos prazos"""
from alembic import op
import sqlalchemy as sa

revision = "0004_prazos"
down_revision = "0003_permissoes"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("prazos_equipe", sa.Integer(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_column("prazos_equipe")
