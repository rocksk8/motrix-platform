# -*- coding: utf-8 -*-
"""建構器方案 B（掛載頁籤）骨架：宣告驗證、自訂模組 `mount` 驗證、容量、可見性（模組權限 ∧ 點 perm ∧ visibleTo）、404、API 角色矩陣、
G-M1 掃描器（宣告的點必須在頁面畫出 `data-mount-point`，反之亦然）。設計：docs/platform/plans/BUILDER-B-DESIGN.md。
測試用的內建模組／掛載點是假的（registry.loaded 被替換）；真的首批點（daily_tasks）隨前端一起出貨。"""
import copy
import json
import os
import re
from types import SimpleNamespace

import pytest

import db
from core import mounts as MT
from core import customization as CUS
from helpers import custom_modules as CM

HOST = {"key": "mt_host", "name": "宿主", "version": "1.0.0", "pages": [{"path": "host.html"}, {"path": "other.html"}],
        "mount_points": [{"key": "tab-a", "page": "host.html", "kind": "tab", "label": "A 頁籤", "perm": ["case_manage"], "context": ["case_no"]},
                         {"key": "open", "page": "other.html", "kind": "tab", "label": "開放頁籤", "perm": "any"}]}
POINT_A, POINT_OPEN = "mt_host.tab-a", "mt_host.open"


def _loaded(*manifests):
    return [SimpleNamespace(key=m["key"], manifest=m) for m in manifests]


@pytest.fixture
def host(monkeypatch):
    from core import registry
    monkeypatch.setattr(registry, "loaded", lambda: _loaded(HOST))
    return HOST


# ── 宣告驗證 ────────────────────────────────────────────────────────────────

def test_valid_declaration_passes_and_is_collected():
    assert MT.validate_mount_points(HOST) == [] and CUS.validate_manifest(HOST) == []                # 走 loader 同一個出口
    pts = MT.declared_points({"mt_host": HOST})
    assert set(pts) == {POINT_A, POINT_OPEN} and pts[POINT_A]["context"] == ["case_no"] and pts[POINT_OPEN]["context"] == []
    assert MT.validate_mount_points({"key": "x"}) == []                                              # 沒有宣告＝沒問題


@pytest.mark.parametrize("mutate, needle", [
    (lambda m: m["mount_points"][0].pop("label"), "缺 label"),
    (lambda m: m["mount_points"][0].update(extra=1), "不認得的鍵"),
    (lambda m: m["mount_points"][0].update(key="Bad_Key"), "key 必須符合"),
    (lambda m: m["mount_points"][0].update(page="nope.html"), "不在 module.json 的 pages"),
    (lambda m: m["mount_points"][0].update(kind="button"), "kind 目前只有"),
    (lambda m: m["mount_points"][0].update(perm="everyone"), "perm 格式不對"),
    (lambda m: m["mount_points"][0].update(perm=[]), "perm 格式不對"),
    (lambda m: m["mount_points"][0].update(context=["a", "a"]), "不重複"),
    (lambda m: m["mount_points"][1].update(key="tab-a"), "key 重複"),
    (lambda m: m.update(mount_points={"key": "x"}), "必須是清單"),
])
def test_invalid_declarations_are_reported_through_the_loader_gate(mutate, needle):
    m = copy.deepcopy(HOST)
    mutate(m)
    probs = CUS.validate_manifest(m)
    assert any(needle in p["message"] for p in probs), probs
    assert MT.declared_points({"mt_host": m}) == {}                                                  # 不合格的宣告不會被當成存在


def test_every_real_module_manifest_still_validates():
    """正對照＋回歸：所有內建模組的 module.json 照舊合格（新驗證不誤傷）。"""
    from core import source_tree
    root = os.path.join(os.path.dirname(__file__), "..", "modules")
    n = 0
    for d in sorted(os.listdir(root)):
        f = os.path.join(root, d, "module.json")
        if os.path.isfile(f):
            n += 1
            assert CUS.validate_manifest(json.load(open(f, encoding="utf-8"))) == [], d
    assert n >= 5


# ── 自訂模組的 mount 驗證 ──────────────────────────────────────────────────────

def _body(**mount):
    return {"fields": [{"key": "caseNo", "type": "text"}], "mount": mount}


