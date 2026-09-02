def test_admin_operations_page_exposes_non_secret_readiness(admin_client):
    response = admin_client.get("/admin/operations")

    assert response.status_code == 200
    assert "Operational Readiness" in response.text
    assert "Photos are stored on the local application filesystem" in response.text
    assert "passwords, API keys, or contact details" in response.text
