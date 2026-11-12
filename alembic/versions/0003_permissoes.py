"""permissões por usuário, definidas pelo administrador"""
from alembic import op
import sqlalchemy as sa

revision = "0003_permissoes"
down_revision = "0002_ficha"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as b:
        b.add_column(sa.Column("perms", sa.JSON(), nullable=True))


def downgrade():
    with op.batch_alter_table("users") as b:
        b.drop_column("perms")