def test_custom_module_mount_validation():
    mf = {"mt_host": HOST}
    assert CM._validate_mount(_body(point=POINT_A, label="請款單", contextField="caseNo"), mf) == []
    assert CM._validate_mount({"fields": []}, mf) == []                                              # 沒有 mount ＝ 獨立模組
    cases = [
        (_body(point="mt_host.nope"), "掛載目標不存在"),
        (_body(point=POINT_A, contextField="ghost"), "必須是本模組的欄位"),
        (_body(point=POINT_OPEN, contextField="caseNo"), "沒有提供上下文"),
        (_body(point=POINT_A, label=""), "頁籤文字"),
        (_body(point=POINT_A, color="red"), "不認得的鍵"),
    ]
    for body, needle in cases:
        assert any(needle in p["message"] for p in CM._validate_mount(body, mf)), (body, needle)
    assert any("不存在或其模組未載入" in p["message"] for p in CM._validate_mount(_body(point=POINT_A), {})), "宿主模組沒載入 ⇒ 明說"
    assert CM._validate_mount({"mount": "x"}, mf)[0]["path"] == "mount"


# ── 資料：發布一個自訂模組（直接寫定義庫）─────────────────────────────────────

def _publish(key, point, label="", visible_to=None, extra_menu=None):
    body = {"name": "自訂%s" % key, "fields": [{"key": "caseNo", "type": "text", "label": "案件"}], "mount": {"point": point, "label": label},
            "menu": ({"visibleTo": visible_to} if visible_to else {})}
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO ui_definitions(kind,key,scope,version,status,body_json) VALUES ('custom_module',?, 'company',1,'published',?)",
                     (key, json.dumps(body, ensure_ascii=False)))
        conn.commit()
    finally:
        conn.close()


def _user(mods, role="engineer", username="u"):
    return {"role": role, "username": username, "modules": json.dumps(mods)}


def test_capacity_check_counts_other_published_modules_only(client):
    for i in range(MT.MAX_TABS_PER_POINT):
        _publish("cap_%d" % i, POINT_OPEN)
    conn = db.get_db()
    try:
        assert CM.mount_cap_problems(conn, "cap_new", {"mount": {"point": POINT_OPEN}})                # 第 9 個 ⇒ 拒絕
        assert not CM.mount_cap_problems(conn, "cap_0", {"mount": {"point": POINT_OPEN}})              # 已經在裡面的不算自己
        assert not CM.mount_cap_problems(conn, "cap_new", {"mount": {"point": POINT_A}})               # 別的點不受影響
        assert not CM.mount_cap_problems(conn, "cap_new", {})                                          # 沒有 mount
    finally:
        conn.close()


def test_visible_mounts_is_module_permission_and_point_permission(client, host):
    _publish("mt_one", POINT_A, label="請款單")
    conn = db.get_db()
    try:
        vm = lambda u, p=POINT_A: CM.visible_mounts(conn, u, p, {"mt_host": HOST})
        sa = vm(_user([], "superadmin"))
        assert [t["key"] for t in sa] == ["mt_one"] and sa[0]["label"] == "請款單" and sa[0]["href"] == "custom-records.html?key=mt_one&embed=1"
        assert [t["key"] for t in vm(_user(["custom.mt_one", "case_manage"]))] == ["mt_one"]            # 兩個權限都有
        assert vm(_user(["custom.mt_one"])) == []                                                      # 只有自訂模組權限、沒過點 perm
        assert vm(_user(["case_manage"])) == []                                                        # 只有點 perm、沒有 custom.<key>
        assert vm(_user([])) == []
        with pytest.raises(CM.MountError) as e:
            vm(_user([], "superadmin"), "mt_host.nope")
        assert e.value.status == 404
        with pytest.raises(CM.MountError):
            CM.visible_mounts(conn, _user([], "superadmin"), POINT_A, {})                             # 宿主沒載入 ⇒ 404，不是空清單
        assert vm(_user([], "superadmin"), POINT_OPEN) == []                                           # 沒人掛 ⇒ 空清單（正對照：404 ≠ 空）
    finally:
        conn.close()


def test_visible_to_role_filter_applies_to_tabs(client, host):
    _publish("mt_role", POINT_OPEN, visible_to={"roles": ["admin"]})
    conn = db.get_db()
    try:
        vm = lambda u: [t["key"] for t in CM.visible_mounts(conn, u, POINT_OPEN, {"mt_host": HOST})]
        assert vm(_user(["custom.mt_role"], "admin")) == ["mt_role"]
        assert vm(_user(["custom.mt_role"], "engineer")) == []                                         # menu.visibleTo 同樣擋
    finally:
        conn.close()


def test_tabs_are_capped_and_sorted(client, host):
    for i in range(MT.MAX_TABS_PER_POINT + 2):
        _publish("srt_%02d" % i, POINT_OPEN, label="L%02d" % (MT.MAX_TABS_PER_POINT + 1 - i))
    conn = db.get_db()
    try:
        tabs = CM.visible_mounts(conn, _user([], "superadmin"), POINT_OPEN, {"mt_host": HOST})
        assert len(tabs) == MT.MAX_TABS_PER_POINT and [t["label"] for t in tabs] == sorted(t["label"] for t in tabs)
    finally:
        conn.close()


