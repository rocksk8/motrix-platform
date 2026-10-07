# -*- coding: utf-8 -*-
"""D7 演練工具（tools/platform/final_drill.py）的安全前提：來源只讀、路徑守門、複製範圍。"""
import json
import os
import re
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import final_drill as FD  # noqa: E402


def _db(path, wal=False):
    c = sqlite3.connect(str(path))
    if wal:
        c.execute("PRAGMA journal_mode=WAL")
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (1)")
    c.commit()
    c.close()


@pytest.mark.parametrize("wal", [False, True])
def test_ro_backup_does_not_touch_the_source(tmp_path, wal):
    src = tmp_path / "src" / "motrix_erp.db"
    src.parent.mkdir()
    _db(src, wal)
    before = (src.read_bytes(), src.stat().st_mtime_ns, sorted(p.name for p in src.parent.iterdir()))
    FD.ro_backup(str(src), str(tmp_path / "dst" / "motrix_erp.db"))
    assert (src.read_bytes(), src.stat().st_mtime_ns, sorted(p.name for p in src.parent.iterdir())) == before
    c = sqlite3.connect(str(tmp_path / "dst" / "motrix_erp.db"))
    assert c.execute("SELECT x FROM t").fetchall() == [(1,)]
    c.close()


def test_ro_backup_refuses_to_write_into_the_source(tmp_path):
    """反向控制：唯讀連線真的是唯讀（寫入會失敗）——證明上一題不是剛好沒寫。"""
    src = tmp_path / "a.db"
    _db(src)
    c = sqlite3.connect("file:%s?mode=ro" % src.as_posix(), uri=True)
    with pytest.raises(sqlite3.OperationalError):
        c.execute("INSERT INTO t VALUES (2)")
    c.close()


def test_install_path_with_v9_0_is_refused(tmp_path):
    with pytest.raises(AssertionError, match="V9.0"):
        FD.build_install(str(tmp_path), str(tmp_path / "V9.0" / "v9-install"))


def test_copy_skips_repo_and_env_directories(tmp_path):
    root = tmp_path / "v9"
    for rel in (".git/HEAD", "node_modules/x.js", ".venv312/lib.py", "deploy_packages/p.zip",
                "backend/__pycache__/a.pyc", "backend/main.py", "frontend/index.html"):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("x", encoding="utf-8")
    got = sorted(os.path.relpath(p, root).replace("\\", "/") for p in FD._walk(str(root)))
    assert got == ["backend/main.py", "frontend/index.html"]


def test_ro_backup_captures_uncheckpointed_wal_content(tmp_path):
    """來源的最新資料還在 -wal 裡（另一條連線開著、還沒 checkpoint）⇒ 備份也要有那一筆；來源目錄的檔案清單不變。"""
    src = tmp_path / "src" / "motrix_erp.db"
    src.parent.mkdir()
    c = sqlite3.connect(str(src))
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA wal_autocheckpoint=0")
    c.execute("CREATE TABLE t (x)")
    c.execute("INSERT INTO t VALUES (42)")
    c.commit()                                                     # 連線不關 ⇒ 資料留在 -wal
    try:
        before = sorted(p.name for p in src.parent.iterdir())
        assert "motrix_erp.db-wal" in before
        FD.ro_backup(str(src), str(tmp_path / "dst" / "motrix_erp.db"))
        assert sorted(p.name for p in src.parent.iterdir()) == before
    finally:
        c.close()
    d = sqlite3.connect(str(tmp_path / "dst" / "motrix_erp.db"))
    assert d.execute("SELECT x FROM t").fetchall() == [(42,)]
    d.close()


def _route_matches(template, path):
    """`/api/definitions/{kind}` 對得上 `/api/definitions/custom_module`（一個 {參數} 對一段）。"""
    parts = re.split(r"\{[^}]+\}", template)
    return re.fullmatch("[^/]+".join(re.escape(p) for p in parts), path) is not None


def test_smoke_route_matcher():
    assert _route_matches("/api/definitions/{kind}", "/api/definitions/custom_module")
    assert not _route_matches("/api/definitions/{kind}", "/api/definitions/a/b")
    assert _route_matches("/api/vouchers", "/api/vouchers") and not _route_matches("/api/voucher", "/api/vouchers")


