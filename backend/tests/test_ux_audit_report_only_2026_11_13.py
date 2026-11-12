# -*- coding: utf-8 -*-
"""UX 守門報告（P0）的契約題：**只驗『工具會動、讀得到東西、設定檔合法』，不驗任何閾值**（P0 只出報告、不擋 CI；PM 2026-11-13）。

- 正對照：在暫存的假 frontend 放已知的壞東西，工具必須逐項抓到（否則『0 筆』可能只是掃不到）。
- 真實倉庫：掃得到足夠多頁、報告結構完整；不對『多少筆』下斷言（那是 ratchet 的事，由 `ux_audit.py --check` 手動跑）。
"""
import json
import os
import sys

import pytest

HERE = os.path.dirname(os.path.abspath(__file__))
BACKEND = os.path.abspath(os.path.join(HERE, ".."))
REPO = os.path.abspath(os.path.join(BACKEND, ".."))
sys.path.insert(0, os.path.join(BACKEND, "tools"))
import ux_audit as UA  # noqa: E402


def _write(root, rel, text):
    p = os.path.join(root, *rel.split("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


BAD_PAGE = """<!doctype html><html><body>
<!-- 待審核 在註解裡，不應計入 -->
<div class="pg"><div class="pg__l"><h1 class="pg__t">測試頁</h1></div>
 <div class="pg__a"><button class="btn btn-primary">新增</button><button class="btn btn-primary">匯出</button></div></div>
<p style="color:red">這張單是待審核，請看 token 與 SMTP 設定</p>
<input placeholder="輸入刪除暫存區">
<span x-text="'等我簽核'"></span>
<table><tr><th>A</th><th>B</th></tr></table>
<script>
const s = '待審核'; const n = (1234).toLocaleString('zh-TW');
</script>
</body></html>
"""


def test_positive_control_scanner_finds_known_bad_things(tmp_path):
    root = str(tmp_path)
    _write(root, "frontend/pages/bad.html", BAD_PAGE)
    _write(root, "frontend/pages/notification-settings.html", "<p>請貼上 Channel access token</p>")
    cfg = UA.load_config()
    rep = UA.run(root, cfg)
    e = rep["files"]["frontend/pages/bad.html"]
    assert e["has_pg_header"] and e["h1_count"] == 1
    assert e["primary_in_header"] == 2 and e["primary_in_header_over1"] == 1
    assert e["inline_styles"] == 1 and e["to_locale_string"] == 1 and e["th_count"] == 2
    d = e["deprecated"]
    assert d["待審核"]["text"] == 1 and d["待審核"]["js"] == 1, "註解不計、畫面文字與 JS 字串分開計"
    assert d["刪除暫存區"]["text"] == 1, "placeholder 屬性要算畫面文字"
    assert d["等我簽核"]["text"] == 1, "x-text 內的字串字面要算畫面文字"
    assert e["forbidden"]["token"]["text"] == 1 and e["forbidden"]["SMTP"]["text"] == 1
    # 白名單：LINE 設定頁可出現 token／channel
    w = rep["files"]["frontend/pages/notification-settings.html"]
    assert w["forbidden"] == {} and w["forbidden_hits"] == 0
    # 報告可輸出、ratchet 比對可跑
    md = UA.to_markdown(rep, cfg, [])
    assert "待審核" in md and "UX 守門報告" in md
    base = UA.baseline_view(rep, cfg)
    assert UA.compare(rep, base, cfg) == []
    worse = json.loads(json.dumps(base))
    worse["files"]["frontend/pages/bad.html"]["inline_styles"] = 0
    probs = UA.compare(rep, worse, cfg)
    assert probs and probs[0][1] == 0 and probs[0][2] == 1, "現在 > 基準 ＝ 倒退"


def test_real_repo_report_is_produced_and_well_formed():
    cfg = UA.load_config()
    rep = UA.run(REPO, cfg)
    assert rep["html_files"] >= 60, "frontend 的 HTML 頁應掃到 60 頁以上（掃不到＝路徑壞了，不是『沒問題』）"
    for k in ("inline_styles", "to_locale_string", "forbidden_hits", "primary_in_header_over1", "th_count"):
        assert k in rep["totals"]
    sv = rep["status_vocab"]
    assert sv["error"] is None and len(sv["js_map_keys"]) >= 10 and len(sv["table_keys"]) >= 20
    assert "# UX 守門報告" in UA.to_markdown(rep, cfg)


def test_config_is_valid_and_covers_user_decisions():
    cfg = UA.load_config()
    terms = {t["term"]: t["use"] for t in cfg["deprecated_terms"]}
    # 使用者 2026-11-13 的四項用詞裁示必須在清單內
    assert terms["待審核"] == "待簽核" and terms["刪除暫存區"] == "資源回收筒" and terms["歷史紀錄"] == "操作紀錄"
    assert "審核中" in terms and "等我簽核" in terms
    forb = {t["term"] for t in cfg["forbidden_terms"]}
    assert {"token", "SMTP", "Schema", "Callback URL", "channel"} <= forb
    wl = cfg["whitelist"]
    assert {"token", "channel"} <= set(wl["notification-settings.html"]), "LINE 設定卡片需要白名單（hichan-6 評審）"
    assert all(isinstance(v, list) for k, v in wl.items() if not k.startswith("_"))


@pytest.mark.parametrize("html,expect", [
    ('<div class="pg__a"><div><button class="btn-primary">a</button></div></div><button class="btn-primary">x</button>', 1),
    ('<div class="pg__a"></div><button class="btn-primary">x</button>', 0),
    ('<!-- <div class="pg__a"><b class="btn-primary"></b></div> -->', 0),
])
def test_primary_in_header_counts_only_inside_pg_a(html, expect):
    assert UA.primary_in_header(html) == expect
