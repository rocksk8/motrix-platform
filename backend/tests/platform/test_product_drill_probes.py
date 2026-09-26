"""產品演練（tools/platform/product_drill.py）的模組端點判定（稽核 ⑰ M-3）。

演練原本把 `provides.api_prefixes` 的前綴本身當端點打：前綴常常不是路由（`/api/dashboard`、`/api/reports`
在模組在時也 404）⇒ 完整產品假紅、模組被排除時假綠。改成讀模組自己宣告的 `provides.probes`。
- 宣告了：每一支都必須是**真的 GET 路由**、落在該模組自己的前綴底下、模組在時回 200（否則演練判不準）
- 沒宣告：不打、不判紅，但一定列在 `undeclared_probes`（主持過渡裁示：唯讀動作的缺口要輸出，不可以靜默略過）
"""
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO / "tools" / "platform"))
import product_drill as PD  # noqa: E402


def _mod(root, key, provides, pages=()):
    d = root / key
    d.mkdir(parents=True)
    (d / "module.json").write_text(json.dumps({"key": key, "provides": provides,
                                               "pages": [{"path": p} for p in pages]}), encoding="utf-8")


def test_rc_plan_uses_declared_probes_and_lists_modules_without_them(tmp_path):
    """合成樹（不綁真實模組）：有宣告 ⇒ 打那幾支；沒宣告（新模組）⇒ 不打端點、但列在清單；頁面照驗。"""
    _mod(tmp_path, "aa", {"api_prefixes": ["/api/aa"], "probes": ["/api/aa/list"]}, pages=["aa.html"])
    _mod(tmp_path, "zz_new", {"api_prefixes": ["/api/zz"]}, pages=["zz.html"])
    plan, undeclared = PD.probe_plan(tmp_path, {"modules": {"aa": {}}})
    assert undeclared == ["zz_new"]
    assert ("aa", True, "GET", "/api/aa/list") in plan
    assert not [x for x in plan if x[0] == "zz_new" and x[2] == "GET"], "沒宣告 probe 的模組不可以拿前綴去猜端點"
    assert ("zz_new", False, "page", "zz.html") in plan
    assert not [x for x in plan if x[3] in ("/api/aa", "/api/zz")], "前綴本身不是端點"


def _installed_probes():
    from core import source_tree
    out = []
    for d in source_tree.module_dirs():
        m = json.loads((d / "module.json").read_text(encoding="utf-8"))
        prov = m.get("provides") or {}
        for p in prov.get("probes") or []:
            out.append((d.name, p, tuple(prov.get("api_prefixes") or ())))
    return out


def test_declared_probes_are_real_get_routes_under_the_modules_prefixes(client):
    from tests._routes import all_routes
    probes = _installed_probes()
    if not probes:
        pytest.skip("已安裝的模組都沒有宣告 probes ⇒ 無對象（演練輸出會列出 undeclared_probes）")
    gets = {p for p, methods, _r in all_routes(client.app) if "GET" in methods}
    for key, path, prefixes in probes:
        assert path in gets, "%s 的 probe %s 不是註冊中的 GET 路由" % (key, path)
        assert any(path == pre or path.startswith(pre.rstrip("/") + "/") for pre in prefixes), (
            "%s 的 probe %s 不在它自己的前綴 %s 底下" % (key, path, prefixes))


def test_declared_probes_answer_200_when_the_module_is_installed(client, make_user):
    """演練在「模組在」時要求 200：用最高管理者打一次（假設換成要參數的端點，這裡就會先紅）。"""
    probes = _installed_probes()
    if not probes:
        pytest.skip("已安裝的模組都沒有宣告 probes ⇒ 無對象")
    u, pw = make_user(username="drill_probe_sa", role="superadmin")
    tok = client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]
    for key, path, _pre in probes:
        r = client.get(path, headers={"Authorization": "Bearer " + tok})
        assert r.status_code == 200, "%s 的 probe %s 回 %s：%s" % (key, path, r.status_code, r.text[:150])