def test_smoke_paths_are_real_routes_or_pages(client):
    """稽核 D：冒煙清單的每一條都必須是 app 的 GET 路由，或 frontend/ 底下真的有的頁面（打錯字不會在演練時才發現）。
    屬於 L2 模組的項目在 `SMOKE` 帶模組 key（`smoke_plan`），那個模組不在時不算。"""
    from tests._routes import all_routes
    gets = {p for p, methods, _r in all_routes(client.app) if "GET" in methods}
    front = REPO / "frontend"
    missing = []
    for name, method, path, skipped in FD.smoke_plan(str(REPO / "backend")):
        assert method == "GET", name
        if skipped:                       # 模組不在這棵樹（反向控制／產品選配）：它的路由本來就不在
            continue
        if path == "/" or path.endswith(".html"):
            target = front / ("index.html" if path == "/" else path.lstrip("/"))
            if not target.is_file():
                missing.append((name, path))
        elif not any(_route_matches(g, path) for g in gets):
            missing.append((name, path))
    assert not missing, "冒煙清單裡不存在的路徑：%s" % missing


def _mod(backend, key, probes=None, pages=()):
    import json
    d = backend / "modules" / key
    d.mkdir(parents=True)
    prov = {"api_prefixes": ["/api/" + key]}
    if probes is not None:
        prov["probes"] = probes
    (d / "module.json").write_text(json.dumps({"key": key, "provides": prov, "pages": [{"path": p} for p in pages]}),
                                   encoding="utf-8")


def test_smoke_plan_derives_module_checks_from_the_package(tmp_path):
    """合成樹（不綁真實模組）：包內模組 ⇒ 打它宣告的 probes 與頁面；登記了卻不在包內 ⇒ 明列「不在安裝包」；共用清單照跑。"""
    backend = tmp_path / "backend"
    _mod(backend, "aa", probes=["/api/aa/list"], pages=["aa.html"])
    plan = FD.smoke_plan(str(backend), registered={"aa", "bb", "cc"}, migrated={"aa", "bb"})
    rows = {(p[2], p[3]) for p in plan}
    assert ("/api/aa/list", None) in rows and ("/pages/aa.html", None) in rows
    assert ("modules/bb", "模組 bb %s" % FD.ABSENT) in rows
    # D 稽核 S-1：有 key 但還沒搬遷（沒有 mod: 單位）的，說成「尚未搬遷」，不是「不在安裝包」（報告讀者會以為少了功能）
    assert ("modules/cc", "模組 cc %s" % FD.NOT_MIGRATED) in rows
    assert all(p[3] is None for p in plan[:len(FD.SMOKE)])
    out = {"checks": [{"name": "x", "ok": True}],
           "skipped": [{"name": n, "path": pa, "reason": r} for n, _m, pa, r in plan if r]}
    assert FD.smoke_ok(out) is True                    # 只有「不在安裝包」的略過 ⇒ 合法


def test_rc_a_module_without_probes_fails_the_smoke(tmp_path):
    """反向控制：包內模組沒宣告 probes ⇒ 判不過（沒宣告的模組不可以進正式 D7）。"""
    backend = tmp_path / "backend"
    _mod(backend, "aa")
    plan = FD.smoke_plan(str(backend), registered={"aa"})
    reasons = [p[3] for p in plan if p[3]]
    assert reasons and FD.UNDECLARED in reasons[0], plan
    out = {"checks": [{"name": "x", "ok": True}], "skipped": [{"name": "aa", "path": "modules/aa", "reason": reasons[0]}]}
    assert FD.smoke_ok(out) is False


def test_rc_an_unregistered_module_in_the_package_fails_the_smoke(tmp_path):
    """反向控制：包內模組的 key 沒在 modules.json 登記（打錯字或改名）⇒ 判不過，而不是當成合法略過。"""
    backend = tmp_path / "backend"
    _mod(backend, "analytcs", probes=["/api/analytcs/x"])
    plan = FD.smoke_plan(str(backend), registered={"analytics"})
    reasons = [p[3] for p in plan if p[3] and "analytcs" in p[3]]
    assert reasons and FD.UNREGISTERED in reasons[0], plan
    out = {"checks": [{"name": "x", "ok": True}], "skipped": [{"name": "x", "path": "modules/analytcs", "reason": reasons[0]}]}
    assert FD.smoke_ok(out) is False


