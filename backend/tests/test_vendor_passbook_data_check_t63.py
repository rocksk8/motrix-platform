"""T63：承攬商 POST/PUT 的 data.bankPassbookImage 只准 data:image/（與 /passbook 端點同一規則），其餘 400。"""
import pytest

PB = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGA"


@pytest.fixture()
def h(client, make_user):
    u, pw = make_user(username="t63_sa", role="superadmin")[:2]
    r = client.post("/api/auth/login", json={"username": u, "password": pw})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("bad", ["file:///C:/Windows/win.ini", "http://127.0.0.1/x.png", "uploads/a.png", 123])
def test_create_rejects_non_data_image(client, h, bad):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "V-bad", "data": {"bankPassbookImage": bad}})
    assert r.status_code == 400, r.text


def test_update_rejects_and_accepts(client, h):
    r = client.post("/api/vendor-contractors", headers=h, json={"name": "V-ok", "data": {"bankPassbookImage": PB}})
    assert r.status_code == 201, r.text
    vid = r.json()["id"]
    assert client.put("/api/vendor-contractors/%d" % vid, headers=h,
                      json={"name": "V-ok", "data": {"bankPassbookImage": "file:///C:/x.png"}}).status_code == 400
    assert client.put("/api/vendor-contractors/%d" % vid, headers=h,
                      json={"name": "V-ok", "data": {"bankPassbookImage": PB}}).status_code == 200
    assert client.put("/api/vendor-contractors/%d" % vid, headers=h, json={"name": "V-ok", "data": {}}).status_code == 200   # 不帶 ⇒ 保留既有
