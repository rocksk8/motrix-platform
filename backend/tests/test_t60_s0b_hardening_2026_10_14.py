# -*- coding: utf-8 -*-
"""T60 S0b（hichan-04 對 t59 的稽核）：
(a) GET /api/layout/{module} 對非最高管理者不再帶側欄操作（含改名文字與看不到的目標 id）；最高管理者照舊
(b) 含 hub 項的群組（system）不能當 move.to 的目的地：執行期（apply_layout_ex）、發布驗證（customization）、選單編輯器的下拉都排除"""
import json
import subprocess
import shutil
from pathlib import Path

import pytest

import db
from core import customization as C
from core import definitions as D
from core import menu as M
from core import registry

NODE = shutil.which("node")
ROOT = Path(__file__).resolve().parents[2]


def _login(client, make_user, name, role, modules=None):
    u, pw = make_user(username=name, role=role, **({"modules": modules} if modules is not None else {}))[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": pw}).json()["token"]}


def _pick():
    for m in registry.loaded():
        for p in (m.manifest or {}).get("pages") or []:
            perm = (p.get("menu") or {}).get("perm") if isinstance(p, dict) else None
            if isinstance(p, dict) and p.get("menu") and isinstance(perm, list) and perm \
                    and not ({"cashier", "finance", "financial_view"} & set(perm)):
                return m.key, p["path"]
    pytest.skip("沒有宣告模組權限的選單項")


# ── (a) ────────────────────────────────────────────────────────────────────────────────
def test_layout_endpoint_hides_sidebar_ops_from_non_superadmin(client, make_user):
    key, href = _pick()
    tgt = "%s:%s/sidebar" % (key, href)
    conn = db.get_db()
    try:
        D.save_draft(conn, "layout", "module:%s" % key, "company", {"ops": [{"op": "hide", "target": tgt}]}, user="t")
        D.publish(conn, "layout", "module:%s" % key, "company", note="t", user="t")
    finally:
        conn.close()
    h_sa = _login(client, make_user, "t60s0b_sa", "superadmin")
    h_none = _login(client, make_user, "t60s0b_none", "admin", modules=[])
    sa = client.get("/api/layout/" + key, headers=h_sa).json()
    none = client.get("/api/layout/" + key, headers=h_none).json()
    assert any(o.get("target") == tgt for o in sa["ops"]), "對照組：最高管理者仍看得到側欄操作"
    assert tgt not in json.dumps({"ops": none["ops"], "dropped": none["dropped"]}, ensure_ascii=False)     # points 是模組宣告（與公開的選單宣告同一份），不在此限
    assert set(none) == set(sa) and none["module"] == sa["module"] and none["points"] == sa["points"]      # 其餘欄位不變


# ── (b) ────────────────────────────────────────────────────────────────────────────────
def _groups_with_hub():
    return [{"key": "g", "label": "G", "items": [{"href": "a.html", "label": "A", "module": "ma"}]},
            {"key": "system", "label": "系統", "items": [{"href": "system-hub.html", "label": "系統中心", "hub": True},
                                                       {"href": "s.html", "label": "S", "module": "ms"}]}]


def test_hub_group_keys_come_from_the_l1_declaration():
    assert "system" in M.hub_group_keys() and "g" not in M.hub_group_keys()


def test_runtime_move_into_a_hub_group_is_skipped():
    op = {"op": "move", "target": "ma:a.html/sidebar", "to": "group:system"}
    out, applied, skipped = M.apply_layout_ex(_groups_with_hub(), [op], builder=True)
    assert applied == [] and len(skipped) == 1 and skipped[0]["op"] == op
    assert [it["href"] for g in out for it in g["items"]] == ["a.html", "system-hub.html", "s.html"]       # 沒有搬動
    ok, applied2, _ = M.apply_layout_ex(_groups_with_hub(), [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:g", "index": 0}], builder=True)
    assert len(applied2) == 1                                                                              # 對照：一般群組照常


def test_publish_validation_rejects_hub_group_destination():
    pt = [{"id": "ma:a.html/sidebar", "kind": "sidebar", "ops": list(C.OPS_BY_KIND["sidebar"])}]
    groups = [g["key"] for g in M.load_l1()["groups"]]
    normal = next(k for k in groups if k not in M.hub_group_keys())
    assert C._check_ops(pt, [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:system"}])
    msg = C._check_ops(pt, [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:system"}])[0]["message"]
    offered = msg.split("可選：")[1].split("）")[0].split("、")
    assert "system" not in offered and normal in offered                                                    # 可選清單不含 system、含一般群組
    assert not C._check_ops(pt, [{"op": "move", "target": "ma:a.html/sidebar", "to": "group:" + normal}])   # 對照：一般群組通過


@pytest.mark.skipif(not NODE, reason="需要 node")
def test_menu_editor_group_dropdown_excludes_hub_groups_except_the_current_one():
    src = (ROOT / "frontend" / "static" / "menu-editor.js").read_text(encoding="utf-8")
    assert "g.items.some(function (it) { return it.hub }) && g.key !== cur" in src
    harness = r"""
const sel = { children: [], appendChild(o) { this.children.push(o) } }
const el = (t, a) => Object.assign({ tag: t, selected: false }, a)
const st = { decl: [{ key: 'g', label: 'G', items: [{ href: 'a' }] }, { key: 'system', label: '系統', items: [{ href: 'h', hub: true }] }] }
function run(cur) {
  sel.children = []
  st.decl.forEach(function (g) {
    if (g.items.some(function (it) { return it.hub }) && g.key !== cur) return
    var o = el('option', { value: g.key, text: g.label }); if (g.key === cur) o.selected = true; sel.appendChild(o)
  })
  return sel.children.map(o => o.value)
}
console.log(JSON.stringify([run('g'), run('system')]))
"""
    out = subprocess.run([NODE, "-e", harness], capture_output=True, text=True, encoding="utf-8", timeout=30)
    assert json.loads(out.stdout.strip()) == [["g"], ["g", "system"]]
