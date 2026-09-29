"""T21-1（2026-09-29）：main.py 啟動逐步耗時（`STARTUP_STEP <名稱> <毫秒>ms`＋最後一行 `STARTUP_TOTAL <毫秒>ms steps=<段數>`）。

起因：正式機套用第二十一班後，啟動到健檢通過從 3～4 秒變 14 秒，server.log 的 CORS 行 → GEO 行 11.2 秒（演練機同版 0.07 秒），
而那一段有十幾個呼叫、log 分不出是哪一個。下次上線直接 `Select-String server.log -Pattern 'STARTUP_'` 就能定位。

守門：
① 真的 `import main`（子行程、DB 與所有安裝檔導到暫存）⇒ 每一段恰好一行、順序與清單相同、最後一行是總耗時，
   段數與 steps= 相符、各段相加 ≈ 總耗時（反向控制：拿掉 `_startup_total()` ⇒ 紅，突變測過）
② 記錄本身出錯不可以丟例外（診斷不可以變成起不來的理由）
③ 所有 `_startup_step` 呼叫都在模組頂層（不在排程閘門區塊裡；test_geocode_warm_async 逐字執行那個區塊）
"""
import ast
import os
import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]

#: 分段清單＝main.py 的呼叫順序。改了 main.py 的分段 ⇒ 這裡一起改（讀 server.log 的人照這份名稱查）。
EXPECTED_STEPS = (
    "import_core", "import_routers", "load_modules", "build_info", "app_cors", "middleware_setup",
    "require_db", "init_db_main", "init_db_demo", "fail_incomplete_modules", "integrity_check", "company_setup",
    "init_default_admin", "init_demo_account", "flag_weak_passwords", "init_unlock_passwords", "cleanup_sessions",
    "schedulers", "geo_notice", "prune_login_locks", "init_rate_limiting", "sync_module_versions",
    "include_routers", "page_map", "mount_modules", "module_schedulers", "module_states_file", "startup_notices",
    "page_and_static_routes",
)

STEP_RE = re.compile(r"STARTUP_STEP (\S+) (\d+)ms$")
TOTAL_RE = re.compile(r"STARTUP_TOTAL (\d+)ms steps=(\d+)$")

_IMPORT_MAIN_SCRIPT = r'''
import os, sys
import db
_tmp = sys.argv[1]      # 父行程的 tmp_path（由 pytest --basetemp 管理，跑完隨 basetemp 刪）
db.DB_PATH = os.path.join(_tmp, "t.db")
db.DEMO_DB_PATH = os.path.join(_tmp, "d.db")
# 子行程沒有 conftest 的隔離：首次安裝帳密檔、本公司資料閘門三個安裝檔、模組載入狀態檔一律導到暫存
import helpers.auth as _auth, helpers.startup as _startup
_auth._CREDENTIALS_FILE = os.path.join(_tmp, "initial_admin_credentials.txt")
_startup._DEMO_CREDENTIALS_FILE = os.path.join(_tmp, "initial_demo_credentials.txt")
from helpers import company_setup as _cs
_cs.FILES_OVERRIDE = (os.path.join(_tmp, ".install_identity"), os.path.join(_tmp, "company_confirmation.sig"),
                      os.path.join(_tmp, "company_setup_grace.json"))
import core.paths as _core_paths
_core_paths.LOGS_DIR = os.path.join(_tmp, "logs")
os.makedirs(_core_paths.LOGS_DIR, exist_ok=True)
os.environ["MOTRIX_DISABLE_SCHEDULERS"] = "1"
import main  # noqa: F401
sys.stderr.flush()
print("IMPORT_OK")
sys.stdout.flush()
os._exit(0)
'''


def _tree_state():
    """子行程不可以動這棵樹的安裝檔。回 {檔名: mtime 或 None}。"""
    names = (".initial_admin_credentials.txt", ".initial_demo_credentials.txt", "logs/module_states.json",
             ".install_identity", "company_confirmation.sig", "company_setup_grace.json")
    return {n: (os.path.getmtime(BACKEND / n) if (BACKEND / n).exists() else None) for n in names}


def _startup_lines(text):
    return [l[l.index("STARTUP_"):].rstrip() for l in text.splitlines() if "STARTUP_STEP " in l or "STARTUP_TOTAL " in l]


