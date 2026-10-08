"""scripts.make_admin: promotes a registered account on a hosted (unseeded) database."""

from app.repositories import user_repo
from scripts.make_admin import make_admin


def test_make_admin_promotes_an_existing_account(db, make_user):
    payload, _ = make_user()

    assert make_admin(db, payload["email"].upper()) is True
    assert user_repo.get_by_email(db, payload["email"]).is_admin is True


def test_make_admin_reports_an_unknown_email(db):
    assert make_admin(db, "nobody@example.com") is False