# ── API ─────────────────────────────────────────────────────────────────────

def _login(client, u, p):
    r = client.post("/api/auth/login", json={"username": u, "password": p})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def test_api_role_matrix_and_404(client, make_user, host):
    _publish("mt_api", POINT_A, label="API 頁籤")
    h = {n: _login(client, *make_user(username=n, role=r, modules=m)) for n, r, m in (
        ("mb_sa", "superadmin", None), ("mb_both", "engineer", ["custom.mt_api", "case_manage"]),
        ("mb_custom_only", "engineer", ["custom.mt_api"]), ("mb_none", "engineer", []), ("mb_admin", "admin", None))}
    assert client.get("/api/platform/mounts?point=%s" % POINT_A).status_code in (401, 403)             # 未登入
    tabs = lambda who, pt=POINT_A: client.get("/api/platform/mounts?point=%s" % pt, headers=h[who])
    assert [t["key"] for t in tabs("mb_sa").json()["tabs"]] == ["mt_api"]
    assert [t["key"] for t in tabs("mb_both").json()["tabs"]] == ["mt_api"]
    for who in ("mb_custom_only", "mb_none"):
        r = tabs(who)
        assert r.status_code == 200 and r.json()["tabs"] == [], who
    assert tabs("mb_sa", "mt_host.ghost").status_code == 404
    # mount-points：只有最高管理者
    assert client.get("/api/platform/mount-points", headers=h["mb_admin"]).status_code == 403
    r = client.get("/api/platform/mount-points", headers=h["mb_sa"])
    assert r.status_code == 200 and {p["id"] for p in r.json()["points"]} == {POINT_A, POINT_OPEN} and r.json()["maxTabs"] == MT.MAX_TABS_PER_POINT


# ── G-M1：宣告的點必須在頁面畫出來，反之亦然 ─────────────────────────────────────

_MARK = re.compile(r'data-mount-point="([^"]+)"')


def mount_marker_problems(manifests, read_page):
    """{模組key: manifest}、read_page(模組key, 頁名) ⇒ 文字或 None ⇒ 問題清單。"""
    probs, declared = [], MT.declared_points(manifests)
    marked = set()
    for mkey, m in manifests.items():
        for pg in (m.get("pages") or []):
            html = read_page(mkey, pg["path"])
            for pid in _MARK.findall(html or ""):
                marked.add(pid)
                if pid not in declared:
                    probs.append("%s 畫了 data-mount-point=%s 但沒有宣告（建構器看不到）" % (pg["path"], pid))
    for pid, p in declared.items():
        if pid not in marked:
            probs.append("%s 宣告了掛載點但頁面 %s 沒有 data-mount-point（靜默沒有頁籤）" % (pid, p["page"]))
        else:
            html = read_page(p["module"], p["page"]) or ""
            if 'data-mount-point="%s"' % pid not in html:
                probs.append("%s 的標記不在宣告的頁面 %s" % (pid, p["page"]))
    return probs


def test_marker_scanner_finds_known_violations_and_real_tree_is_clean():
    pages = {("mt_host", "host.html"): '<div data-mount-point="mt_host.tab-a"></div>', ("mt_host", "other.html"): "<p>x</p>"}
    rp = lambda k, p: pages.get((k, p))
    assert any("mt_host.open" in x and "沒有 data-mount-point" in x for x in mount_marker_problems({"mt_host": HOST}, rp))     # 正對照：宣告沒畫
    pages[("mt_host", "other.html")] = '<div data-mount-point="mt_host.open"></div><div data-mount-point="mt_host.ghost"></div>'
    probs = mount_marker_problems({"mt_host": HOST}, rp)
    assert any("ghost" in x and "沒有宣告" in x for x in probs) and len(probs) == 1                                         # 畫了沒宣告
    pages[("mt_host", "other.html")] = '<div data-mount-point="mt_host.open"></div>'
    assert mount_marker_problems({"mt_host": HOST}, rp) == []
    # 真實的樹：目前沒有任何模組宣告掛載點 ⇒ 沒有問題；之後宣告了就必須同時畫
    root = os.path.join(os.path.dirname(__file__), "..", "..")
    mans = {}
    for d in sorted(os.listdir(os.path.join(root, "backend", "modules"))):
        f = os.path.join(root, "backend", "modules", d, "module.json")
        if os.path.isfile(f):
            mans[d] = json.load(open(f, encoding="utf-8"))

    def real(mkey, page):
        f = os.path.join(root, "frontend", "pages", page)
        return open(f, encoding="utf-8").read() if os.path.isfile(f) else None
    assert mount_marker_problems(mans, real) == []
