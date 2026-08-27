
def create_event(admin_client):
    response = admin_client.post(
        "/admin/events",
        data={
            "code": "RF",
            "name": "Rasuwa Flood",
            "disaster_type": "flood",
            "start_date": "2026-08-26",
            "affected_locations": "Rasuwa\nTimure\nRasuwagadhi",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303


def test_public_report_admin_approval_publish_search_and_export(admin_client):
    create_event(admin_client)

    page = admin_client.get("/report")
    assert "Rasuwa Flood" in page.text

    response = admin_client.post(
        "/report",
        data={
            "disaster_id": "1",
            "name": "Anushka Pandey",
            "name_ne": "अनुष्का पाण्डे",
            "age": "32",
            "gender": "Female",
            "last_seen_date": "2026-08-26",
            "last_seen_location": "Timure, Rasuwa",
            "clothing": "Red jacket, black trousers",
            "public_contact_number": "9812345678",
            "social_url": "https://facebook.com/groups/example/posts/123?utm_source=test",
            "reporter_name": "Family Member",
            "reporter_phone": "9800000000",
        },
    )
    assert response.status_code == 200
    assert "Report received" in response.text

    pending = admin_client.get("/admin/submissions")
    assert "Anushka Pandey" in pending.text

    approved = admin_client.post("/admin/submissions/1/approve-new", follow_redirects=False)
    assert approved.status_code == 303
    assert approved.headers["location"].startswith("/admin/people/")

    person_id = int(approved.headers["location"].rsplit("/", 1)[-1])
    admin_client.post(f"/admin/people/{person_id}/publish")

    public = admin_client.get("/?q=Anushka")
    assert "NP-2026-RF-00001" in public.text
    assert "Anushka Pandey" in public.text

    detail = admin_client.get("/person/NP-2026-RF-00001")
    assert "Original source" in detail.text
    assert "facebook.com/groups/example/posts/123" in detail.text
    assert "9800000000" not in detail.text

    export = admin_client.get("/admin/export/xlsx?disaster_id=1")
    assert export.status_code == 200
    assert export.headers["content-type"].startswith("application/vnd.openxmlformats")
    assert len(export.content) > 1000


def test_export_requires_admin(client):
    response = client.get("/admin/export/xlsx?disaster_id=1", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_public_cannot_submit_to_inactive_event(admin_client):
    create_event(admin_client)
    admin_client.post(
        "/admin/events/1/update",
        data={
            "name": "Rasuwa Flood",
            "disaster_type": "flood",
            "affected_locations": "Rasuwa\nTimure",
            # active checkbox intentionally omitted
        },
    )
    response = admin_client.post(
        "/report",
        data={
            "disaster_id": "1",
            "name": "Test Person",
            "last_seen_location": "Timure",
        },
    )
    assert response.status_code == 200
    assert "Please select an active disaster" in response.text


def test_submission_cannot_attach_across_disasters(admin_client):
    create_event(admin_client)
    admin_client.post(
        "/admin/events",
        data={
            "code": "KF",
            "name": "Koshi Flood",
            "disaster_type": "flood",
            "start_date": "2026-08-27",
            "affected_locations": "Koshi",
        },
    )

    # Create a person under the second disaster through a submission.
    admin_client.post(
        "/report",
        data={
            "disaster_id": "2",
            "name": "Second Event Person",
            "last_seen_location": "Koshi",
        },
    )
    approved = admin_client.post("/admin/submissions/1/approve-new", follow_redirects=False)
    second_person_id = int(approved.headers["location"].rsplit("/", 1)[-1])

    # Create a pending submission under the first disaster, then try to attach it across events.
    admin_client.post(
        "/report",
        data={
            "disaster_id": "1",
            "name": "Rasuwa Person",
            "last_seen_location": "Timure",
        },
    )
    response = admin_client.post(
        "/admin/submissions/2/attach",
        data={"person_id": str(second_person_id)},
        follow_redirects=False,
    )
    assert response.status_code == 400
    assert "different disaster" in response.text


def test_one_discovery_source_can_create_multiple_person_submissions(admin_client):
    create_event(admin_client)
    response = admin_client.post(
        "/admin/discovery/manual",
        data={
            "disaster_id": "1",
            "platform": "facebook",
            "url": "https://facebook.com/groups/example/posts/multiple",
            "title": "Two people missing",
            "snippet": "Two people are reported missing from Timure",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303

    first = admin_client.post(
        "/admin/discovery/1/submission",
        data={"name": "Person One", "last_seen_location": "Timure"},
        follow_redirects=False,
    )
    second = admin_client.post(
        "/admin/discovery/1/submission",
        data={"name": "Person Two", "last_seen_location": "Timure"},
        follow_redirects=False,
    )
    assert first.status_code == 303
    assert second.status_code == 303

    page = admin_client.get("/admin/submissions")
    assert "Person One" in page.text
    assert "Person Two" in page.text
    assert page.text.count("facebook.com/groups/example/posts/multiple") >= 2


def test_pending_submission_photo_is_not_public_but_is_admin_visible(admin_client):
    from io import BytesIO
    from PIL import Image

    create_event(admin_client)
    image_bytes = BytesIO()
    Image.new("RGB", (20, 20), "white").save(image_bytes, format="JPEG")
    image_bytes.seek(0)

    response = admin_client.post(
        "/report",
        data={
            "disaster_id": "1",
            "name": "Photo Person",
            "last_seen_location": "Timure",
        },
        files={"photo": ("person.jpg", image_bytes.getvalue(), "image/jpeg")},
    )
    assert response.status_code == 200

    # There is no raw public uploads route anymore.
    assert admin_client.get("/uploads/not-a-real-file.jpg").status_code == 404
    # Unpublished case does not yet exist and therefore has no public media URL.
    assert admin_client.get("/media/person/NP-2026-RF-00001").status_code == 404

    pending = admin_client.get("/admin/submissions")
    assert "/admin/media/" in pending.text

    approved = admin_client.post("/admin/submissions/1/approve-new", follow_redirects=False)
    person_id = int(approved.headers["location"].rsplit("/", 1)[-1])
    # Still private until publication.
    assert admin_client.get("/media/person/NP-2026-RF-00001").status_code == 404
    admin_client.post(f"/admin/people/{person_id}/publish")
    public_photo = admin_client.get("/media/person/NP-2026-RF-00001")
    assert public_photo.status_code == 200
    assert public_photo.headers["content-type"].startswith("image/")