def _migrated_claims():
    """已搬遷模組的前綴與頁面：modules.json 裡已搬遷群組（FD.migrated_module_keys）的 api_prefixes，
    加上樹上各模組 module.json 宣告的前綴與頁面。

    〔第八班列車（core-only 反向控制抓到，2026-09-26）：原本只讀樹上的 module.json ⇒ 模組全拿掉的樹上前綴清單是空的，
    正對照紅——正對照綁在 L2 模組在不在（§C-6 不准）。modules.json 在 L1、core-only 樹上也在 ⇒ 前綴檢查照常生效；
    頁面只有 module.json 宣告，模組不在時頁面那一半沒有對象（該模組的頁面也不會被服務）〕"""
    import json
    prefixes, pages = [], set()
    mods = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8")).get("modules") or {}
    migrated = FD.migrated_module_keys()
    for g in mods.values():
        if g.get("key") in migrated:
            prefixes += [(g["key"], p.rstrip("/")) for p in g.get("api_prefixes") or []]
    for mj in (REPO / "backend" / "modules").glob("*/module.json"):
        m = json.loads(mj.read_text(encoding="utf-8"))
        prov = m.get("provides") or {}
        prefixes += [(mj.parent.name, p.rstrip("/")) for p in prov.get("api_prefixes") or []]
        pages |= {"/pages/" + pg["path"] for pg in m.get("pages") or []}
    return sorted(set(prefixes)), pages


def core_violations(smoke, prefixes, pages):
    bad = []
    for name, _m, path in smoke:
        if path in pages:
            bad.append("%s %s：是模組頁面" % (name, path))
        for key, pre in prefixes:
            if path == pre or path.startswith(pre + "/"):
                bad.append("%s %s：在模組 %s 的前綴 %s 底下" % (name, path, key, pre))
    return bad


def test_smoke_core_has_no_paths_of_migrated_modules():
    """共用清單不可以放已搬遷模組的路徑（否則那個模組不在時必紅，例：/pages/bonus.html 在 payroll 搬走後）。"""
    prefixes, pages = _migrated_claims()
    assert prefixes, "正對照：repo 裡應該有已搬遷的模組"
    bad = core_violations(FD.SMOKE, prefixes, pages)
    assert not bad, "共用冒煙清單混進了模組的路徑（改由模組宣告 provides.probes）：\n  " + "\n  ".join(bad)


def test_rc_core_violation_is_caught():
    assert core_violations([("x", "GET", "/pages/zz.html"), ("y", "GET", "/api/zz/list"), ("ok", "GET", "/api/zzz")],
                           [("zz", "/api/zz")], {"/pages/zz.html"}) == [
        "x /pages/zz.html：是模組頁面", "y /api/zz/list：在模組 zz 的前綴 /api/zz 底下"]


def test_logical_digest_ignores_bytes_but_not_content(tmp_path):
    """K-M1：6a 用邏輯內容比對「還原後＝原始庫」——Online Backup 的副本位元組不同也要相等；少一筆就不相等；檔案不在要報錯不是建空庫。"""
    src = tmp_path / "a.db"
    _db(src)
    cp = tmp_path / "b.db"
    FD.ro_backup(str(src), str(cp))
    assert FD.logical_digest(str(src)) == FD.logical_digest(str(cp))
    c = sqlite3.connect(str(cp))
    c.execute("INSERT INTO t VALUES (2)")
    c.commit()
    c.close()
    assert FD.logical_digest(str(src)) != FD.logical_digest(str(cp))
    with pytest.raises(FileNotFoundError):
        FD.logical_digest(str(tmp_path / "missing.db"))
    assert not (tmp_path / "missing.db").exists()


