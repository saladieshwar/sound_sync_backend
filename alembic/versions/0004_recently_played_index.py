"""recently_played: index matching the newest-first history query

Revision ID: 0004
Revises: 0003
Create Date: 2026-10-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_recently_played_user_played_at_id",
        "recently_played",
        ["user_id", sa.text("played_at DESC"), sa.text("id DESC")],
    )
    op.drop_index("ix_recently_played_user_played_at", table_name="recently_played")


def downgrade() -> None:
    op.create_index(
        "ix_recently_played_user_played_at", "recently_played", ["user_id", "played_at"]
    )
    op.drop_index("ix_recently_played_user_played_at_id", table_name="recently_played")
