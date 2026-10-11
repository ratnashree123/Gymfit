from app.services import photo_service

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 200
JPG = b"\xff\xd8\xff\xe0" + b"1" * 200


def upload(client, headers, member_id, data=PNG, name="me.png", content_type="image/png"):
    return client.post(f"/api/members/{member_id}/photo", headers=headers,
                       files={"file": (name, data, content_type)})


def test_upload_and_download_photo(client, admin_headers, make_member):
    member = make_member()
    response = upload(client, admin_headers, member["id"])
    assert response.status_code == 200
    body = response.json()
    assert body["has_photo"] is True and body["photo_url"] == f"/api/members/{member['id']}/photo"

    download = client.get(body["photo_url"], headers=admin_headers)
    assert download.status_code == 200
    assert download.content == PNG
    assert download.headers["content-type"] == "image/png"
    assert download.headers["x-content-type-options"] == "nosniff"


def test_photo_download_requires_login(client, admin_headers, make_member):
    member = make_member()
    upload(client, admin_headers, member["id"])
    assert client.get(f"/api/members/{member['id']}/photo").status_code == 401


def test_fake_images_are_rejected_even_with_an_image_name(client, admin_headers, make_member):
    member = make_member()
    for data, name, ctype in [
        (b"MZ this is a program", "photo.png", "image/png"),
        (b"<svg onload=alert(1)></svg>", "photo.svg", "image/svg+xml"),
        (b"just text", "photo.jpg", "image/jpeg"),
    ]:
        assert upload(client, admin_headers, member["id"], data, name, ctype).status_code == 400
    assert client.get(f"/api/members/{member['id']}", headers=admin_headers).json()["has_photo"] is False


def test_oversized_photo_is_rejected(client, admin_headers, make_member):
    member = make_member()
    too_big = PNG + b"0" * (2 * 1024 * 1024)
    assert upload(client, admin_headers, member["id"], too_big).status_code == 413


def test_replacing_a_photo_deletes_the_old_file(client, admin_headers, make_member):
    member = make_member()
    upload(client, admin_headers, member["id"], PNG)
    assert len(list(photo_service.UPLOAD_ROOT.iterdir())) == 1
    upload(client, admin_headers, member["id"], JPG, "me.jpg", "image/jpeg")
    files = list(photo_service.UPLOAD_ROOT.iterdir())
    assert len(files) == 1 and files[0].suffix == ".jpg"
    assert files[0].name.startswith(member["member_code"])  # our own name, never the uploaded file name


def test_delete_photo(client, admin_headers, make_member):
    member = make_member()
    assert client.delete(f"/api/members/{member['id']}/photo", headers=admin_headers).status_code == 404
    upload(client, admin_headers, member["id"])
    response = client.delete(f"/api/members/{member['id']}/photo", headers=admin_headers)
    assert response.status_code == 200 and response.json()["has_photo"] is False
    assert list(photo_service.UPLOAD_ROOT.iterdir()) == []
    assert client.get(f"/api/members/{member['id']}/photo", headers=admin_headers).status_code == 404


def test_trainer_cannot_upload_or_see_unassigned_photos(client, admin_headers, trainer, make_member):
    trainer_id, trainer_headers = trainer
    mine = make_member(assigned_trainer_id=trainer_id)
    other = make_member()
    upload(client, admin_headers, mine["id"])
    upload(client, admin_headers, other["id"])

    assert upload(client, trainer_headers, mine["id"]).status_code == 403
    assert client.get(f"/api/members/{mine['id']}/photo", headers=trainer_headers).status_code == 200
    assert client.get(f"/api/members/{other['id']}/photo", headers=trainer_headers).status_code == 404


def test_photo_for_unknown_member_is_404(client, admin_headers):
    assert upload(client, admin_headers, 9999).status_code == 404
