from app.database import SessionLocal
from app.models import AdminUser, AuditLog
from app.security import verify_password


def login(client, username, password):
    return client.post(
        "/admin/login",
        data={"username": username, "password": password},
        follow_redirects=False,
    )


def create_user(username="operator", role="reviewer", password="StrongPass123"):
    with SessionLocal() as db:
        user = AdminUser(
            username=username,
            display_name=username.title(),
            role=role,
            active=True,
            password_hash="placeholder",
        )
        from app.security import hash_password

        user.password_hash = hash_password(password)
        db.add(user)
        db.commit()
        return user.id


def test_super_admin_can_open_user_management(admin_client):
    response = admin_client.get("/admin/users")
    assert response.status_code == 200
    assert "Admin Users" in response.text
    assert "password_hash" not in response.text


def test_reviewer_cannot_access_user_management(client):
    create_user()
    assert login(client, "operator", "StrongPass123").status_code == 303
    response = client.get("/admin/users")
    assert response.status_code == 403


def test_create_user_validates_and_hashes_password(admin_client):
    response = admin_client.post(
        "/admin/users/new",
        data={
            "username": " New.User ",
            "display_name": "New User",
            "email": "new@example.com",
            "role": "admin",
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
            "active": "1",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        user = db.query(AdminUser).filter_by(username="new.user").one()
        assert user.role == "admin"
        assert user.password_hash != "StrongPass123"
        assert verify_password("StrongPass123", user.password_hash)
        assert db.query(AuditLog).filter_by(action="admin_user_created").count() == 1


def test_duplicate_username_and_password_confirmation_are_rejected(admin_client):
    create_user(username="dupe")
    duplicate = admin_client.post(
        "/admin/users/new",
        data={
            "username": "dupe",
            "display_name": "Dupe",
            "role": "reviewer",
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
            "active": "1",
        },
    )
    mismatch = admin_client.post(
        "/admin/users/new",
        data={
            "username": "different",
            "display_name": "Different",
            "role": "reviewer",
            "password": "StrongPass123",
            "confirm_password": "WrongPass123",
            "active": "1",
        },
    )
    assert "Username already exists" in duplicate.text
    assert "Password confirmation does not match" in mismatch.text


def test_disabled_user_cannot_log_in(client):
    user_id = create_user(username="disabled", password="StrongPass123")
    with SessionLocal() as db:
        user = db.get(AdminUser, user_id)
        user.active = False
        db.commit()

    response = login(client, "disabled", "StrongPass123")
    assert response.status_code == 200
    assert "Invalid credentials" in response.text


def test_password_reset_works_and_does_not_expose_hash(admin_client):
    user_id = create_user(username="resetme", password="OldStrong123")
    response = admin_client.post(
        f"/admin/users/{user_id}/reset-password",
        data={"password": "NewStrong123", "confirm_password": "NewStrong123"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    with SessionLocal() as db:
        user = db.get(AdminUser, user_id)
        assert verify_password("NewStrong123", user.password_hash)
        assert db.query(AuditLog).filter_by(action="admin_password_reset").count() == 1
    page = admin_client.get(f"/admin/users/{user_id}/reset-password")
    assert "pbkdf2_sha256" not in page.text


def test_final_super_admin_and_self_disable_are_protected(admin_client):
    with SessionLocal() as db:
        super_admin = db.query(AdminUser).filter_by(username="admin").one()
        user_id = super_admin.id

    demote = admin_client.post(
        f"/admin/users/{user_id}/edit",
        data={"display_name": "Admin", "role": "admin", "active": "1"},
        follow_redirects=False,
    )
    disable = admin_client.post(
        f"/admin/users/{user_id}/edit",
        data={"display_name": "Admin", "role": "super_admin"},
        follow_redirects=False,
    )

    assert demote.status_code == 409
    assert disable.status_code == 409


def test_role_value_is_enforced_server_side(admin_client):
    response = admin_client.post(
        "/admin/users/new",
        data={
            "username": "badrole",
            "display_name": "Bad Role",
            "role": "owner",
            "password": "StrongPass123",
            "confirm_password": "StrongPass123",
            "active": "1",
        },
    )
    assert "Invalid role" in response.text
