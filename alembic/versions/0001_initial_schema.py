"""initial schema: users, songs, library, rooms

Revision ID: 0001
Revises:
Create Date: 2026-10-03
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

room_status = sa.Enum("active", "closed", name="room_status")


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(50), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("password_hash", sa.String(255), nullable=False),
        sa.Column("is_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "songs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("artist", sa.String(200), nullable=False),
        sa.Column("album", sa.String(200)),
        sa.Column("category", sa.String(50), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("audio_url", sa.String(500), nullable=False),
        sa.Column("cover_url", sa.String(500)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_songs_title", "songs", ["title"])
    op.create_index("ix_songs_artist", "songs", ["artist"])
    op.create_index("ix_songs_album", "songs", ["album"])
    op.create_index("ix_songs_category", "songs", ["category"])

    op.create_table(
        "liked_songs",
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("song_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("liked_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "recently_played",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("song_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_recently_played_user_played_at", "recently_played", ["user_id", "played_at"]
    )

    op.create_table(
        "musical_rooms",
        sa.Column("id", sa.String(12), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("admin_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("controller_user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("current_song_id", sa.Integer(), sa.ForeignKey("songs.id", ondelete="SET NULL")),
        sa.Column("is_playing", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("position_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("state_updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("status", room_status, nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "room_participants",
        sa.Column("room_id", sa.String(12), sa.ForeignKey("musical_rooms.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_index("ix_room_participants_user_id", "room_participants", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_room_participants_user_id", table_name="room_participants")
    op.drop_table("room_participants")
    op.drop_table("musical_rooms")
    room_status.drop(op.get_bind(), checkfirst=True)
    op.drop_index("ix_recently_played_user_played_at", table_name="recently_played")
    op.drop_table("recently_played")
    op.drop_table("liked_songs")
    for name in ("ix_songs_category", "ix_songs_album", "ix_songs_artist", "ix_songs_title"):
        op.drop_index(name, table_name="songs")
    op.drop_table("songs")
    op.drop_index("ix_users_email", table_name="users")
    op.drop_table("users")
