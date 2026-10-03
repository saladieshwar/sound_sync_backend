"""users: enforce lowercase email and bcrypt-only password_hash

Revision ID: 0002
Revises: 0001
Create Date: 2026-10-03
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_check_constraint("ck_users_email_lowercase", "users", "email = lower(email)")
    op.create_check_constraint(
        "ck_users_password_hash_bcrypt", "users", "password_hash ~ '^\\$2[aby]\\$'"
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_password_hash_bcrypt", "users", type_="check")
    op.drop_constraint("ck_users_email_lowercase", "users", type_="check")
