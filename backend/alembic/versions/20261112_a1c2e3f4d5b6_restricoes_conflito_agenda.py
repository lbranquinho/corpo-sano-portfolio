"""restrições de conflito da agenda (exclusão por intervalo de tempo)

Garante no próprio banco que um profissional ou uma sala não tenham dois atendimentos
ativos sobrepostos, mesmo em requisições simultâneas.

Revision ID: a1c2e3f4d5b6
Revises: f8561b093cae
Create Date: 2026-11-12
"""
from typing import Sequence, Union

from alembic import op

revision: str = "a1c2e3f4d5b6"
down_revision: Union[str, None] = "f8561b093cae"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_professional "
        "EXCLUDE USING gist (professional_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&) "
        "WHERE (status NOT IN ('cancelado', 'falta'))"
    )
    op.execute(
        "ALTER TABLE appointments ADD CONSTRAINT ex_appointments_room "
        "EXCLUDE USING gist (room_id WITH =, tstzrange(start_at, end_at, '[)') WITH &&) "
        "WHERE (room_id IS NOT NULL AND status NOT IN ('cancelado', 'falta'))"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ex_appointments_room")
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ex_appointments_professional")
