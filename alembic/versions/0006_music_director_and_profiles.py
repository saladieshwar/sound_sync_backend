"""songs: music_director; users: profile details (full_name, phone, bio, avatar_url)

Revision ID: 0006
Revises: 0005
Create Date: 2026-10-08
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_PROFILE_COLUMNS = (
    ("full_name", 100),
    ("phone", 20),
    ("bio", 300),
    ("avatar_url", 500),
)


def upgrade() -> None:
    op.add_column("songs", sa.Column("music_director", sa.String(length=200), nullable=True))
    for name, length in _PROFILE_COLUMNS:
        op.add_column("users", sa.Column(name, sa.String(length=length), nullable=True))


def downgrade() -> None:
    for name, _ in reversed(_PROFILE_COLUMNS):
        op.drop_column("users", name)
    op.drop_column("songs", "music_director")