def _fake_6a(tmp_path, monkeypatch, *, equal=True, problems=()):
    """6a 的假環境：記下 rollback／start 的呼叫；source-backup 與還原後的主庫內容相同或不同。"""
    root = tmp_path / "drill"
    for rel in ("source-backup/backend", "v9-install/backend", FD.FIRST_BACKUP, FD.SECOND_BACKUP):
        (root / rel).mkdir(parents=True)
    _db(root / "source-backup" / "backend" / "motrix_erp.db")
    calls = []

    def rollback(install, backup_dir, mode, info):
        calls.append(("rollback", os.path.basename(backup_dir), mode))
        _db(Path(install) / "backend" / "motrix_erp.db")
        if not equal:
            c = sqlite3.connect(str(Path(install) / "backend" / "motrix_erp.db"))
            c.execute("INSERT INTO t VALUES (99)")
            c.commit()
            c.close()
        return list(problems)

    monkeypatch.setattr(FD.U, "rollback", rollback)
    monkeypatch.setattr(FD.T, "start_and_ping", lambda install, port: calls.append(("start",)) or {"ok": True, "status": 200})
    return str(root), calls


def test_full_rollback_uses_the_first_backup_and_checks_the_source(tmp_path, monkeypatch):
    """K-M1：6a 用第一份備份（轉換前的原始庫）做完整回滾；內容等於 source-backup ⇒ 才啟動 V9、判通過。"""
    root, calls = _fake_6a(tmp_path, monkeypatch)
    out = FD.full_rollback_step(root)
    assert calls == [("rollback", FD.FIRST_BACKUP, "full"), ("start",)]
    assert out["ok"] is True and out["logical_equal_to_source"] is True and out["backup"] == FD.FIRST_BACKUP


@pytest.mark.parametrize("equal,problems", [(False, ()), (True, ("雜湊不符",))])
def test_full_rollback_fails_when_not_equal_to_the_source(tmp_path, monkeypatch, equal, problems):
    """K-M1 反向控制：還原後內容與原始庫不同、或還原回報問題 ⇒ 判失敗，而且不啟動 V9。"""
    root, calls = _fake_6a(tmp_path, monkeypatch, equal=equal, problems=problems)
    out = FD.full_rollback_step(root)
    assert out["ok"] is False and ("start",) not in calls
    assert out["logical_equal_to_source"] is equal


def test_cleanup_keeps_the_scene_when_the_drill_failed(tmp_path):
    """K-S3：失敗 ⇒ 演練目錄全部保留並回傳路徑（寫進報告）；通過 ⇒ 刪；--keep-install ⇒ 保留。source-backup 一律不動。"""
    def make():
        for d in FD.DRILL_DIRS + ("source-backup",):
            (tmp_path / d).mkdir(exist_ok=True)
    make()
    kept = FD.cleanup(str(tmp_path), ok=False, keep=False)
    assert sorted(os.path.basename(k) for k in kept) == sorted(FD.DRILL_DIRS)
    assert all((tmp_path / d).is_dir() for d in FD.DRILL_DIRS)
    assert len(FD.cleanup(str(tmp_path), ok=True, keep=True)) == len(FD.DRILL_DIRS)
    assert FD.cleanup(str(tmp_path), ok=True, keep=False) == []
    assert not any((tmp_path / d).exists() for d in FD.DRILL_DIRS) and (tmp_path / "source-backup").is_dir()


def test_report_names_the_kept_directories(tmp_path):
    rep = {"at": "t", "v9_dir": "v", "drill_root": "r", "new_source": "n", "steps": [{"name": "6a", "ok": False}],
           "ok": False, "stopped_at": "6a", "kept_for_diagnosis": [str(tmp_path / "v9-install")]}
    FD.write_report(rep, str(tmp_path / "r.md"))
    text = (tmp_path / "r.md").read_text(encoding="utf-8")
    assert "保留" in text and str(tmp_path / "v9-install") in text





def test_migrated_keys_follow_modules_json_mod_units():
    """真實登記表：已搬遷＝群組含 mod: 單位；有 key 還沒搬的不在裡面（與 check_group_keys 同判準）。"""
    import json
    groups = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))["modules"].values()
    want = {g["key"] for g in groups if g.get("key") and any(str(u).startswith("mod:") for u in g.get("units") or [])}
    got = FD.migrated_module_keys()
    assert got == want and got, got
    assert got < FD.registered_module_keys() or got == FD.registered_module_keys()


# ── 缺席模組實際打 probes／頁面驗 404（主持裁示；D7-CHECKLIST §3）──────────────────────────

def _decl(root, key, probes=(), pages=()):
    d = root / key
    d.mkdir(parents=True)
    (d / "module.json").write_text(json.dumps({"key": key, "provides": {"probes": list(probes)},
                                               "pages": [{"path": p} for p in pages]}), encoding="utf-8")


