# -*- coding: utf-8 -*-
"""時間不確定性守門（2026-10-01，第二十六～二十七班建包連敗七次的教訓；PLAYBOOK §G5 第 20 項）。

三道靜態棘輪（基線 clock_ratchet_baseline.json：{規則: {檔案: 次數}}，只准變少；變少了要同一個 commit 更新基線）：
  clock  `parametrize` 裝飾器內、模組層級／類別層級常數裡，呼叫 date.today／datetime.now／datetime.today／utcnow／time.time
         ⇒ 收集時就取值：xdist 各 worker 算出不同的 id（收集不一致）、或收集與執行之間跨午夜（預期值差一天）。
  zip    測試裡 `zf.writestr("名稱", …)`（沒給 ZipInfo date_time）、`ZipInfo("名稱")`（沒給 date_time）
         ⇒ zip 位元組帶「現在時間」，進參數 id／雜湊比對就每次不同（upload_magic，2026-10-01 建包卡在這）。
  重產基線：python backend/tests/platform/test_clock_gates_2026_10_01.py --update

另有：tests/_clock.py 行為題、date_sensitive 清單的檔案都存在、時鐘接縫還在（接縫被改名 ⇒ install_seams 靜默失效）。
"""
import ast
import json
import os
import subprocess
import sys
import warnings
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
BACKEND = REPO / "backend"
BASELINE = Path(__file__).with_name("clock_ratchet_baseline.json")
if str(BACKEND) not in sys.path:      # 直接執行 --update 時 tests 套件要找得到
    sys.path.insert(0, str(BACKEND))
SKIP_PARTS = {"__pycache__", "node_modules", ".git"}
TIME_BASES = {"date", "datetime"}
TIME_MODS = {"time", "_time"}


# ── 掃描 ─────────────────────────────────────────────────────────────────────────

def _tail(node):
    """Name／Attribute 的最後一段名字；否則 None。"""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def is_time_call(node):
    """date.today()／datetime.now()／datetime.today()／datetime.utcnow()／time.time()（任何別名前綴：_dt.date.today、datetime.datetime.now）。"""
    if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
        return False
    attr, base = node.func.attr, _tail(node.func.value)
    if attr in ("today", "now", "utcnow") and base in TIME_BASES:
        return True
    return attr == "time" and base in TIME_MODS