def check_startup_log(lines):
    """⇒ 問題清單（真題與反向控制共用）。lines＝_startup_lines 的結果。"""
    problems = []
    steps = [STEP_RE.match(l) for l in lines if l.startswith("STARTUP_STEP ")]
    if any(m is None for m in steps):
        problems.append("STARTUP_STEP 行格式不對：%s" % [l for l in lines if l.startswith("STARTUP_STEP ") and not STEP_RE.match(l)])
        return problems
    names = tuple(m.group(1) for m in steps)
    if names != EXPECTED_STEPS:
        problems.append("分段與清單不同：\n  實際 %s\n  預期 %s" % (names, EXPECTED_STEPS))
    totals = [l for l in lines if l.startswith("STARTUP_TOTAL ")]
    if len(totals) != 1:
        problems.append("總耗時行應恰好 1 行，實際 %d 行" % len(totals))
        return problems
    if not lines or lines[-1] != totals[0]:
        problems.append("總耗時行不是最後一行 STARTUP_ 記錄")
    m = TOTAL_RE.match(totals[0])
    if m is None:
        problems.append("STARTUP_TOTAL 格式不對：%s" % totals[0])
        return problems
    total_ms, count = int(m.group(1)), int(m.group(2))
    if count != len(steps):
        problems.append("steps=%d 與實際段數 %d 不同" % (count, len(steps)))
    summed = sum(int(s.group(2)) for s in steps)
    if abs(summed - total_ms) > len(steps) + 1:     # 各段四捨五入到毫秒 ⇒ 誤差 ≤ 段數
        problems.append("各段相加 %dms 與總耗時 %dms 對不上（分段沒有接續）" % (summed, total_ms))
    return problems


def test_import_main_logs_every_step_and_total(tmp_path):
    from tests._subproc import run_python
    before = _tree_state()
    proc = run_python(["-c", _IMPORT_MAIN_SCRIPT, str(tmp_path)], cwd=BACKEND, timeout=240)
    assert _tree_state() == before, "子行程改動了這棵樹的安裝檔或載入狀態檔"
    assert proc.returncode == 0 and "IMPORT_OK" in proc.stdout, (
        f"子行程失敗（returncode={proc.returncode}）：\n{proc.stderr[-2500:]}")
    lines = _startup_lines(proc.stderr + "\n" + proc.stdout)
    problems = check_startup_log(lines)
    assert not problems, "\n".join(problems) + "\n--- 收到的 STARTUP_ 行 ---\n" + "\n".join(lines)


def test_check_startup_log_catches_missing_total_and_missing_step():
    """反向控制（同一支判定）：少了總耗時行、少一段、段名順序錯 ⇒ 都要有問題。"""
    good = ["STARTUP_STEP %s 1ms" % n for n in EXPECTED_STEPS] + ["STARTUP_TOTAL %dms steps=%d" % (len(EXPECTED_STEPS), len(EXPECTED_STEPS))]
    assert check_startup_log(good) == []
    assert check_startup_log(good[:-1]), "少了 STARTUP_TOTAL 沒被抓到"
    assert check_startup_log(good[1:]), "少了第一段沒被抓到"
    swapped = list(good)
    swapped[0], swapped[1] = swapped[1], swapped[0]
    assert check_startup_log(swapped), "段名順序錯沒被抓到"


def test_startup_step_swallows_logging_failures(client, monkeypatch):
    """記錄本身出錯（logger 丟例外、內部狀態壞掉）⇒ 不丟例外。"""
    import main

    class _Boom:
        handlers = [object()]

        def info(self, *a, **k):
            raise RuntimeError("log 壞了")

    class _FakeLogging:
        @staticmethod
        def getLogger(*a, **k):
            return _Boom()

    monkeypatch.setattr(main, "logging", _FakeLogging)
    monkeypatch.setattr(main, "_STARTUP_PENDING", [])
    main._startup_step("zz_probe")
    main._startup_total()
    monkeypatch.setattr(main, "_STARTUP_LAST", None)      # 內部狀態壞掉 ⇒ TypeError 也吞掉
    main._startup_step("zz_probe2")


def test_startup_step_calls_are_top_level():
    """所有 `_startup_step(...)` 都是模組頂層的單獨敘述（不在任何 if／for／函式裡）。"""
    tree = ast.parse((BACKEND / "main.py").read_text(encoding="utf-8"))
    top = [n.value for n in tree.body if isinstance(n, ast.Expr) and isinstance(n.value, ast.Call)
           and getattr(n.value.func, "id", None) == "_startup_step"]
    every = [n for n in ast.walk(tree) if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "_startup_step"]
    assert len(top) == len(every) == len(EXPECTED_STEPS), (len(top), len(every))
    assert tuple(c.args[0].value for c in top) == EXPECTED_STEPS
    last = tree.body[-1]
    assert isinstance(last, ast.Expr) and getattr(last.value.func, "id", None) == "_startup_total", "總耗時不是 main.py 最後一行"
