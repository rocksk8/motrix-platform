"""D7 演練的 probe（模組 `module.json` 的 `provides.probes`）必須是**純讀**，而且**不把回應內容寫進 log**。

主持裁示（2026-09-26，D7-CHECKLIST §4／RUN-PLAN §6）：演練以最高管理者打每支 probe，只記狀態碼。
① 無副作用：打 probe 前後，每張表的列數＋整表內容雜湊不變；不寄信（smtplib.SMTP 不被建立）；
   不起背景工作（threading.Thread.start 不被本程式碼呼叫；TestClient／anyio 自己的執行緒不算）
   ⚠ **暖機**：每支 probe 先打一次再量——首次讀取可能懶初始化設定列（例：預設簽核設定），那不是 probe 的副作用，
   但要冪等（第二次起不再變）；第二次起的任何變化都算 probe 的副作用。
② 回應值不進 log：打 probe 時攔 app 的 logging（caplog，root，DEBUG 以上）與 stdout／stderr（capsys），
   新增的內容不可以含這支 probe 回應 JSON 裡任何長度 ≥4 的字串值（數字不比，避免誤報）。
③ 演練工具只記狀態碼：tools/platform/product_drill.py、final_drill.py 對 probe／冒煙回應只取狀態碼，不把內文放進報告。
正對照／反向控制：比對器對「會寫表」「會 log 回應」「會起背景執行緒」的合成動作都要報得出來。
規則寫在 MODULE-GUIDE 的 probes 段（「probe 路由不可以 log 回應內容」）。
"""
import ast
import hashlib
import json
import logging
import smtplib
import threading
from pathlib import Path

import pytest

from tests.platform.test_product_drill_probes import _installed_probes

REPO = Path(__file__).resolve().parents[3]


# ── 比對器 ────────────────────────────────────────────────────────────────────

def db_fingerprint():
    """{表名: (列數, 內容 sha256)}（排除 sqlite_ 內部表）。"""
    import db
    conn = db.get_db()
    try:
        out = {}
        tables = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        for t in tables:
            rows = conn.execute('SELECT * FROM "%s"' % t.replace('"', '""')).fetchall()
            h = hashlib.sha256()
            for r in sorted(repr(tuple(r)) for r in rows):
                h.update(r.encode("utf-8", "replace"))
            out[t] = (len(rows), h.hexdigest())
        return out
    finally:
        conn.close()


def changed_tables(before, after):
    return sorted(t for t in set(before) | set(after) if before.get(t) != after.get(t))


def string_values(obj, minlen=4):
    """回應 JSON 裡所有字串值（遞迴；長度 ≥ minlen；數字不算）。"""
    out = set()
    if isinstance(obj, str):
        if len(obj.strip()) >= minlen:
            out.add(obj.strip())
    elif isinstance(obj, dict):
        for v in obj.values():
            out |= string_values(v, minlen)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            out |= string_values(v, minlen)
    return out


def leaked(values, text):
    return sorted(v for v in values if v in text)


class _SideEffects:
    """攔 smtplib.SMTP 與本程式碼的 threading.Thread.start。"""

    def __init__(self, monkeypatch):
        self.smtp, self.threads = [], []
        test = self

        class _NoSMTP:
            def __init__(self, *a, **k):
                test.smtp.append(a)
                raise OSError("probe 不可以寄信")
        monkeypatch.setattr(smtplib, "SMTP", _NoSMTP)
        monkeypatch.setattr(smtplib, "SMTP_SSL", _NoSMTP)
        orig_start = threading.Thread.start

        def _start(th, *a, **k):
            tgt = getattr(th, "_target", None)
            # 框架自己的工作執行緒（anyio／concurrent 的 Thread 子類別）沒有 _target ⇒ 不算；
            # 產品的背景工作一律 `threading.Thread(target=…)`（含 db.spawn_bg_thread 的 ctx.run）
            if tgt is not None:
                inner = th._args[0] if getattr(tgt, "__name__", "") == "run" and th._args else tgt
                mod = getattr(inner, "__module__", None) or ""
                if not mod.startswith(("anyio", "starlette", "concurrent", "asyncio")):
                    test.threads.append("%s.%s" % (mod, getattr(inner, "__qualname__", repr(inner))))
            return orig_start(th, *a, **k)
        monkeypatch.setattr(threading.Thread, "start", _start)