def _time_calls_in(node):
    """node 底下的時間呼叫；lambda／函式本體不算（定義時不執行）。"""
    n, stack = 0, [node]
    while stack:
        cur = stack.pop()
        if isinstance(cur, (ast.Lambda, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if is_time_call(cur):
            n += 1
        stack.extend(ast.iter_child_nodes(cur))
    return n


def _is_parametrize(dec):
    return isinstance(dec, ast.Call) and _tail(dec.func) == "parametrize"


def count_clock(tree):
    """收集期取值的時間呼叫數：parametrize 裝飾器＋模組層級／類別層級的常數（Assign／AnnAssign／AugAssign）。"""
    total = 0

    def decorators(n):
        return [d for d in getattr(n, "decorator_list", []) if _is_parametrize(d)]

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            for d in decorators(node):
                total += _time_calls_in(d)

    def const_stmts(body):
        n = 0
        for st in body:
            if isinstance(st, (ast.Assign, ast.AnnAssign, ast.AugAssign)) and getattr(st, "value", None) is not None:
                n += _time_calls_in(st.value)
            elif isinstance(st, ast.ClassDef):
                n += const_stmts(st.body)
            elif isinstance(st, (ast.If, ast.Try)):
                n += const_stmts(st.body) + const_stmts(getattr(st, "orelse", []))
        return n
    return total + const_stmts(tree.body)


def count_zip(tree):
    """`x.writestr(<不是 ZipInfo>, …)`、`ZipInfo(name)`（沒有 date_time）各算一處。"""
    zipinfo_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call) and _tail(node.value.func) == "ZipInfo":
            zipinfo_names |= {t.id for t in node.targets if isinstance(t, ast.Name)}
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if _tail(node.func) == "ZipInfo":
            has_dt = len(node.args) >= 2 or any(k.arg == "date_time" for k in node.keywords)
            total += 0 if has_dt else 1
        elif isinstance(node.func, ast.Attribute) and node.func.attr == "writestr" and node.args:
            a0 = node.args[0]
            if isinstance(a0, ast.Call) and _tail(a0.func) == "ZipInfo":
                continue                 # ZipInfo(...) 自己會被上面那個分支檢查
            if isinstance(a0, ast.Name) and a0.id in zipinfo_names:
                continue
            total += 1
    return total


def scan_file(path):
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")      # 別人測試檔裡的 "\s" 之類 SyntaxWarning 與本守門無關
            tree = ast.parse(Path(path).read_text(encoding="utf-8-sig"), filename=str(path))
    except (SyntaxError, ValueError, OSError):
        return 0, 0
    return count_clock(tree), count_zip(tree)


def iter_test_files(repo=REPO):
    """backend/tests（含 platform）與 backend/modules/*/tests 的 .py。"""
    roots = [Path(repo) / "backend" / "tests"] + sorted((Path(repo) / "backend" / "modules").glob("*/tests"))
    for root in roots:
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.py")):
            rel = p.relative_to(repo)
            if not (SKIP_PARTS & set(rel.parts)) and not any(x.startswith(".venv") for x in rel.parts):
                yield p, rel.as_posix()


def scan(repo=REPO):
    out = {"clock": {}, "zip": {}}
    for p, rel in iter_test_files(repo):
        c, z = scan_file(p)
        if c:
            out["clock"][rel] = c
        if z:
            out["zip"][rel] = z
    return out


def problems(found, baseline, installed=None):
    """⇒ 訊息清單。多於基線＝紅；少於基線＝也紅（棘輪：同一個 commit 更新基線，免得空出的額度被別人用掉）。
    installed：已安裝的模組 key 集合——模組沒裝（core-only 反向控制、產品選配）的檔不算降低。"""
    msgs = []
    hint = {"clock": "收集期取時間（parametrize／模組層級常數）⇒ 改在測試函式內用 tests._clock.today()／now()",
            "zip": "zip 沒有固定時間戳 ⇒ writestr(zipfile.ZipInfo(name, date_time=(2020, 1, 1, 0, 0, 0)), data)"}
    for rule in ("clock", "zip"):
        f, b = found.get(rule, {}), baseline.get(rule, {})
        for path, n in sorted(f.items()):
            if n > b.get(path, 0):
                msgs.append("[%s] %s：%d 處（基線 %d）——%s" % (rule, path, n, b.get(path, 0), hint[rule]))
        for path, bn in sorted(b.items()):
            parts = path.split("/")
            if installed is not None and parts[:3] == ["backend", "modules", parts[2] if len(parts) > 2 else ""] and len(parts) > 2 \
                    and parts[2] not in installed:
                continue
            if f.get(path, 0) < bn:
                msgs.append("[%s] %s：降到 %d 處（基線 %d）⇒ 同一個 commit 更新基線（--update）" % (rule, path, f.get(path, 0), bn))
    return msgs


def _installed(repo=REPO):
    d = Path(repo) / "backend" / "modules"
    return {p.name for p in d.iterdir() if (p / "module.json").is_file()} if d.is_dir() else set()


def _baseline():
    return json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.is_file() else {"clock": {}, "zip": {}}


# ── 真實題 ─────────────────────────────────────────────────────────────────────────

def test_clock_and_zip_ratchets_only_go_down():
    msgs = problems(scan(), _baseline(), _installed())
    assert not msgs, "\n".join(msgs)


# ── 掃描器本身（合成輸入；含反向控制）──────────────────────────────────────────────────

def _cc(src):
    return count_clock(ast.parse(src))


def test_scanner_flags_collection_time_clock_reads():
    assert _cc("import pytest\n@pytest.mark.parametrize('d', [date.today()])\ndef test_a(d): pass") == 1
    assert _cc("@pytest.mark.parametrize('d', [datetime.now(), time.time()])\ndef test_a(d): pass") == 2
    assert _cc("D = datetime.datetime.now()") == 1
    assert _cc("NOW: float = time.time()") == 1
    assert _cc("X = (_dt.date.today() - _dt.timedelta(days=1)).isoformat()") == 1
    assert _cc("class T:\n    Y = date.today()\n") == 1
    assert _cc("try:\n    Z = datetime.today()\nexcept Exception:\n    Z = None\n") == 1
    assert _cc("Z = datetime.utcnow()") == 1


def test_scanner_ignores_run_time_reads():
    assert _cc("def test_a():\n    d = date.today()\n    assert d\n") == 0
    assert _cc("F = lambda: date.today()") == 0
    assert _cc("def helper():\n    return datetime.now()\n") == 0
    assert _cc("@pytest.mark.parametrize('x', [1, 2])\ndef test_a(x):\n    t = time.time()\n") == 0
    assert _cc("@pytest.fixture\ndef f():\n    return date.today()\n") == 0
    assert _cc("X = clock.today()") == 0 and _cc("X = obj.time()") == 0


def _cz(src):
    return count_zip(ast.parse(src))


def test_zip_scanner():
    assert _cz("z.writestr('a.txt', 'x')") == 1
    assert _cz("z.writestr(name, 'x')") == 1
    assert _cz("z.writestr(zipfile.ZipInfo('a', date_time=(2020,1,1,0,0,0)), 'x')") == 0
    assert _cz("zi = zipfile.ZipInfo('a', (2020,1,1,0,0,0))\nz.writestr(zi, 'x')") == 0
    assert _cz("zi = ZipInfo('a')\nz.writestr(zi, 'x')") == 1, "ZipInfo(name) 沒給 date_time 卻沒被抓到"
    assert _cz("z.writestr(zipfile.ZipInfo('a'), 'x')") == 1
    assert _cz("z.write('f.txt')") == 0


def test_problems_flags_growth_and_unrecorded_shrink():
    base = {"clock": {"backend/tests/a.py": 2}, "zip": {}}
    assert not problems({"clock": {"backend/tests/a.py": 2}, "zip": {}}, base)
    assert problems({"clock": {"backend/tests/a.py": 3}, "zip": {}}, base), "增加沒被擋"
    assert problems({"clock": {"backend/tests/b.py": 1}, "zip": {}}, {"clock": {}, "zip": {}}), "新檔 0 額度卻被放過"
    assert problems({"clock": {}, "zip": {}}, base), "降低了卻沒更新基線（額度會被別人用掉）"
    assert not problems({"clock": {}, "zip": {}}, {"clock": {"backend/modules/gone/tests/x.py": 1}, "zip": {}}, installed={"case"}), \
        "模組沒裝時，該模組的檔不在不算降低"
    assert problems({"clock": {}, "zip": {"backend/tests/z.py": 1}}, {"clock": {}, "zip": {}}), "zip 規則沒生效"


def test_scanner_reads_real_files(tmp_path):
    (tmp_path / "backend" / "tests").mkdir(parents=True)
    (tmp_path / "backend" / "tests" / "test_x.py").write_text(
        "import zipfile\nD = date.today()\ndef test_a():\n    zipfile.ZipFile('x','w').writestr('a','b')\n", encoding="utf-8")
    got = scan(tmp_path)
    assert got == {"clock": {"backend/tests/test_x.py": 1}, "zip": {"backend/tests/test_x.py": 1}}


# ── tests/_clock.py ────────────────────────────────────────────────────────────────

from tests import _clock  # noqa: E402


def test_clock_returns_fixed_day_at_noon_when_env_is_set(monkeypatch):
    monkeypatch.setenv(_clock.ENV, "2026-02-28")
    assert _clock.today().isoformat() == "2026-02-28"
    n = _clock.now()
    assert (n.year, n.month, n.day, n.hour, n.minute, n.second) == (2026, 2, 28, 12, 0, 0)


def test_clock_is_the_real_clock_without_the_env(monkeypatch):
    monkeypatch.delenv(_clock.ENV, raising=False)
    from datetime import date, datetime
    assert _clock.today() == date.today() and abs((_clock.now() - datetime.now()).total_seconds()) < 5
    monkeypatch.setenv(_clock.ENV, "  ")
    assert _clock.fixed_date() is None


@pytest.mark.parametrize("bad", ["2026/09/30", "20260930", "tomorrow", "2026-13-01", "2026-02-30"])
def test_clock_rejects_a_bad_env_value_loudly(monkeypatch, bad):
    monkeypatch.setenv(_clock.ENV, bad)
    with pytest.raises(ValueError):
        _clock.today()


class _Mod:
    pass


def test_install_seams_swaps_only_existing_seams_and_only_when_set(monkeypatch):
    a, b = _Mod(), _Mod()
    a.today = lambda: "real"
    b.now_dt = lambda: "real"
    seams = (("m.a", "today", "date"), ("m.b", "now_dt", "datetime"), ("m.gone", "today", "date"), ("m.a", "missing", "date"))
    mods = {"m.a": a, "m.b": b}
    monkeypatch.delenv(_clock.ENV, raising=False)
    assert _clock.install_seams(monkeypatch, seams, mods) == [] and a.today() == "real", "沒設環境變數卻換了時鐘"
    monkeypatch.setenv(_clock.ENV, "2026-10-31")
    done = _clock.install_seams(monkeypatch, seams, mods)
    assert done == ["m.a.today", "m.b.now_dt"]
    assert a.today().isoformat() == "2026-10-31" and b.now_dt().isoformat() == "2026-10-31T12:00:00"


def test_the_known_product_seams_still_exist():
    """接縫被改名／拿掉 ⇒ install_seams 靜默不換（fixture 不吵）⇒ 這裡要看得見。tender_radar 沒裝就略過那兩個。"""
    import importlib
    for mod_name, attr, _ in _clock.SEAMS:
        if mod_name.startswith("modules.") and mod_name.split(".")[1] not in _installed():
            continue
        assert hasattr(importlib.import_module(mod_name), attr), "%s.%s 不見了：更新 tests/_clock.SEAMS" % (mod_name, attr)


def test_bad_test_today_stops_the_whole_run_before_any_test(tmp_path):
    """整合題：MOTRIX_TEST_TODAY 不合法 ⇒ pytest 直接 UsageError（exit 4），不會跑題後才靜默退回真實時間。"""
    from tests._subproc import run_python, utf8_env
    t = tmp_path / "t"
    t.mkdir()
    (t / "test_x.py").write_text("def test_ok():\n    assert True\n", encoding="utf-8")
    from tests._subproc import probe_pytest_args
    env = utf8_env(MOTRIX_TEST_TODAY="not-a-date", MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"))
    p = run_python(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp=%s" % (tmp_path / "bt-adhoc"),
                    *probe_pytest_args(t / "test_x.py")], cwd=str(BACKEND), env=env, timeout=120)
    assert p.returncode == 4 and "MOTRIX_TEST_TODAY" in (p.stdout + p.stderr), (p.returncode, (p.stdout + p.stderr)[-500:])
    env = utf8_env(MOTRIX_TEST_TODAY="2026-09-30", MOTRIX_PYTEST_LOCK=str(tmp_path / "lock"))
    p = run_python(["-m", "pytest", "-q", "-p", "no:cacheprovider", "--basetemp=%s" % (tmp_path / "bt2-adhoc"),
                    *probe_pytest_args(t / "test_x.py")], cwd=str(BACKEND), env=env, timeout=120)
    assert p.returncode == 0, (p.stdout + p.stderr)[-500:]


# ── date_sensitive 清單 ──────────────────────────────────────────────────────────────

def _manifest():
    d = json.loads((BACKEND / "tests" / "date_sensitive.json").read_text(encoding="utf-8-sig"))
    return {k: v for k, v in d.items() if not k.startswith("_")}


def test_date_sensitive_manifest_points_at_real_files_with_reasons():
    m = _manifest()
    assert len(m) >= 15
    installed = _installed()
    for rel, why in m.items():
        parts = rel.split("/")
        if parts[0] == "modules" and parts[1] not in installed:
            continue
        assert (BACKEND / rel).is_file(), "date_sensitive.json 列的檔不存在（改名／刪除了？）：%s" % rel
        assert why.strip()


def test_marker_is_registered_and_applied_from_the_manifest(pytester=None):
    import conftest
    assert "tests/test_monthly_backup_2026_09_14.py" in conftest._date_sensitive_manifest()

    class Item:
        def __init__(self, path):
            self.path, self.marks = path, []

        def add_marker(self, m):
            self.marks.append(m.name)
    a = Item(BACKEND / "tests" / "test_monthly_backup_2026_09_14.py")
    b = Item(BACKEND / "tests" / "test_some_other_file.py")
    conftest._apply_date_sensitive([a, b])
    assert a.marks == ["date_sensitive"] and b.marks == [], "清單裡的檔沒被標記／清單外的被標記"
    assert "date_sensitive" in (BACKEND / "pytest.ini").read_text(encoding="utf-8-sig"), "標記沒有登記在 pytest.ini"


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass
    if "--update" in (argv if argv is not None else sys.argv[1:]):
        data = scan()
        BASELINE.write_text(json.dumps(data, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print("基線已更新：clock %d 檔／%d 處，zip %d 檔／%d 處" % (len(data["clock"]), sum(data["clock"].values()),
                                                           len(data["zip"]), sum(data["zip"].values())))
        return 0
    print(json.dumps(scan(), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
