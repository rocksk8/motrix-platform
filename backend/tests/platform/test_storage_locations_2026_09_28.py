# -*- coding: utf-8 -*-
"""儲存位置可設定（CORE-SPEC 裁示表「儲存位置可設定」；A，2026-09-28）。

- 解析：有設定用設定（不存在 ⇒ 雲端存檔根目錄回 ""、不退回自動）；留空照原本的自動判斷（個資＝根目錄旁）。
- 驗證：絕對路徑、存在、可寫；個資與雲端存檔根目錄／更新交付資料夾不可互相包含或相同；不過就不存（DB 不變）。
- 建立：只由最高管理員的明確動作；只建最後一層；背景程式永不自動建（寫個資時資料夾不在 ⇒ 失敗，不建回來）。
- 守門：讀這三個位置的程式一律經 helpers.storage_locations（掃描＋正對照＋反向控制）。
全部用 tmp 目錄；不碰真實雲端資料夾。
"""
import ast
import json
import os
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"


@pytest.fixture(autouse=True)
def _fresh_cache():
    from helpers import storage_locations as SL
    SL.invalidate()
    yield
    SL.invalidate()


def _set(values):
    from helpers import storage_locations as SL
    SL.save({k: values.get(k, "") for k in SL.KINDS})


# ── 解析 ─────────────────────────────────────────────────────────────────────

def test_empty_settings_keep_the_old_automatic_behaviour(tmp_path, monkeypatch):
    """不帶 client：client 夾具會把 archive._archive_base 換成 tmp（conftest 雲端隔離），這裡要驗的正是它本身。
    沒有庫／沒有設定 ⇒ 全部自動。"""
    import archive
    from helpers import storage_locations as SL
    auto = tmp_path / "我的雲端硬碟" / "系統存檔"
    auto.mkdir(parents=True)
    monkeypatch.setattr(archive, "_auto_archive_base", lambda: str(auto))
    assert SL.resolve("archive_root") == {"path": str(auto), "source": "auto"}
    # 個資留空 ⇒ 「目前生效的雲端存檔根目錄」旁邊。測試環境的 archive._archive_base 被 conftest 換成 tmp（session 層級，
    # 雲端隔離），所以這裡斷言的是「跟著 archive._archive_base 走」這個相容行為本身；委派關係見讀碼那一題。
    assert archive._pii_archive_root() == os.path.join(os.path.dirname(archive._archive_base()), SL.PII_DIRNAME)
    assert SL.resolve("delivery_root") == {"path": "", "source": "unset"}


def test_settings_win_and_a_missing_setting_does_not_fall_back(client, tmp_path, monkeypatch):
    """設了卻不存在 ⇒ 雲端存檔根目錄回 ""（找不到、告警），**不**退回自動判斷寫到別處。"""
    import archive
    from helpers import storage_locations as SL
    auto = tmp_path / "auto"
    auto.mkdir()
    monkeypatch.setattr(archive, "_auto_archive_base", lambda: str(auto))
    root, pii, dl = tmp_path / "root", tmp_path / "pii", tmp_path / "交付"
    for p in (root, pii, dl):
        p.mkdir()
    _set({"archive_root": str(root), "pii_root": str(pii), "delivery_root": str(dl)})
    # client 夾具把 archive._archive_base 換成 tmp ⇒ 這裡直接驗解析函式（archive 委派給它，見下一題）
    assert SL.path("archive_root") == str(root) and archive._pii_archive_root() == str(pii)
    assert SL.path("delivery_root") == str(dl)
    root.rmdir()
    SL.invalidate()
    assert SL.path("archive_root") == "", "設定的位置不見了 ⇒ 回空，不改寫到自動判斷的位置"


def test_archive_delegates_both_locations_to_the_resolver():
    """讀碼：archive._archive_base／_pii_archive_root 的本體就是 storage_locations.path（沒有另外的判斷）。"""
    import inspect
    import archive
    for fn, kind in ((archive.__dict__.get("_pii_archive_root"), "pii_root"),):
        assert 'return _storage.path("%s")' % kind in inspect.getsource(fn)
    src = inspect.getsource(archive)
    head = src[src.index("def _archive_base()"):src.index("def _auto_archive_base()")]
    assert 'return _storage.path("archive_root")' in head, head