def _login(client, make_user):
    u, pw = make_user(username="probe_se_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]
    return {"Authorization": "Bearer " + tok}


def _seed(client, h):
    """讓 probe 的回應有內容（空清單比不出 log 外洩）。模組不在就略過那一筆。"""
    seeded = []
    if any(k == "crm" for k, _p, _x in _installed_probes()):
        r = client.post("/api/dev-cases", headers=h, json={"case_name": "探針案件甲乙", "customer_name": "探針客戶丙丁"})
        assert r.status_code == 201, r.text
        seeded.append("crm")
    if any(k == "subcontract" for k, _p, _x in _installed_probes()):
        r = client.post("/api/contractors", headers=h, json={"name": "探針承攬人戊", "phone": "0912345678",
                                                            "address": "探針市探針路一號"})
        assert r.status_code == 201, r.text
        seeded.append("subcontract")
    return seeded


# ── ①② 真實 probe ────────────────────────────────────────────────────────────

#: 對照組：中介層不記軌跡的端點（`trail.SKIP_PREFIXES`）。稽核 D（h-probes）：沒有對照組時，
#: 操作軌跡 `user_request_log` 會讓每一支 probe 都「有副作用」——解法是精確認出那一列，不是把整張表排除。
CONTROL_PATH = "/api/system/version"


def _uid(username):
    import db
    conn = db.get_db()
    try:
        return conn.execute("SELECT id FROM users WHERE username=?", (username,)).fetchone()["id"]
    finally:
        conn.close()


def _clear_trail(uid):
    import db
    conn = db.get_db()
    try:
        conn.execute("DELETE FROM user_request_log WHERE user_id=?", (uid,))
        conn.commit()
    finally:
        conn.close()


def _trail_rows():
    import db
    conn = db.get_db()
    try:
        return [tuple(r) for r in conn.execute("SELECT id, user_id, method, path, status FROM user_request_log ORDER BY id")]
    finally:
        conn.close()

def test_declared_probes_are_read_only_and_do_not_log_their_responses(client, make_user, monkeypatch, caplog, capsys):
    probes = _installed_probes()
    if not probes:
        pytest.skip("已安裝的模組都沒有宣告 probes ⇒ 無對象；⚠ skip 不是驗過")
    h = _login(client, make_user)
    _seed(client, h)
    for _k, path, _x in probes:                                   # 暖機（懶初始化）
        assert client.get(path, headers=h).status_code == 200, path
    fx = _SideEffects(monkeypatch)
    uid = _uid("probe_se_sa")
    # 對照組：中介層不記軌跡的端點（trail.should_skip）⇒ 整個庫一列都不能變（含 user_request_log）
    import trail
    assert trail.should_skip(CONTROL_PATH), CONTROL_PATH
    _clear_trail(uid)
    before = db_fingerprint()
    assert client.get(CONTROL_PATH, headers=h).status_code == 200
    assert changed_tables(before, db_fingerprint()) == [], "對照組（不記軌跡的端點）也讓庫變了 ⇒ 比對器或環境有問題"
    problems = []
    for key, path, _x in probes:
        _clear_trail(uid)            # 每支都從「沒有這個人的軌跡」開始 ⇒ 中介層一定寫恰好一列（不靠 30 秒去重的運氣）
        before = db_fingerprint()
        trail_before = _trail_rows()
        caplog.clear()
        capsys.readouterr()
        n_smtp, n_thr = len(fx.smtp), len(fx.threads)
        with caplog.at_level(logging.DEBUG):
            r = client.get(path, headers=h)
        out = capsys.readouterr()
        assert r.status_code == 200, (key, path, r.status_code)
        ch = changed_tables(before, db_fingerprint())
        # user_request_log：中介層（main.py `_record_request_trail`）對**每一個**請求記的操作軌跡——不是 probe 路由的副作用。
        # 只允許「恰好多一列：本人、GET、這支 probe 的路徑、200」，其他任何改動（改舊列、多列、別的路徑）照樣算。
        if "user_request_log" in ch:
            new = [r_ for r_ in _trail_rows() if r_ not in trail_before]
            old_kept = all(r_ in _trail_rows() for r_ in trail_before)
            if old_kept and len(new) == 1 and new[0][1:] == (uid, "GET", path, 200):
                ch.remove("user_request_log")
            else:
                problems.append("%s %s：user_request_log 的改動不是中介層那一列：新增 %s" % (key, path, new))
        if ch:
            problems.append("%s %s：寫了表 %s" % (key, path, ch))
        if len(fx.smtp) > n_smtp:
            problems.append("%s %s：嘗試寄信" % (key, path))
        if len(fx.threads) > n_thr:
            problems.append("%s %s：起了背景工作 %s" % (key, path, fx.threads[n_thr:]))
        text = "\n".join(rec.getMessage() for rec in caplog.records) + "\n" + out.out + "\n" + out.err
        lk = leaked(string_values(r.json()), text)
        if lk:
            problems.append("%s %s：回應值出現在 log：%s" % (key, path, lk[:5]))
    assert not problems, "probe 必須純讀且不 log 回應內容（換一支 probe，或修掉路由的副作用）：\n  " + "\n  ".join(problems)


# ── 正對照／反向控制（合成動作，不綁真實模組）────────────────────────────────────

def test_rc_fingerprint_sees_a_write_and_nothing_else(client):
    import db
    a = db_fingerprint()
    assert changed_tables(a, db_fingerprint()) == []                     # 沒動 ⇒ 沒變
    conn = db.get_db()
    try:
        conn.execute("INSERT INTO audit_log (action, created_at) VALUES ('probe_rc', '2026-09-26')")
        conn.commit()
    except Exception:
        conn.execute("CREATE TABLE zz_probe_rc (x)")
        conn.execute("INSERT INTO zz_probe_rc VALUES (1)")
        conn.commit()
    finally:
        conn.close()
    assert changed_tables(a, db_fingerprint()) != []


def test_rc_log_leak_and_thread_are_caught(client, make_user, monkeypatch, caplog, capsys):
    """合成路由：一支把回應值 log 出來、一支起背景執行緒、一支乾淨 ⇒ 前兩支被抓到、第三支不報。"""
    app = client.app
    log = logging.getLogger("zz.probe.rc")

    async def leaky():
        body = {"name": "外洩的姓名值", "items": [{"phone": "0987654321"}], "n": 12345}
        log.info("回傳 %s", json.dumps(body, ensure_ascii=False))
        return body

    async def spawner():
        import db
        db.spawn_bg_thread(lambda: None)
        return {"ok": "yes!"}

    async def clean():
        return {"name": "乾淨的姓名值", "n": 1}

    for p, fn in (("/api/zz-probe-rc/leaky", leaky), ("/api/zz-probe-rc/spawner", spawner), ("/api/zz-probe-rc/clean", clean)):
        app.add_api_route(p, fn, methods=["GET"])
        app.router.routes.insert(0, app.router.routes.pop())      # 排在萬用路由（/api/{…}、靜態檔）之前
    h = _login(client, make_user)
    try:
        fx = _SideEffects(monkeypatch)
        got = {}
        for p in ("/api/zz-probe-rc/leaky", "/api/zz-probe-rc/spawner", "/api/zz-probe-rc/clean"):
            caplog.clear()
            capsys.readouterr()
            n_thr = len(fx.threads)
            with caplog.at_level(logging.DEBUG):
                r = client.get(p, headers=h)
            out = capsys.readouterr()
            assert r.status_code == 200, (p, r.status_code, r.text[:120])
            text = "\n".join(rec.getMessage() for rec in caplog.records) + out.out + out.err
            got[p] = (leaked(string_values(r.json()), text), len(fx.threads) > n_thr)
        assert got["/api/zz-probe-rc/leaky"][0] == ["0987654321", "外洩的姓名值"], got
        assert got["/api/zz-probe-rc/spawner"][1] is True, got
        assert got["/api/zz-probe-rc/clean"] == ([], False), got
        assert string_values({"a": "abc", "b": 12345, "c": ["abcd"]}) == {"abcd"}       # 短字串、數字不比
    finally:
        app.router.routes[:] = [r for r in app.router.routes
                                     if not getattr(r, "path", "").startswith("/api/zz-probe-rc/")]


# ── ③ 演練工具只記狀態碼 ──────────────────────────────────────────────────────

def body_uses(src, callee_names):
    """呼叫 callee（`_req`／`urlopen`）的結果裡，內文被保留下來的地方（清單＝違規）。

    允許：`st, _ = _req(...)`、`urlopen(...).status`、`except HTTPError as e: e.code`。
    違規：`st, body = _req(...)` 且 body 之後被用到；`urlopen(...).read()` 的結果被放進任何容器／字串。"""
    tree = ast.parse(src)
    bad = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        body_names = set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Assign) and isinstance(n.value, ast.Call):
                c = n.value.func
                cname = c.attr if isinstance(c, ast.Attribute) else getattr(c, "id", "")
                if cname in callee_names and isinstance(n.targets[0], ast.Tuple) and len(n.targets[0].elts) == 2:
                    second = n.targets[0].elts[1]
                    if isinstance(second, ast.Name) and second.id != "_":
                        body_names.add(second.id)
        for n in ast.walk(fn):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Load) and n.id in body_names:
                bad.append("%s：%s（行 %d）" % (fn.name, n.id, n.lineno))
    return bad


