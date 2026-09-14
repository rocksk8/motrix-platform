"""2026-08-28（模組逐步檢查：業務開發）：軟刪除（is_deleted=1，需 superadmin 核准
才會真正發生）後的專案，get_dev_case()/update_dev_case()/update_dev_case_status()/
mark_converted()/create_dev_log() 五個端點原本都沒有檢查 is_deleted，代表知道/猜到
case_id 的人可以繼續查看/編輯/轉建報價單/新增記錄到一個「已核准刪除」的專案上，
完全不會出現在任何列表裡（list_dev_cases() 本來就有 is_deleted=0 過濾），屬靜默發生。
"""
import json


def _login(client, username, password):
    r = client.post("/api/auth/login", json={"username": username, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def _create_and_soft_delete_case(client, admin_token, superadmin_token):
    r = client.post(
        "/api/dev-cases", headers=_auth(admin_token),
        json={"case_name": "待軟刪測試案件", "customer_name": "", "status": "洽談中"},
    )
    assert r.status_code == 201, r.text
    case_id = r.json()["id"]

    r = client.post(f"/api/dev-cases/{case_id}/request-delete", headers=_auth(admin_token),
                     json={"reason": "測試"})
    assert r.status_code == 200, r.text

    r = client.post(f"/api/dev-cases/{case_id}/approve-delete", headers=_auth(superadmin_token),
                     json={"approve": True})
    assert r.status_code == 200, r.text
    assert r.json()["deleted"] is True
    return case_id


def test_get_soft_deleted_case_404s(client, make_user):
    admin, admin_pw = make_user(username="dcd_admin1", role="admin")
    su, su_pw = make_user(username="dcd_su1", role="superadmin")
    admin_token = _login(client, admin, admin_pw)
    su_token = _login(client, su, su_pw)
    case_id = _create_and_soft_delete_case(client, admin_token, su_token)

    r = client.get(f"/api/dev-cases/{case_id}", headers=_auth(admin_token))
    assert r.status_code == 404, r.text


def test_update_soft_deleted_case_404s(client, make_user):
    admin, admin_pw = make_user(username="dcd_admin2", role="admin")
    su, su_pw = make_user(username="dcd_su2", role="superadmin")
    admin_token = _login(client, admin, admin_pw)
    su_token = _login(client, su, su_pw)
    case_id = _create_and_soft_delete_case(client, admin_token, su_token)

    r = client.put(f"/api/dev-cases/{case_id}", headers=_auth(admin_token),
                    json={"case_name": "偷改", "customer_name": "", "status": "洽談中"})
    assert r.status_code == 404, r.text


def test_update_status_soft_deleted_case_404s(client, make_user):
    admin, admin_pw = make_user(username="dcd_admin3", role="admin")
    su, su_pw = make_user(username="dcd_su3", role="superadmin")
    admin_token = _login(client, admin, admin_pw)
    su_token = _login(client, su, su_pw)
    case_id = _create_and_soft_delete_case(client, admin_token, su_token)

    r = client.patch(f"/api/dev-cases/{case_id}/status", headers=_auth(admin_token),
                      json={"status": "成案"})
    assert r.status_code == 404, r.text


def test_convert_soft_deleted_case_404s(client, make_user):
    admin, admin_pw = make_user(username="dcd_admin4", role="admin")
    su, su_pw = make_user(username="dcd_su4", role="superadmin")
    admin_token = _login(client, admin, admin_pw)
    su_token = _login(client, su, su_pw)
    case_id = _create_and_soft_delete_case(client, admin_token, su_token)

    r = client.patch(f"/api/dev-cases/{case_id}/convert", headers=_auth(admin_token),
                      json={"quote_no": "MQ-DOES-NOT-MATTER"})
    assert r.status_code == 404, r.text


def test_create_log_on_soft_deleted_case_404s(client, make_user):
    admin, admin_pw = make_user(username="dcd_admin5", role="admin")
    su, su_pw = make_user(username="dcd_su5", role="superadmin")
    admin_token = _login(client, admin, admin_pw)
    su_token = _login(client, su, su_pw)
    case_id = _create_and_soft_delete_case(client, admin_token, su_token)

    # 2026-09-14：這支端點改收 multipart（開發記錄可附照片／檔案，DB v82），
    # 所以是 data= 而不是 json=。欄位名與型別跟原本的 JSON body 一字不差。
    r = client.post(f"/api/dev-cases/{case_id}/logs", headers=_auth(admin_token),
                     data={"log_date": "2026-08-28", "log_by": 1, "channel": "電話",
                           "content": "偷加記錄"})
    assert r.status_code == 404, r.text