def test_settings_are_read_from_the_main_db_even_in_demo_mode(client, tmp_path, monkeypatch):
    """儲存位置是機器設定：demo 模式的請求（get_db 會導到 demo 庫）也讀主庫那一份。"""
    import db
    from helpers import storage_locations as SL
    dl = tmp_path / "交付"
    dl.mkdir()
    _set({"delivery_root": str(dl)})
    token = db._demo_mode.set(True)
    try:
        SL.invalidate()
        assert SL.path("delivery_root") == str(dl)
    finally:
        db._demo_mode.reset(token)


# ── 驗證 ─────────────────────────────────────────────────────────────────────

def _problems(values):
    from helpers import storage_locations as SL
    return [(p["kind"], p["message"]) for p in SL.validate(values)]


def test_validation_accepts_good_separate_folders(tmp_path):
    root, pii, dl = tmp_path / "系統存檔", tmp_path / "系統存檔_個資", tmp_path / "MOTRIX-交付"
    for p in (root, pii, dl):
        p.mkdir()
    assert _problems({"archive_root": str(root), "pii_root": str(pii), "delivery_root": str(dl)}) == []
    assert _problems({"archive_root": "", "pii_root": "", "delivery_root": ""}) == []


@pytest.mark.parametrize("case", ["relative", "missing", "pii_in_archive", "archive_in_pii", "pii_equals_delivery",
                                  "auto_pii_in_delivery", "not_writable"])
def test_rc_bad_values_are_rejected_with_the_reason(tmp_path, monkeypatch, case):
    from helpers import storage_locations as SL
    root = tmp_path / "系統存檔"
    root.mkdir()
    v = {"archive_root": str(root), "pii_root": "", "delivery_root": ""}
    if case == "relative":
        v["delivery_root"], kind, needle = "交付", "delivery_root", "完整路徑"
    elif case == "missing":
        v["delivery_root"], kind, needle = str(tmp_path / "沒有"), "delivery_root", "不存在"
    elif case == "pii_in_archive":
        (root / "個資").mkdir()
        v["pii_root"], kind, needle = str(root / "個資"), "pii_root", "互相包含"
    elif case == "archive_in_pii":
        (tmp_path / "p").mkdir()
        (tmp_path / "p" / "a").mkdir()
        v.update(archive_root=str(tmp_path / "p" / "a"), pii_root=str(tmp_path / "p"))
        kind, needle = "pii_root", "互相包含"
    elif case == "pii_equals_delivery":
        (tmp_path / "same").mkdir()
        v.update(pii_root=str(tmp_path / "same"), delivery_root=str(tmp_path / "same"))
        kind, needle = "pii_root", "互相包含"
    elif case == "auto_pii_in_delivery":
        # 個資留空 ⇒ 自動算出「根目錄旁的系統存檔_個資」；交付資料夾包住它 ⇒ 也要擋
        (tmp_path / SL.PII_DIRNAME).mkdir()
        v["delivery_root"], kind, needle = str(tmp_path), "pii_root", "互相包含"
    else:
        monkeypatch.setattr(SL, "_writable", lambda p: False)
        v["delivery_root"] = str(root)
        kind, needle = "archive_root", "無法寫入"
    got = _problems(v)
    assert any(k == kind and needle in m for k, m in got), got


def test_writable_probe_leaves_nothing_behind(tmp_path):
    from helpers import storage_locations as SL
    assert SL._writable(str(tmp_path)) is True and list(tmp_path.iterdir()) == []


# ── 建立（只由最高管理員明確動作；只建最後一層）────────────────────────────────

def test_create_makes_only_the_last_level(tmp_path):
    from helpers import storage_locations as SL
    made = SL.create("pii_root", str(tmp_path / "系統存檔_個資"))
    assert os.path.isdir(made)
    for bad, needle in ((str(tmp_path / "a" / "b"), "上一層"), (made, "已經存在"), ("相對", "完整路徑")):
        with pytest.raises(ValueError, match=needle):
            SL.create("pii_root", bad)
    assert not (tmp_path / "a").exists()


def test_background_code_never_creates_a_configured_pii_folder(client, tmp_path):
    """設定的個資資料夾不存在 ⇒ 寫個資時失敗（PiiFolderMissing），資料夾不會被建回來。"""
    import archive
    pii = tmp_path / "系統存檔_個資"
    _set({"pii_root": str(pii)})
    with pytest.raises(archive.PiiFolderMissing):
        archive._pii_ensure_dir(str(pii / "每日備份" / "2026-09-28"))
    assert not pii.exists()