def test_absent_modules_are_probed_expecting_404(tmp_path):
    """包裡只有 aa；bb 已搬遷而缺席 ⇒ bb 在來源樹宣告的 probes 與頁面每一項期望 404；cc 尚未搬遷 ⇒ 不在這裡；
    dd 已搬遷缺席、來源樹沒有宣告 ⇒ 期望狀態碼 None（smoke 判不過）。"""
    pkg = tmp_path / "pkg" / "backend"
    _decl(pkg / "modules", "aa", probes=["/api/aa/x"])
    src = tmp_path / "src"
    _decl(src, "aa", probes=["/api/aa/x"])
    _decl(src, "bb", probes=["/api/bb/list", "/api/bb/one"], pages=["bb.html"])
    plan = FD.absent_probe_plan(str(pkg), source_modules=str(src),
                                registered={"aa", "bb", "cc", "dd"}, migrated={"aa", "bb", "dd"})
    rows = {(path, expect) for _n, _m, path, expect in plan}
    assert rows == {("/api/bb/list", 404), ("/api/bb/one", 404), ("/pages/bb.html", 404), ("modules/dd", None)}, rows


def test_a_non_404_from_an_absent_module_turns_the_smoke_red():
    """反向控制：缺席模組的 probe 回 200（模組其實沒被拿掉，或 L1 替它接住了）⇒ smoke_ok 判不過；回 404 ⇒ 過。"""
    base = [{"name": "首頁", "path": "/", "status": 200, "ok": True}]
    good = {"checks": base + [{"name": "缺席 bb", "path": "/api/bb/list", "status": 404, "expect": 404, "ok": True}]}
    bad = {"checks": base + [{"name": "缺席 bb", "path": "/api/bb/list", "status": 200, "expect": 404, "ok": False}]}
    assert FD.smoke_ok(good) is True
    assert FD.smoke_ok(bad) is False


def test_smoke_runs_the_absent_plan():
    """smoke() 真的會跑 absent_probe_plan，而且以 expect 判 ok（不是寫死 200）——讀碼守門，行為由 D7 前哨實跑驗。"""
    import inspect
    src = inspect.getsource(FD.smoke)
    assert "absent_probe_plan(" in src and '"ok": code == expect' in src


def test_an_absent_module_with_an_empty_declaration_is_red(tmp_path):
    """稽核 D 建議：module.json 在、probes 與 pages 都空 ⇒ 缺席時沒有東西可驗 ⇒ 期望狀態碼 None（smoke 判不過）；
    只有頁面、沒有 probes ⇒ 照驗頁面（不算空）。"""
    pkg = tmp_path / "pkg" / "backend"
    (pkg / "modules").mkdir(parents=True)
    src = tmp_path / "src"
    _decl(src, "ee")
    _decl(src, "ff", pages=["ff.html"])
    plan = FD.absent_probe_plan(str(pkg), source_modules=str(src), registered={"ee", "ff"}, migrated={"ee", "ff"})
    rows = {(path, expect) for _n, _m, path, expect in plan}
    assert rows == {("modules/ee", None), ("/pages/ff.html", 404)}, rows


# ── S-1 缺席明說（原本只在 d7-tools\d7_extra.py；判準照 D 2b8afa60 審定）────────────────────────────────

def _combos():
    """代表性的選配：全部在、core-only、每次拿掉一個、只留一個（13 份包的形狀）。"""
    keys = FD.registered_module_keys()
    return [set(keys), set()] + [set(keys) - {k} for k in sorted(keys)] + [{k} for k in sorted(keys)]


def _tree_combos():
    """同上，但只取**這棵樹實際有的**模組（modules.json 登記＋資料夾在，§G5 #15 的獨立訊號）。每一條缺席條目都要求
    「發出說明的一方」在（P(...)），所以讀原始碼與比對路由的題在拿掉模組的樹（core-only、§B-11）上只驗得到在場的，
    不會因為讀不到別的模組而紅（§G5 #12）。"""
    here = {k for k in FD.registered_module_keys() if (REPO / "backend" / "modules" / k / "module.json").is_file()}
    return [c & here for c in _combos()]


