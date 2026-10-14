# -*- coding: utf-8 -*-
"""C2：案件頁「執行管理」分頁的子分頁（執行進度、材料申請、設備登錄、保固備註、待辦事項、成員）接上版面引擎（list `execTabs`）。
登記／綁定／核心（執行進度）、OFF 中性（node）、ON 順序與隱藏（node＋真的 runtime）、被隱藏的目前子分頁退回「執行進度」、金額遮蔽不受影響。"""
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from core import customization, source_tree

ROOT = Path(__file__).resolve().parents[3]
NODE = shutil.which("node")
PAGE = "case-management.html"
BASE = "/api/definitions/layout/module:case"
SUB = ["progress", "materials", "devices", "warranty", "todos", "info"]


def _page():
    return source_tree.page_file(PAGE).read_text(encoding="utf-8")


def _manifest():
    return json.loads((ROOT / "backend" / "modules" / "case" / "module.json").read_text(encoding="utf-8"))


def test_manifest_and_bindings():
    m = _manifest()
    assert customization.validate_manifest(m) == []
    pg = [p for p in m["customization"]["pages"] if p["page"] == PAGE][0]
    lst = [x for x in pg["lists"] if x["key"] == "execTabs"][0]
    assert lst["entity"] == "subtab" and [c["field"] for c in lst["columns"]] == SUB
    flags = {f["key"]: f["core"] for f in m["customization"]["fields"]["subtab"]}
    assert list(flags) == SUB and {k for k, v in flags.items() if v} == {"progress"}
    src = _page()
    bar = src[src.index('<div class="cm-subtabs"'):src.index("</div>", src.index('<div class="cm-subtabs"'))]
    assert 'x-effect="subFix()"' in bar
    for k in SUB:
        assert "sShown('%s')" % k in bar and "sOrder('%s')" % k in bar and "sLabel('%s'," % k in bar, k
    assert re.findall(r"'([^']+)'", re.search(r"execTabs:\s*\[([^\]]*)\]", src).group(1)) == SUB
    # 子分頁的內容區（x-show="execSubTab===…"）沒有被動到（隱藏頁籤不改功能）
    assert src.count("x-show=\"execSubTab==='") == 6


def _node(body, cols="[]"):
    from modules.case.tests import test_bp1_layout_cases_2026_10_14 as T
    return T._node(body, cols)


@pytest.mark.skipif(NODE is None, reason="沒有 node")
def test_off_neutral_on_follows_layout_and_hidden_current_subtab_falls_back():
    r = _node("console.log(JSON.stringify({ s: SUB.map(f => o.sShown(f)), ord: o.sOrder('devices'), lab: o.sLabel('devices', '設備登錄') }))".replace("SUB", json.dumps(SUB)))
    assert r == {"s": [True] * 6, "ord": {}, "lab": "設備登錄"}
    cols = json.dumps([{"field": f} for f in ("progress", "todos", "devices", "info")])         # 材料申請、保固備註被隱藏；待辦事項換到前面
    r = _node("o.layoutOn = true\nconst out = { s: SUB.map(f => o.sShown(f)), ord: ['progress','todos','devices','info'].map(f => o.sOrder(f)) }\n"
              "o.execSubTab = 'materials'; o.subFix(); out.hidden = o.execSubTab\n"
              "o.execSubTab = 'devices'; o.subFix(); out.visible = o.execSubTab\n"
              "o.execSubTab = 'zzz'; o.subFix(); out.unknown = o.execSubTab\n"
              "o.layoutOn = false; o.execSubTab = 'materials'; o.subFix(); out.off = o.execSubTab\n"
              "console.log(JSON.stringify(out))".replace("SUB", json.dumps(SUB)), cols)
    assert r["s"] == [True, False, True, False, True, True] and r["ord"] == [{"order": 1}, {"order": 2}, {"order": 3}, {"order": 4}]
    assert (r["hidden"], r["visible"], r["unknown"], r["off"]) == ("progress", "devices", "zzz", "materials")


def _h(client, make_user, name):
    u, p = make_user(name, "Lay-Pass-123", role="superadmin")[:2]
    return {"Authorization": "Bearer " + client.post("/api/auth/login", json={"username": u, "password": p}).json()["token"]}


def _col(f):
    return "case:%s/list:execTabs/column:%s" % (PAGE, f)


def _publish(client, h, ops):
    r = client.put(BASE + "/draft", headers=h, params={"scope": "company"}, json={"body": {"ops": ops}})
    assert r.status_code == 200, r.text
    return client.post(BASE + "/publish", headers=h, params={"scope": "company"}, json={"note": "t"})


def test_progress_is_core_the_rest_can_be_hidden_renamed_and_restored(client, make_user):
    boss = _h(client, make_user, "c2_boss")
    assert _publish(client, boss, [{"op": "hide", "target": _col("progress")}]).status_code == 422
    assert _publish(client, boss, [{"op": "relabel", "target": _col("progress"), "label": "x"}]).status_code == 422
    v1 = [{"op": "hide", "target": _col("warranty")}]
    v2 = [{"op": "relabel", "target": _col("info"), "label": "專案成員"}]
    assert _publish(client, boss, v1).status_code == 200 and _publish(client, boss, v2).status_code == 200
    mine = lambda: [o for o in client.get("/api/layout/case", headers=boss).json()["ops"] if "/list:execTabs/" in o["target"]]      # noqa: E731
    assert mine() == v2
    assert client.post(BASE + "/restore/1", headers=boss, params={"scope": "company"}, json={"note": "b"}).status_code == 200
    assert mine() == v1


def test_flag_gated_x_show_has_no_static_inline_display():
    bad = []
    for m in re.finditer(r"<[a-zA-Z][^<>]*?>", _page(), re.S):
        tag = m.group(0)
        xs = re.search(r'x-show="([^"]*)"', tag)
        if not xs or not re.search(r"\b[a-zA-Z]Shown\(", xs.group(1)):
            continue
        st = re.search(r'(?<![:\w-])style="([^"]*)"', tag)
        if st and re.search(r"(^|;)\s*display\s*:", st.group(1)):
            bad.append(re.sub(r"\s+", " ", tag)[:120])
    assert not bad, bad
