"""T86 U9：自訂模組預覽 422 的訊息要說明「哪裡不對、怎麼改」（狀態碼與規則不變；既有題照舊）。"""
import pytest


def _hdr(client, make_user, name):
    u, p = make_user(username=name, role="superadmin")
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


@pytest.mark.parametrize("numbering,must", [
    ({"prefix": "", "date": "", "digits": 4}, ("大寫英文字母", "EL")),
    ({"prefix": "ab", "date": "", "digits": 4}, ("大寫英文字母", "EL")),
    ({"prefix": "EL", "date": "YYYY", "digits": 4}, ("年月日", "年月")),
    ({"prefix": "EL", "date": "", "digits": 2}, ("3～8", "0001")),
    ({"prefix": "EL", "date": "", "digits": "x"}, ("3～8", "0001")),
])
def test_numbering_preview_422_says_what_and_how(client, make_user, numbering, must):
    h = _hdr(client, make_user, "cmp_n")
    r = client.post("/api/custom-modules/numbering/preview", headers=h, json={"numbering": numbering})
    assert r.status_code == 422, r.text
    msg = " ".join(p["message"] for p in r.json()["problems"])
    for m in must:
        assert m in msg, (m, msg)


@pytest.mark.parametrize("body,must", [
    ({"name": "x", "fields": []}, ("尚無可以預覽的欄位", "新增")),
    ({"name": "x"}, ("尚無可以預覽的欄位", "新增")),
    ({"name": "x", "fields": [{"label": "甲"}]}, ("尚未完成",)),
])
def test_output_preview_422_says_what_and_how(client, make_user, body, must):
    h = _hdr(client, make_user, "cmp_o")
    r = client.post("/api/custom-modules/pv_msg/output/preview", headers=h, json={"body": body})
    assert r.status_code == 422, r.text
    text = r.json()["detail"] + " " + " ".join(p["message"] for p in r.json()["problems"])
    for m in must:
        assert m in text, (m, text)
