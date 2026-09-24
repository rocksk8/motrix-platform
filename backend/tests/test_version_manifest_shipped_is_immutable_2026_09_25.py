"""版本紀錄：**已出貨的條目不可改號、改寫、刪除**（正式機基準的每一筆都要逐字留著）。

☠️ 2026-09-25 最終建包被 VR7 擋下：正式機（46dc6ae）的 manifest 有、master 沒有的三筆——
   傳票 2026-09-23c（被升號併進 24h）、獎金分潤 2026-09-24b（併進 24l）、營運報表 2026-09-12（併進 24k）；
   另有三筆（系統訊息 24c、地圖與距離 22b、標案雷達 22a）被在後面**追加**新的行。
   正式機資料庫有那幾筆、manifest 沒有 ⇒ 重建或災難還原之後永久消失；
   追加的行則讓「那一版出貨了什麼」被事後改寫。
   VR1～VR3 都綠：它們驗「有沒有寫」「一個模組一筆」，沒有一題驗「舊的還在不在、有沒有被改」。

🔑 判準：正式機基準 manifest 的每一筆，在目前的 manifest 裡以 (module, version) 找得到，
   而且 date、time、content 逐字相同。新增條目不受限制。
📌 基準常數在 `tests/_prod_baseline.py`，每次部署後要更新成新的正式機 commit。
"""
import json
from pathlib import Path

from tests._prod_baseline import BASELINE, baseline_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "backend" / "version_manifest.json"
FIELDS = ("date", "time", "content")


def shipped_violations(baseline, current):
    """回傳違規清單（空＝沒有違規）。純函式。"""
    cur = {(e.get("module"), e.get("version")): e for e in current}
    bad = []
    for b in baseline:
        k = (b.get("module"), b.get("version"))
        c = cur.get(k)
        if c is None:
            bad.append("%s %s：已出貨的條目不見了（被刪除、改號或併進別筆）" % k)
            continue
        changed = [f for f in FIELDS if b.get(f) != c.get(f)]
        if changed:
            bad.append("%s %s：已出貨的條目被改寫（%s）" % (k + ("、".join(changed),)))
    return bad


def test_every_shipped_entry_is_still_there_unchanged():
    base = baseline_manifest()
    cur = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    bad = shipped_violations(base, cur)
    assert not bad, (
        "已出貨的版本紀錄被動過（正式機資料庫有它，重建／還原後會消失或對不上）：\n  " + "\n  ".join(bad)
        + "\n⇒ 從 `git show %s:backend/version_manifest.json` 逐字還原；"
          "新的改動寫成新條目，不要改舊的。" % BASELINE)


def test_the_guard_catches_delete_renumber_rewrite_and_append_but_not_additions():
    """正對照（四種動法都要抓到）＋反向控制（新增條目不算違規）。"""
    a = {"module": "傳票", "version": "2026-09-23c", "date": "2026-09-23", "time": "01:35", "content": "甲\n乙"}
    b = {"module": "報表", "version": "2026-09-12", "date": "2026-09-12", "time": "01:30", "content": "丙"}
    base = [a, b]
    assert shipped_violations(base, [a, b]) == []
    assert shipped_violations(base, [a, b, {"module": "新", "version": "2026-09-26a", "date": "2026-09-26",
                                            "time": "00:00", "content": "丁"}]) == []
    assert len(shipped_violations(base, [a])) == 1                                     # 刪除
    assert len(shipped_violations(base, [a, dict(b, version="2026-09-24k")])) == 1      # 改號
    assert len(shipped_violations(base, [a, dict(b, content="丙改")])) == 1              # 改寫
    assert len(shipped_violations(base, [dict(a, content="甲\n乙\n追加"), b])) == 1      # 追加
    assert len(shipped_violations(base, [dict(a, module="傳票/新"), b])) == 1            # 改模組名
