"""catalog search/category indexes, library indexes, per-row library timestamps

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_TRGM_COLUMNS = ("title", "artist", "album")


def upgrade() -> None:
    # pg_trgm is a trusted extension (PG13+), so the database owner can create it.
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    for column in _TRGM_COLUMNS:
        op.create_index(
            f"ix_songs_{column}_trgm",
            "songs",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )
    op.create_index("ix_songs_category_lower", "songs", [sa.text("lower(category)")])

    op.create_index("ix_liked_songs_user_liked_at", "liked_songs", ["user_id", "liked_at"])
    op.create_index("ix_liked_songs_song_id", "liked_songs", ["song_id"])
    op.create_index("ix_recently_played_song_id", "recently_played", ["song_id"])

    op.alter_column("liked_songs", "liked_at", server_default=sa.text("clock_timestamp()"))
    op.alter_column("recently_played", "played_at", server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    op.alter_column("recently_played", "played_at", server_default=sa.text("now()"))
    op.alter_column("liked_songs", "liked_at", server_default=sa.text("now()"))

    op.drop_index("ix_recently_played_song_id", table_name="recently_played")
    op.drop_index("ix_liked_songs_song_id", table_name="liked_songs")
    op.drop_index("ix_liked_songs_user_liked_at", table_name="liked_songs")

    op.drop_index("ix_songs_category_lower", table_name="songs")
    for column in reversed(_TRGM_COLUMNS):
        op.drop_index(f"ix_songs_{column}_trgm", table_name="songs")
