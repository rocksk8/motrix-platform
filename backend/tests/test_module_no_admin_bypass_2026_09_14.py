"""取消 admin 直通：模組權限對管理員也生效（2026-09-14 使用者裁示）。

「管理者一樣依據有開權限的內容去顯示，沒開的就不顯示，包含模組名稱。
超級管理者預設全開，使用者部分看模組內容去檢核，未開啟的直接不顯示」。

在此之前 `require_any_module()` 對 `admin` 與 `superadmin` 一律直通，所以：
  ・使用者管理裡的模組勾選對 admin **完全沒有作用**（勾掉照樣進得去）
  ・沒有人發現既有 admin 帳號的模組清單早就過時了——2026-08／09 新增的模組
    加進了角色樣板，既有帳號卻從來沒回填，只因為直通所以看不出來

這裡的觀測點一律是「實際打 API 的回應碼與內容」，不是讀回設定值。
"""
import json

import pytest


def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


# 拿來當探針的端點：各自只認一個明確的模組，且都是純讀取（不會改到資料）
_PROBES = [
    ("/api/parts", "procurement", "料號主檔"),
    ("/api/audit-log", "audit_log", "歷史紀錄"),
    ("/api/module-versions", "module_versions", "版本紀錄"),
    ("/api/shipping-notes/export-history", "shipping_export_log", "出貨單歷史紀錄"),
]
# 模組的端點由模組自己的測試帶進同一組檢查（例：modules/netplan/tests/test_netplan_moved_guards.py），
# 拿掉那個模組時探針跟著消失（PLAYBOOK §B-11）。


@pytest.mark.parametrize("path,module,label", _PROBES)
def test_admin_without_module_is_blocked(client, make_user, path, module, label):
    """這是整批改動的核心斷言：**admin 沒有那個模組就是進不去**。

    改動前這幾支對 admin 全部回 200——模組勾選對管理員形同虛設。
    """
    u, p = make_user(username=f"adm_{module}", role="admin", modules=[])
    r = client.get(path, headers=_login(client, u, p))
    assert r.status_code == 403, f"{label}：admin 沒有 {module} 模組卻仍然進得去（{r.status_code}）"


@pytest.mark.parametrize("path,module,label", _PROBES)
def test_admin_with_module_passes(client, make_user, path, module, label):
    """反向控制。少了這一題，上面那批可以靠「admin 一律 403」變綠——
    而那會是比原本更糟的狀態（擋錯人，見 MODULE-AUDIT §5）。"""
    u, p = make_user(username=f"adm_ok_{module}", role="admin", modules=[module])
    r = client.get(path, headers=_login(client, u, p))
    assert r.status_code == 200, f"{label}：admin 有 {module} 模組卻被擋（{r.status_code}）{r.text[:200]}"


@pytest.mark.parametrize("path,module,label", _PROBES)
def test_superadmin_always_passes(client, make_user, path, module, label):
    """「超級管理者預設全開」——一個模組都沒勾也照樣全通。"""
    u, p = make_user(username=f"sa_{module}", role="superadmin", modules=[])
    r = client.get(path, headers=_login(client, u, p))
    assert r.status_code == 200, f"{label}：superadmin 被擋了（{r.status_code}）"


def test_module_revocation_actually_takes_effect(client, make_user):
    """把模組拿掉之後**當下就擋得住**，不是等下次登入才生效。

    這一題才是使用者真正要的東西：勾選框要有作用。權限讀的是 users 表
    當下的值（`_require_user()` 每次請求都重查），不是登入時快照進 session 的。
    """
    from db import get_db

    u, p = make_user(username="revoke_me", role="admin", modules=["procurement"])
    headers = _login(client, u, p)
    assert client.get("/api/parts", headers=headers).status_code == 200

    conn = get_db()
    conn.execute("UPDATE users SET modules=? WHERE username=?",
                 (json.dumps([]), "revoke_me"))
    conn.commit()
    conn.close()

    assert client.get("/api/parts", headers=headers).status_code == 403, \
        "取消勾選後仍然進得去——那就還是『顯示偏好』不是權限"


def test_error_message_names_the_missing_module(client, make_user):
    """403 要講得出缺哪個模組，否則管理員無從判斷該去勾什麼。"""
    u, p = make_user(username="nomod", role="admin", modules=[])
    r = client.get("/api/parts", headers=_login(client, u, p))
    assert r.status_code == 403
    detail = r.json()["detail"]
    # 訊息用的是**權限目錄上的標籤**（「供應商／料號／採購」），不是端點名稱
    # ——管理員要去 users.html 勾的就是那一列，兩邊講同一個詞才找得到。
    assert "模組" in detail and "採購" in detail, detail


# ── 新建的模組 key（使用者：「沒有對應模組 key 也建立就沒有這個問題」）────────

def test_newly_created_keys_are_grantable_in_the_catalogue():
    """新 key 必須出現在 users.html 的權限目錄裡，否則永遠沒人勾得到
    ——那正是 `project_manage` 當初踩過的坑（後端在擋、畫面上勾不到）。"""
    import io
    import os
    import re

    # 2026-09-24（B7）：權限目錄的唯一來源是 helpers/module_registry.py
    #   （users.html 由 /api/modules/catalog 取得同一份）。斷言不變。
    from helpers.module_registry import MODULE_KEYS as catalogue

    for k in ("netplan", "audit_log", "shipping_export_log",
              "module_versions"):
        assert k in catalogue, f"{k} 後端會擋，但權限目錄裡勾不到"


# test_network_plan_read_accepts_case_manage_consumer （2026-09-26 移到 modules/netplan/tests/test_netplan_moved_guards.py：拿掉 netplan 時那一項跟著消失，PLAYBOOK §B-11）