def test_explain_plan_is_empty_for_full_and_lists_l1_notices_for_core_only():
    """正對照：core-only ⇒ 至少有 L1 自己的兩條（IP-16 獎金入口、IP-91 報價預設條款）；full ⇒ 空（沒有東西缺席）。"""
    assert FD.explain_plan(FD.registered_module_keys(), "Q-1") == []
    ips = {row[0] for row in FD.explain_plan(set(), None)}
    assert {"IP-16", "IP-91"} <= ips, ips


def test_explain_plan_paths_are_real_get_routes(client):
    """每一條要打的路徑（去掉查詢字串）都是 app 的 GET 路由——打錯字不會在正式演練才發現。"""
    from tests._routes import all_routes
    gets = {p for p, methods, _r in all_routes(client.app) if "GET" in methods}
    paths = {row[2].split("?")[0] for present in _tree_combos() for row in FD.explain_plan(present, "Q-TEST")}
    assert paths, "一條都沒有 ⇒ 選配組合沒產生任何缺席條目，這一題沒驗到東西"
    missing = sorted(p for p in paths if not any(_route_matches(g, p) for g in gets))
    assert not missing, "缺席明說要打的路徑不是 GET 路由：%s" % missing


def test_explain_plan_notices_exist_in_the_product_source():
    """每一句要求的說明都真的寫在產品程式裡（tests 以外）——訊息改字時在這裡紅，不是在演練時假紅。"""
    src = "\n".join(p.read_text(encoding="utf-8", errors="replace") for p in (REPO / "backend").rglob("*.py")
                    if "tests" not in p.relative_to(REPO / "backend").parts)
    needles = {n for present in _tree_combos() for row in FD.explain_plan(present, "Q-TEST") for n in row[4]
               if not n.startswith('"')}                   # '"enabled":false' 這類是 JSON 形狀，不是字面訊息
    assert needles
    missing = sorted(n for n in needles if n not in src)
    assert not missing, "產品程式裡找不到這些說明：%s" % missing


def test_ip98_is_only_required_on_the_cash_basis():
    """判準 2（D 審定）：「應收應付模組未安裝」只在現金口徑要求；analytics 在、arap 缺席 ⇒ 有 basis=cash 那一條。"""
    for present in _combos():
        assert FD.ip98_basis_violations(FD.explain_plan(present, "Q-TEST")) == [], present
    rows = FD.explain_plan({"analytics", "case", "subcontract"}, None)
    assert any(r[0] == "IP-98" and r[2].endswith("basis=cash") and FD.ARAP_ABSENT in r[4] for r in rows), rows


def test_rc_ip98_on_accrual_basis_is_caught():
    """反向控制：第一版 d7_extra 的寫法（權責口徑要求應收應付的說明）⇒ ip98_basis_violations 抓得到。"""
    bad = ("IP-98", "x", FD._EXPENSES + "accrual", 200, [FD.ARAP_ABSENT])
    ok = ("IP-98", "x", FD._EXPENSES + "cash", 200, [FD.ARAP_ABSENT])
    assert FD.ip98_basis_violations([bad, ok]) == [bad]


def _av(**kw):
    return {k: {"state": v, "label": "", "name": k} for k, v in kw.items()}


def test_availability_lists_only_installed_modules():
    """判準 1（D 審定）：清單＝已安裝模組且都 loaded ⇒ 過；core-only 回空清單 ⇒ 過（缺席的 key 不在清單裡才對）。"""
    assert FD.availability_verdict(200, json.dumps(_av(aa="loaded", bb="loaded")), {"aa", "bb"})["ok"] is True
    assert FD.availability_verdict(200, "{}", set())["ok"] is True


@pytest.mark.parametrize("status, body, present", [
    (200, json.dumps(_av(aa="loaded", bb="absent")), {"aa"}),       # 第一版判準要的樣子（提到缺席的 bb）⇒ 其實是錯的
    (200, json.dumps(_av(aa="loaded", bb="loaded")), {"aa"}),       # 多列一個不在包內的 key（即使標 loaded）⇒ 紅（突變 M2 存活後補）
    (200, json.dumps(_av(aa="loaded")), {"aa", "bb"}),              # 已安裝的 bb 沒列
    (200, json.dumps(_av(aa="loaded", bb="failed")), {"aa", "bb"}),  # 列了但沒載入
    (500, json.dumps(_av(aa="loaded")), {"aa"}),
    (200, "not json", {"aa"}),
    (200, "[]", set()),
])
def test_rc_availability_mismatches_are_red(status, body, present):
    assert FD.availability_verdict(status, body, present)["ok"] is False