# ── API ──────────────────────────────────────────────────────────────────────

def _h(client, user):
    r = client.post("/api/auth/login", json={"username": user[0], "password": user[1]})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["token"]}


def _stored():
    import db
    conn = db.get_db()
    try:
        row = conn.execute("SELECT value_json FROM system_settings WHERE key='storage_locations'").fetchone()
        return json.loads(row[0]) if row else None
    finally:
        conn.close()


def _audits(action):
    import db
    conn = db.get_db()
    try:
        return [r[0] for r in conn.execute("SELECT target_label FROM audit_log WHERE action=?", (action,)).fetchall()]
    finally:
        conn.close()


def test_api_only_superadmin(client, make_user):
    h = _h(client, make_user(username="st_admin", role="admin"))
    assert client.get("/api/settings/storage-locations", headers=h).status_code == 403
    assert client.put("/api/settings/storage-locations", headers=h,
                      json={"archive_root": "", "pii_root": "", "delivery_root": ""}).status_code == 403
    assert client.post("/api/settings/storage-locations/create", headers=h, json={"kind": "pii_root", "path": "x"}).status_code == 403


def test_api_save_validates_and_audits(client, make_user, tmp_path):
    h = _h(client, make_user(username="st_sa", role="superadmin"))
    missing = str(tmp_path / "MOTRIX-交付")
    r = client.put("/api/settings/storage-locations", headers=h, json={"archive_root": "", "pii_root": "", "delivery_root": missing})
    assert r.status_code == 400 and r.json()["detail"]["problems"][0]["kind"] == "delivery_root", r.text
    assert _stored() is None, "沒通過就不存"
    r = client.post("/api/settings/storage-locations/create", headers=h, json={"kind": "delivery_root", "path": missing})
    assert r.status_code == 200 and os.path.isdir(missing) and "共用權限" in r.json()["notice"], r.text
    assert any(missing in d for d in _audits("settings.storage_locations.create"))
    r = client.put("/api/settings/storage-locations", headers=h, json={"archive_root": "", "pii_root": "", "delivery_root": missing})
    assert r.status_code == 200, r.text
    assert _stored() == {"archive_root": "", "pii_root": "", "delivery_root": missing}
    assert any("更新交付資料夾" in d for d in _audits("settings.storage_locations.update"))
    from helpers import storage_locations as SL
    assert SL.path("delivery_root") == missing, "存檔後立刻生效（快取已清）"
    got = client.get("/api/settings/storage-locations", headers=h).json()
    assert got["status"]["delivery_root"]["exists"] is True and got["status"]["delivery_root"]["source"] == "setting"


def test_rc_api_rejects_extra_or_missing_fields(client, make_user):
    """寬鬆驗證會靜默丟欄位：多送、少送都 422。"""
    h = _h(client, make_user(username="st_sa2", role="superadmin"))
    assert client.put("/api/settings/storage-locations", headers=h,
                      json={"archive_root": "", "pii_root": ""}).status_code == 422
    assert client.put("/api/settings/storage-locations", headers=h,
                      json={"archive_root": "", "pii_root": "", "delivery_root": "", "uploads_root": ""}).status_code == 422


# ── 守門：讀這三個位置只經 helpers.storage_locations ─────────────────────────────

#: 例外（附理由）：只是訊息文字、不是讀位置
ALLOWED_LITERAL = {
    "backend/tools/deploy_insights.py": "部署前檢查的警告文字（「正式機看不到『系統存檔_個資』資料夾」），不讀位置",
}
_AUTO_NAMES = {"_auto_archive_base", "_detect_archive_base"}
_AUTO_OWNERS = {"backend/archive.py", "backend/helpers/storage_locations.py"}
_KEY_OWNER = "backend/helpers/storage_locations.py"


def _docstring_nodes(tree):
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(getattr(first, "value", None), ast.Constant):
                out.add(id(first.value))
    return out


