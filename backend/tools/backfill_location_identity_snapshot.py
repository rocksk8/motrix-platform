# -*- coding: utf-8 -*-
"""`QL25` §6：舊報價單一次補「據點身分」快照。

# 為什麼要有這支

`QL25` 讓報價單在**送出那一刻**把據點的抬頭五欄凍結進
`data_json["locationIdentity"]`——而這件事上線之前就已經送出的舊單，
從來沒有機會走到那個寫入點。`identity_for()`／`apply_snapshot()` 對
沒有快照的單會落回即時查（不會印空白），所以**不補也不會壞**，但補了
之後這些舊單的抬頭也會跟著凍結，不再隨著使用者之後修改據點設定而變。

# 🔴 時機：使用者填完設定之後才跑（A 裁）

現在很多據點的抬頭五欄可能還是空的（新功能剛上線）；若在那個狀態下跑，
補進去的快照內容也是空的，之後使用者才把設定填好，卻不會回頭更新已經
凍結的那些單。⇒ **這支不會在 migration 裡自動執行**，是一個手動觸發的
維運動作，等使用者確認設定填完了再跑。

# 🔴 判準：鍵在不在，不是值是不是空的

〈null 不等於 0〉的同一條——用 `"locationIdentity" not in d` 判斷「有沒有
快照」，不要用 `not d.get("locationIdentity")`。後者會把「快照存在但內容
剛好全空」誤判成「沒有快照」，讓這支腳本每跑一次都把那張單的快照換成
今天算出來的值——而它看起來完全正常，因為兩次算出來的值通常一樣，直到
使用者又改了一次據點設定，那張「內容全空的快照」才會被悄悄覆蓋成新值，
而那正是快照原本要擋住的事。

用法：
    cd backend
    python tools/backfill_location_identity_snapshot.py           # 先看會動到幾張單
    python tools/backfill_location_identity_snapshot.py --apply   # 真的寫入
"""
import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:                                            # noqa: BLE001
    pass

sys.path.insert(0, ".")

from db import get_db
from helpers.company_identity import snapshot_for, SNAPSHOT_KEY


def _candidates(conn):
    """對象：`status != '草稿'` 且 `data_json` 沒有 `locationIdentity` 鍵的單。"""
    out = []
    for row in conn.execute(
            "SELECT quote_no, location_id, data_json FROM quotations"
            " WHERE status != '草稿'"):
        try:
            d = json.loads(row["data_json"] or "{}")
        except (TypeError, ValueError):
            d = {}
        if SNAPSHOT_KEY not in d:
            out.append((row["quote_no"], row["location_id"] or "", d))
    return out


def main():
    apply = "--apply" in sys.argv[1:]
    conn = get_db()
    try:
        targets = _candidates(conn)
        print("找到 %d 張沒有快照的非草稿報價單。" % len(targets))
        if not targets:
            return
        if not apply:
            for quote_no, location_id, _d in targets[:20]:
                print("  %s（據點：%s）" % (quote_no, location_id or "主要據點"))
            if len(targets) > 20:
                print("  ……其餘 %d 張略。" % (len(targets) - 20))
            print("\n這是預覽，沒有寫入。確認過設定已填好之後，加 --apply 執行。")
            return
        for quote_no, location_id, d in targets:
            d[SNAPSHOT_KEY] = snapshot_for(location_id)
            conn.execute(
                "UPDATE quotations SET data_json=? WHERE quote_no=?",
                (json.dumps(d, ensure_ascii=False), quote_no))
        conn.commit()
        print("已補 %d 張。" % len(targets))
    finally:
        conn.close()


if __name__ == "__main__":
    main()