def test_absence_verdict_needs_status_and_every_notice():
    ok = FD.absence_verdict(200, '{"enabled": false, "notice": "薪資獎金模組未安裝：獎金分潤不提供"}', 200,
                            ['"enabled":false', "薪資獎金模組未安裝"])
    assert ok["ok"] is True, "JSON 的空白不影響比對"
    assert FD.absence_verdict(500, "薪資獎金模組未安裝", 200, ["薪資獎金模組未安裝"])["ok"] is False
    miss = FD.absence_verdict(200, '{"enabled": false}', 200, ['"enabled":false', "薪資獎金模組未安裝"])
    assert miss["ok"] is False and miss["lacking"] == ["薪資獎金模組未安裝"]
    assert FD.absence_verdict("URLError", "", 200, [])["ok"] is False, "連線失敗不是 int，不可以過"


def test_installed_modules_prefers_the_lock_then_folders(tmp_path):
    backend = tmp_path / "backend"
    _mod(backend, "aa", probes=["/api/aa/x"])
    _mod(backend, "bb", probes=["/api/bb/x"])
    assert FD.installed_modules(str(backend)) == ({"aa", "bb"}, "modules/ 資料夾")
    (backend / "modules.lock.json").write_text(json.dumps({"modules": {"aa": {}}}), encoding="utf-8")
    assert FD.installed_modules(str(backend)) == ({"aa"}, "modules.lock.json")


def _explain(**over):
    ex = {"availability": {"ok": True}, "absence": [{"ok": True}], "pages": [{"ok": True}], "crawl": {"ok": True}}
    ex.update(over)
    return ex


def test_explain_ok_needs_every_part():
    assert FD.explain_ok(_explain()) is True
    assert FD.explain_ok(_explain(absence=[])) is True, "full：沒有缺席條目是合法的"


@pytest.mark.parametrize("over", [
    {"availability": {"ok": False}}, {"availability": None},
    {"absence": [{"ok": True}, {"ok": False}]}, {"absence": None},
    {"pages": []}, {"pages": [{"ok": False}]},
    {"crawl": {"ok": False}}, {"crawl": None},
])
def test_rc_explain_part_missing_or_red_fails(over):
    """反向控制：任何一部分紅、或沒有結果（沒跑到）⇒ 不過；不可以因為少了一項而變綠。"""
    assert FD.explain_ok(_explain(**over)) is False


def test_smoke_verdict_requires_the_explain():
    base = {"checks": [{"name": "首頁", "path": "/", "status": 200, "ok": True}]}
    assert FD.smoke_verdict({**base, "explain": {"ok": True}}) is True
    assert FD.smoke_verdict({**base, "explain": {"ok": False}}) is False
    assert FD.smoke_verdict(base) is False, "沒跑到缺席明說 ⇒ 冒煙不過"


def test_smoke_runs_the_explain():
    """smoke() 真的呼叫 explain_absence、而且用 smoke_verdict 判 ok——讀碼守門，行為由正式演練實跑驗。"""
    import inspect
    src = inspect.getsource(FD.smoke)
    assert "explain_absence(" in src and 'out["ok"] = smoke_verdict(out)' in src


def test_report_says_when_the_explain_did_not_run():
    rep = {"steps": [{"name": "5 冒煙", "ok": False}]}
    text = "\n".join(FD.explain_report_lines(rep))
    assert "未驗" in text
    rep = {"steps": [{"name": "5 冒煙", "ok": True, "explain": {
        "installed": ["aa"], "installed_from": "modules.lock.json", "availability": {"ok": True, "status": 200},
        "pages": [{"ok": True}], "crawl": {"checked": 3, "by_status": {"200": 3}, "bad": []},
        "absence": [{"ip": "IP-16", "name": "n", "path": "/p", "status": 200, "expect": 200, "lacking": [], "ok": True}]}}]}
    text = "\n".join(FD.explain_report_lines(rep))
    assert "IP-16" in text and "modules.lock.json" in text


# ── 第 46 班：本公司資料閘門（428）與離線工具不建空庫 ─────────────────────────────

