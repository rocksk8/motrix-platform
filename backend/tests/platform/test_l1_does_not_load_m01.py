"""CA-O4（M01-PLAN §3-8 ①）：L1 不 import M01——載入所有 L1 單位（`core:main` 除外：它掛載 router，② 之後改由載入器）
之後，M01 的單位一個都不在 `sys.modules`。M01 拿掉時 L1 仍載入它 ⇒ 它在 import 時登記的提供者會殘留（CA-O3 的前提）。

正對照：同一支探針改成也 import M01 的 router ⇒ 報出 M01 單位（探針不是永遠回空）。
"""
import json
import os
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
REPO = BACKEND.parent

_PROBE = r'''
import importlib, json, sys
mods, m01 = json.loads(sys.argv[1]), json.loads(sys.argv[2])
failed = {}
for m in mods:
    try:
        importlib.import_module(m)
    except Exception as e:                       # noqa: BLE001
        failed[m] = repr(e)[:200]
loaded = sorted(x for x in m01 if x in sys.modules)
print(json.dumps({"loaded": loaded, "failed": failed}))
'''


def _unit_to_module(u):
    kind, name = u.split(":", 1)
    if kind == "mod":                                  # 已搬進 modules/ 的單位（M01 ② 之後：mod:case/api/quotations）
        return "modules." + name.replace("/", ".").replace(".__init__", "")
    # plat:＝backend/core/*.py（L0 平台核心；稽核 D 觀察：原本沒有探到）
    return {"core": name, "helper": "helpers." + name, "router": "routers." + name, "plat": "core." + name}.get(kind)


def _groups():
    d = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))
    l1 = [m for m in map(_unit_to_module, d["L1"]["units"]) if m and m != "main"]
    m01 = [m for m in map(_unit_to_module, d["modules"]["M01"]["units"]) if m]
    return l1, m01


def _probe(mods, m01):
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
    r = subprocess.run([sys.executable, "-c", _PROBE, json.dumps(mods), json.dumps(m01)], cwd=str(BACKEND),
                       env=env, capture_output=True, text=True, encoding="utf-8", timeout=180)
    assert r.returncode == 0, r.stderr[-2000:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_importing_every_l1_unit_loads_no_m01_unit(client):
    l1, m01 = _groups()
    assert len(l1) > 40 and "modules.case.quotations" in m01
    out = _probe([m for m in l1 if m not in m01], m01)
    assert not out["failed"], out["failed"]
    assert out["loaded"] == [], "L1 載入了 M01 的單位（CA-O4）：%s" % out["loaded"]


def test_the_probe_covers_every_platform_core_unit(client):
    """反向控制（稽核 D）：modules.json 的每個 plat: 單位都在探針清單裡、而且真的被 import（沒有 import 失敗）。
    少了這題，plat: 對應漏掉時探針照樣綠——那時 core/ 就算 import 了 M01 也不會被抓到。"""
    import json
    d = json.loads((REPO / "docs" / "platform" / "modules.json").read_text(encoding="utf-8"))
    plats = ["core." + u.split(":", 1)[1] for u in d["L1"]["units"] if u.startswith("plat:")]
    l1, m01 = _groups()
    assert plats and set(plats) <= set(l1), sorted(set(plats) - set(l1))
    out = _probe(plats, m01)
    assert not out["failed"] and out["loaded"] == [], out


def test_rc_the_probe_reports_m01_when_it_is_imported(client):
    _l1, m01 = _groups()
    out = _probe(["helpers.dates", "modules.case.api.quotations"], m01)
    assert "modules.case.quotations" in out["loaded"] and "modules.case.api.quotations" in out["loaded"], out