def test_drill_tools_record_only_status_codes():
    """product_drill 的 drill()：打 probe 的 `_req` 結果只取狀態碼（登入／改密碼的錯誤訊息例外：那是認證端點，不是 probe）。"""
    src = (REPO / "tools/platform/product_drill.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    drill = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "drill")
    loop = [n for n in ast.walk(drill) if isinstance(n, ast.For)
            and isinstance(n.target, ast.Tuple) and "plan" in ast.unparse(n.iter)]
    assert loop, "找不到打 probe 的迴圈（for … in plan）⇒ 守門失效，先修守門"
    seg = ast.unparse(loop[0])
    assert body_uses("def f():\n" + "\n".join("    " + l for l in seg.splitlines()), {"_req"}) == [], seg
    fsrc = (REPO / "tools/platform/final_drill.py").read_text(encoding="utf-8")
    smoke = [n for n in ast.walk(ast.parse(fsrc)) if isinstance(n, ast.Attribute) and n.attr == "read"
             and "urlopen(r," in ast.unparse(n)]
    assert smoke == [], "final_drill 的冒煙讀了回應內文：%s" % [ast.unparse(n) for n in smoke]


def test_rc_body_uses_catches_a_kept_body():
    ok = "def f():\n    st, _ = _req(u)\n    out.append({'status': st})\n"
    bad = "def f():\n    st, body = _req(u)\n    out.append({'status': st, 'body': body[:200]})\n"
    assert body_uses(ok, {"_req"}) == []
    assert body_uses(bad, {"_req"}) == ["f：body（行 3）"]
