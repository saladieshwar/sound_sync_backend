"""songs: single search column + trigram index; musical_rooms: foreign-key and active-room
indexes, created_at defaults to clock_timestamp()

Revision ID: 0005
Revises: 0004
Create Date: 2026-10-07
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# chr(31) (unit separator) keeps a search term from matching across two fields.
SEARCH_TEXT_SQL = "lower(title || chr(31) || artist || chr(31) || coalesce(album, ''))"
_OLD_TRGM_COLUMNS = ("title", "artist", "album")
_ROOM_FK_COLUMNS = ("admin_user_id", "controller_user_id", "current_song_id")


def upgrade() -> None:
    # One pre-lowered column: a single trigram index probe instead of three, and plain LIKE
    # instead of per-row ILIKE case folding (8x faster on the 1-2 letter searches that cannot use
    # trigrams and fall back to a scan).
    op.add_column(
        "songs",
        sa.Column("search_text", sa.Text(), sa.Computed(SEARCH_TEXT_SQL, persisted=True), nullable=False),
    )
    op.create_index(
        "ix_songs_search_trgm",
        "songs",
        ["search_text"],
        postgresql_using="gin",
        postgresql_ops={"search_text": "gin_trgm_ops"},
    )
    for column in _OLD_TRGM_COLUMNS:
        op.drop_index(f"ix_songs_{column}_trgm", table_name="songs")

    # Without these, deleting a user or song (CASCADE / SET NULL) scans every room.
    for column in _ROOM_FK_COLUMNS:
        op.create_index(f"ix_musical_rooms_{column}", "musical_rooms", [column])
    op.create_index(
        "ix_musical_rooms_active_created_at",
        "musical_rooms",
        [sa.text("created_at DESC")],
        postgresql_where=sa.text("status = 'active'"),
    )
    # Same reason as liked_at / played_at in 0003: now() is frozen per transaction.
    op.alter_column("musical_rooms", "created_at", server_default=sa.text("clock_timestamp()"))


def downgrade() -> None:
    op.alter_column("musical_rooms", "created_at", server_default=sa.text("now()"))
    op.drop_index("ix_musical_rooms_active_created_at", table_name="musical_rooms")
    for column in reversed(_ROOM_FK_COLUMNS):
        op.drop_index(f"ix_musical_rooms_{column}", table_name="musical_rooms")

    for column in _OLD_TRGM_COLUMNS:
        op.create_index(
            f"ix_songs_{column}_trgm",
            "songs",
            [column],
            postgresql_using="gin",
            postgresql_ops={column: "gin_trgm_ops"},
        )
    op.drop_index("ix_songs_search_trgm", table_name="songs")
    op.drop_column("songs", "search_text")