@pytest.mark.company_gate
def test_drill_company_confirmation_opens_the_gate(tmp_path, monkeypatch):
    """演練複本沒有確認紀錄 ⇒ 全部 /api 428；ensure_drill_company 寫入後閘門必須是「已設定」。"""
    import contextlib
    import io
    sys.path.insert(0, str(REPO / "backend"))
    import db
    from helpers import company_setup as C
    install = tmp_path / "install"
    (install / "backend" / "helpers").mkdir(parents=True)
    (install / "backend" / "helpers" / "company_setup.py").write_text("# stub marker\n")
    dbp = install / "backend" / "motrix_erp.db"
    db.init_db(str(dbp))
    monkeypatch.setattr(C, "FILES_OVERRIDE", [str(tmp_path / "id"), str(tmp_path / "sig"), str(tmp_path / "grace")])

    def run_here(backend, code):                     # 以行程內執行代替子行程（FILES_OVERRIDE 只在本行程有效）
        monkeypatch.chdir(backend)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            exec(code, {})
        return buf.getvalue().strip()
    monkeypatch.setattr(FD, "_py_in", run_here)
    conn = sqlite3.connect(str(dbp))
    conn.execute("DELETE FROM system_settings WHERE key IN ('company_profile', ?)", (C.CONFIRMATION_SETTING,))
    conn.commit()
    assert C.status(conn)["configured"] is False         # 起點＝V9 轉換後的複本：沒有確認紀錄
    conn.close()
    out = FD.ensure_drill_company(str(install))
    assert out["gate"] is True and C.ubn_valid(out["tax"]) and out["tax"] != C.RESERVED_DEMO_UBN
    conn = sqlite3.connect(str(dbp))
    assert C.status(conn)["configured"] is True
    assert not C.is_developer_identity(C._get(conn, "company_profile"))
    conn.close()


def test_drill_company_skips_programs_without_the_gate(tmp_path):
    (tmp_path / "backend").mkdir()
    assert "skipped" in FD.ensure_drill_company(str(tmp_path))


def test_drill_428_is_labelled_as_gate_not_endpoint_failure():
    assert "428" in FD.GATE_428 and "閘門" in FD.GATE_428


def test_offline_tool_refuses_missing_db_without_creating_it(tmp_path):
    sys.path.insert(0, str(REPO / "backend" / "tools"))
    import _dbbind
    missing = tmp_path / "nope.db"
    with pytest.raises(SystemExit) as e:
        _dbbind.bind(str(missing))
    assert e.value.code == 2 and not missing.exists()
    with pytest.raises(SystemExit):
        _dbbind.connect_path(str(missing))
    assert not missing.exists()


@pytest.mark.parametrize("tool", ["audit_account_permissions", "backfill_location_identity_snapshot",
                                  "finance_role_impact_report", "list_payment_anomalies",
                                  "duty_roles_export_effective"])
def test_offline_tools_with_db_flag_never_create_an_empty_db(tmp_path, tool):
    import subprocess
    missing = tmp_path / "nope.db"
    r = subprocess.run([sys.executable, str(REPO / "backend" / "tools" / (tool + ".py")),
                        "--db", str(missing)], cwd=str(tmp_path), capture_output=True, timeout=120,
                       env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "MOTRIX_DISABLE_SCHEDULERS": "1"})
    assert r.returncode == 2, r.stderr[-400:]
    assert not missing.exists() and not list(tmp_path.glob("*.db"))


@pytest.mark.parametrize("v9,base,ok", [(116, 116, True), (115, 116, True), (118, 116, False)])
def test_schema_gap_flags_v9_ahead_of_baseline(tmp_path, v9, base, ok):
    for name, text in (("v9", "CURRENT_VERSION = %d\n" % v9), ("new", "CURRENT_VERSION = %d\nV9_BASELINE = %d\n" % (base, base))):
        (tmp_path / name).mkdir()
        (tmp_path / name / "db.py").write_text(text)
    r = FD.schema_gap(str(tmp_path / "v9"), str(tmp_path / "new"))
    assert r["ok"] is ok and (ok or ("117" in r["reason"] and "118" in r["reason"]))


def test_schema_gap_unreadable_is_not_a_pass(tmp_path):
    assert FD.schema_gap(str(tmp_path / "x"), str(tmp_path / "y"))["ok"] is False
