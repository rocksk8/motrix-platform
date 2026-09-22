# -*- coding: utf-8 -*-
"""VR7 · 版本紀錄的**反方向**：資料庫裡有而 `version_manifest.json` 沒有的，要擋下來。

Step 1.6（`build_deploy_package.ps1`）守的是一個方向：
```
manifest 舊於這一包的 commit   ⇒ 有人出貨而沒有寫紀錄
```
⚠️ A-2 在 2026-09-22 指出它只守一半。另一半是：

```
manifest 有、DB 沒有   正常 —— 服務還沒重啟，下次開機會同步進去
DB 有、manifest 沒有   🔴 重建資料庫就永久消失，而 Step 1.6 完全看不到
```

🔑 為什麼第二種會永久消失：`helpers/startup.py:_sync_module_versions()` 開機時
把 manifest **匯進**資料表（`INSERT OR IGNORE`）—— 那是單向的。
⇒ 從畫面 API 新增的紀錄**永遠不會回寫進 manifest**，
☠️ 而全新安裝與災難還原都是「從 manifest 長出一個新資料庫」。

實際發生過：四筆 2026-08-01 的紀錄只活在資料庫裡，**已經 52 天**
（`系統安全 2026-08-01a／b`、`營運報表 2026-08-01c`、`部署/更新流程 2026-08-01g`），
而那四筆裡有一筆記的是一個已修的 PDF `KeyError`。

## ⚠️ 讀不到資料庫時**不可以跳過**

A 2026-09-22 的原話：「『讀不到就跳過』是不行的——那會讓它在正式機上永遠不觸發。」
📌 〈計數器要有落點〉的同一族：**一道從來不會觸發的守門，跟運作良好長得一樣。**
⇒ 讀不到就是**失敗**，並把路徑印出來讓人知道要去看哪裡。

用法：
    python backend/tools/check_version_sync.py [--db <path>] [--manifest <path>]
結束碼 0 = 同步；1 = 有 DB 才有的紀錄，或讀不到其中一邊。
"""
import argparse
import json
import os
import sqlite3
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)

# 🔴🔴 主控台編碼會把「過了」變成「沒過」（2026-09-22，A 在打包前手動跑才撞到）。
#
# 這支腳本的輸出是中文，而 Windows 主控台的預設編碼在這台機器上是 cp932
# ⇒ `print()` 丟 `UnicodeEncodeError` ⇒ **行程以 exit 1 收場**。
# ☠️ 而打包腳本 Step 2.52 只看 `$LASTEXITCODE`
#    ⇒ 它會停在一句「版本紀錄反方向守門沒過」，**而實際上它過了**，
#    🔑 然後下一個人會去查版本紀錄，那裡什麼問題都沒有。
#
# ⚠️ 修法**不可以是「改成印 ASCII」**：這道守門的價值有一半在它的失敗訊息。
# ⚠️ 也不可以只在打包腳本那一側設 `PYTHONIOENCODING` —— 這支腳本會被人
#    直接跑（A 與 D 今天都跑過），直接跑一樣會炸。
# ⇒ **兩道都做**，而這一道在這裡：不管誰呼叫都不會因為主控台編碼而失敗。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:       # noqa: BLE001 —— 舊版 Python 或被接管過的 stream
        pass


# 🔑 判準**只有一份**：`helpers/startup.py:drift_between()`。
# ☠️ 這支腳本自己再寫一次比對的話，「守門說同步了」與「伺服器實際同步了」
#    會在某一天不是同一件事，而那一天不會有人發現。
sys.path.insert(0, _BACKEND)
from helpers.startup import drift_between          # noqa: E402


def _load_manifest(path):
    # ⚠️ `utf-8-sig`：PowerShell 5.1 重寫過這個檔的話會帶 BOM，
    #    而用 `utf-8` 讀的那天，失敗的理由會跟這道守門無關。
    with open(path, encoding="utf-8-sig") as f:
        entries = json.load(f)
    if not isinstance(entries, list):
        raise ValueError("version_manifest.json 不是一個陣列")
    return entries


def _load_db(path):
    # `mode=ro`：正式機上伺服器正開著這個檔，唯讀連線不會跟它搶寫鎖。
    conn = sqlite3.connect("file:%s?mode=ro" % path.replace("?", "%3f"), uri=True)
    try:
        conn.row_factory = sqlite3.Row
        return [dict(r) for r in conn.execute(
            "SELECT id, module, version, updated_at, updated_by, content "
            "FROM module_versions ORDER BY id")]
    finally:
        conn.close()


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=os.path.join(_BACKEND, "motrix_erp.db"))
    ap.add_argument("--manifest",
                    default=os.path.join(_BACKEND, "version_manifest.json"))
    args = ap.parse_args(argv)

    try:
        entries = _load_manifest(args.manifest)
    except Exception as exc:                      # noqa: BLE001 —— 讀不到就是失敗
        print("[FAIL] 讀不到 %s：%s" % (args.manifest, exc))
        return 1

    if not os.path.isfile(args.db):
        print("[FAIL] 找不到資料庫 %s —— 這道守門不會因為讀不到就放行。" % args.db)
        print("⇒ 若這台機器本來就沒有資料庫，請用 --db 指到一份"
              "（例如最近一次的備份快照）。")
        return 1

    try:
        rows = _load_db(args.db)
    except Exception as exc:                      # noqa: BLE001
        print("[FAIL] 讀不到 %s 的 module_versions：%s" % (args.db, exc))
        return 1

    by_key = {(r["module"], r["version"]): r for r in rows}
    drift = drift_between(entries, set(by_key))

    if drift["duplicates"]:
        print("[FAIL] version_manifest.json 有重複的 (module, version)：")
        for key in drift["duplicates"]:
            print("   %s" % key)
        print("⇒ 資料表有 UNIQUE(module, version)，重複的那一筆永遠進不去，"
              "而它在畫面上就是不存在。請改成一個沒用過的版本字母。")
        return 1

    if drift["db_only"]:
        print("[FAIL] 這些版本紀錄只活在資料庫裡，"
              "`version_manifest.json` 沒有 —— 重建資料庫就永久消失：")
        for key in drift["db_only"]:
            module, version = key.split(" / ", 1)
            row = by_key.get((module, version), {})
            print("   %-16s %-14s %s  (id=%s, by=%s)" % (
                module, version, row.get("updated_at"), row.get("id"),
                row.get("updated_by")))
        print("⇒ 內容**逐字照抄**資料庫裡的原文補進 manifest，不要改寫："
              "改寫等於偽造當時的紀錄。")
        return 1

    # 📌 `manifest_only` 只印不擋（`VR9`）：那是「服務還沒重啟」的正常狀態。
    # ☠️ 把它當缺陷會導出一個「啟動時強制同步」的修法，而那正是 `_m035` 修掉的。
    if drift["manifest_only"]:
        print("   （另有 %d 筆 manifest 有而資料庫沒有 —— 那是等待下次重啟同步的"
              "正常狀態，不擋打包）" % len(drift["manifest_only"]))

    print("[OK] 版本紀錄雙向同步：資料庫 %d 列、manifest %d 筆，"
          "沒有「只活在資料庫裡」的紀錄。" % (len(rows), len(entries)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