def violations(sources):
    """{相對路徑: 原始碼} ⇒ [(路徑, 行, 說明)]。註解與 docstring 不算。"""
    bad = []
    for rel, src in sources.items():
        try:
            tree = ast.parse(src)
        except SyntaxError:
            continue
        docs = _docstring_nodes(tree)
        for n in ast.walk(tree):
            name = n.id if isinstance(n, ast.Name) else (n.attr if isinstance(n, ast.Attribute) else None)
            if name in _AUTO_NAMES and rel not in _AUTO_OWNERS:
                bad.append((rel, n.lineno, "直接用自動判斷 %s（要經 storage_locations.resolve）" % name))
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs:
                if n.value == "storage_locations" and rel != _KEY_OWNER:
                    bad.append((rel, n.lineno, "直接讀寫設定鍵 storage_locations"))
                if "系統存檔_個資" in n.value and rel != _KEY_OWNER and rel not in ALLOWED_LITERAL:
                    bad.append((rel, n.lineno, "自己拼個資資料夾名稱（要經 storage_locations.path('pii_root')）"))
    return bad


def _real_sources():
    out = {}
    for base in (BACKEND, REPO / "tools"):
        for p in base.rglob("*.py"):
            rel = p.relative_to(REPO).as_posix()
            if "/tests/" in "/" + rel or rel.startswith("backend/tests") or "__pycache__" in rel or "/.venv" in rel:
                continue
            out[rel] = p.read_text(encoding="utf-8", errors="replace")
    return out


def test_every_reader_goes_through_the_resolver():
    src = _real_sources()
    assert "backend/archive.py" in src and _KEY_OWNER in src and len(src) > 100, "掃描範圍壞了"
    bad = violations(src)
    assert not bad, "\n".join("%s:%d %s" % b for b in bad)
    for rel in ALLOWED_LITERAL:
        assert "系統存檔_個資" in src.get(rel, ""), "例外清單過期：%s 已經沒有那段文字" % rel


def test_positive_control_a_direct_reader_lights_up():
    src = {"backend/helpers/x.py": "import archive\nBASE = archive._detect_archive_base()\n"
                                   "P = BASE + '\\\\系統存檔_個資'\nK = 'storage_locations'\n"}
    kinds = sorted(b[2].split("（")[0] for b in violations(src))
    assert len(kinds) == 3, violations(src)


def test_reverse_control_comments_docstrings_and_owners_do_not_count():
    src = {"backend/helpers/x.py": '"""提到 系統存檔_個資 與 _detect_archive_base 的說明"""\n# archive._detect_archive_base()\nX = 1\n',
           "backend/archive.py": "def _archive_base():\n    return _auto_archive_base()\n",
           "backend/helpers/storage_locations.py": "SETTING_KEY = 'storage_locations'\nPII = '系統存檔_個資'\n"}
    assert violations(src) == []


# ── D 稽核 SL-M1：讀不到設定 ≠ 沒設定 ──

def test_slm1_unreadable_settings_resolve_to_nothing_not_to_auto(client, tmp_path, monkeypatch):
    import archive
    from helpers import storage_locations as SL
    auto = tmp_path / "auto"
    auto.mkdir()
    monkeypatch.setattr(archive, "_auto_archive_base", lambda: str(auto))
    root, pii = tmp_path / "root", tmp_path / "pii"
    root.mkdir()
    pii.mkdir()
    _set({"archive_root": str(root), "pii_root": str(pii)})
    SL.invalidate()
    real = SL._read_main_db
    monkeypatch.setattr(SL, "_read_main_db", lambda: None)            # 庫被鎖／損毀
    for k in SL.KINDS:
        assert SL.resolve(k) == {"path": "", "source": "unknown"}, k  # 不是 auto 的 tmp/auto
    assert all(v["source"] == "unknown" for v in SL.status().values())
    with pytest.raises(SL.Unreadable):
        SL.configured()
    monkeypatch.setattr(SL, "_read_main_db", real)                     # 恢復 ⇒ 下一次就讀到（讀不到不快取）
    assert SL.path("archive_root") == str(root) and SL.path("pii_root") == str(pii)


def test_slm1_api_refuses_instead_of_showing_empty_values(client, make_user, monkeypatch):
    from helpers import storage_locations as SL
    h = _h(client, make_user(username="st_sa_slm1", role="superadmin"))
    _set({"archive_root": "", "pii_root": "", "delivery_root": ""})
    before = _stored()
    SL.invalidate()
    monkeypatch.setattr(SL, "_read_main_db", lambda: None)
    assert client.get("/api/settings/storage-locations", headers=h).status_code == 503
    r = client.put("/api/settings/storage-locations", headers=h,
                   json={"archive_root": "", "pii_root": "", "delivery_root": ""})
    assert r.status_code == 503 and _stored() == before
