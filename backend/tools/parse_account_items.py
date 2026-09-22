# -*- coding: utf-8 -*-
"""《商業會計項目表》PDF → 靜態 JSON（`FN1` §92b ①②）。

## 🔴 這支**離線跑**，migration 不可以呼叫它

`§69(c)`：〈凍住的歷史不要呼叫活的程式碼〉—— migration 是歷史，
而解析器會演進（官方改版、pdfplumber 升級都會改變輸出）。
⇒ 這支產出一份**靜態 JSON**，`v94` 載入那份 JSON，**不載入這支**。
📌 而那條為了正確性訂的規則，順帶把工作切成「碰 db 的」與「不碰 db 的」
   —— 這支屬於後者，所以它不影響正在出貨的那一包。

## 🔴 二級是**範圍代號**，不可以靠前綴建樹

```
一級  1       資產
二級  11-12   流動資產     ← **是一個範圍**
三級  111     現金及約當現金
☠️ "111".startswith("11-12") 為 False
```
⇒ `parent_code` **明確記錄**，用「最近一個上層代號」推，不用字串前綴。

## ⚠️ 輸入要有指紋

同一支解析器對不同年度版本都跑得出漂亮的結果，**而那是另一份資料**。
⇒ 跑之前先核對 sha256；對不上就停，不要產出。

用法:
    python parse_account_items.py <pdf> [--out <json>] [--expect-sha256 <hex>]
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

#: A-2 於 2026-09-22 22:23 自 `https://gcis.nat.gov.tw/F/t70492_p` 取得的那一份。
#: 🔑 記在這裡是為了讓「輸入有沒有被換掉」變成**可檢查**的 ——
#: ☠️ 否則下一次有人換成新年度版，解析結果會變，而**沒有東西會說它變了**。
#: ⚠️ 而它只保證「這是我們解析過的那一份」，**不保證它是現行最新版**
#:    （`§69c`：「112 年版之後有無更新版」仍未查公告）。
KNOWN_SHA256 = "872f827ce18157b9b8e26a979c7bb47b7952ddee68fd850a363e869d419e2d34"
KNOWN_BYTES = 1578890

#: 四個層級代號在表格裡的欄位索引（`extract_tables()` 回 8 欄）。
_LEVEL_COLS = (0, 1, 2, 3)
_NAME_COL = 4
_EN_COL = 5

#: 代號長什麼樣：`1`／`11-12`／`111`／`1111`。
#: ⚠️ **範圍代號一定要能被接受** —— 用 `^\d+$` 的話二級整層都會消失。
_CODE_RE = re.compile(r"^\s*(\d+(?:-\d+)?)\s*$")


def _cell(row, i):
    v = row[i] if i < len(row) else None
    return (v or "").replace("\n", "").strip()


def _is_header(row):
    """表頭列。**每一頁都會重複一次**，不濾掉會被併進上一筆的名稱裡。"""
    head = {_cell(row, i) for i in range(6)}
    return bool(head & {"一級", "二級", "三級", "四級", "項目",
                        "會計項目名稱", "ACCOUNT NAME"})


def _code_cell(row):
    """回 `(欄位索引, 層級, 代號字面)`，沒有代號回 `None`。

    ⚠️ **三種**形狀都要收，而我漏掉第三種時的症狀值得記：
    ```
    111      一般代號
    11-      範圍代號的**前半**（後半在下一列，甚至下一頁）
    21-22    **完整的範圍代號，整個在同一格**   ← 我第一版漏了這一種
    ```
    ☠️ 漏掉第三種時：`21-22` 不被當成代號 ⇒ 它的名稱「流動負債」被當成續行
       併進上一筆 ⇒ 一級變成 `2 負債流動負債`，而它底下 27 筆三級全部
       `parent=None` —— **而筆數看起來很正常**（544 筆），正對照才叫出來。
    🔑 〈判準的寬窄都會騙人〉：我為了收第二種而把正則改窄，**順手砍掉了第三種**。
    """
    for ci in _LEVEL_COLS:
        v = _cell(row, ci)
        if re.match(r"^(?:\d+-|\d+(?:-\d+)?)$", v):
            return ci, ci + 1, v
    return None


def parse(pdf_path):
    """回 `(items, stats)`。

    ## 🔴 三件事必須在**同一個串流**上做，不能逐頁各自處理

    ```
    ① 名稱跨列    811 = '繼續營業單位稅前淨' ＋ 下一列 '益（或淨損）'
    ② 範圍代號跨列 11-12 在 PDF 裡是 '11-' ＋ 下一列 '12'
    ③ 而 ② **會跨頁**：723- 在第 37 頁最後一列，724 在第 38 頁
    ```
    ☠️ 逐頁處理的話 ③ 永遠接不起來，而它**不會報錯** —— 只會安靜地多出一筆
       叫 `723-` 的項目和一筆叫 `724` 的項目，兩筆的名稱都是半截。
    """
    import pdfplumber

    rows = []
    pages = 0
    with pdfplumber.open(pdf_path) as pdf:
        pages = len(pdf.pages)
        for page in pdf.pages:
            for table in page.extract_tables():
                for row in table:
                    if not _is_header(row):
                        rows.append(row)

    items = []
    last_at_level = {}
    cur = None            # 正在累積的項目
    pending_col = None    # 範圍代號前半所在的欄（等後半）

    def close():
        if cur is not None:
            cur["name"] = cur["name"].strip()
            cur["name_en"] = " ".join(cur["name_en"].split())
            items.append(cur)

    for row in rows:
        hit = _code_cell(row)
        if hit is None:
            # 沒有代號 ⇒ 名稱／英文的續行。
            if cur is not None:
                cur["name"] += _cell(row, _NAME_COL)
                cur["name_en"] += " " + _cell(row, _EN_COL)
            continue

        ci, level, code = hit

        if pending_col is not None and ci == pending_col and not code.endswith("-"):
            # 範圍代號的後半：**補完代號**，而它那一列的名稱也要併進來。
            cur["code"] += code
            cur["name"] += _cell(row, _NAME_COL)
            cur["name_en"] += " " + _cell(row, _EN_COL)
            last_at_level[cur["level"]] = cur["code"]
            pending_col = None
            continue

        close()
        parent = last_at_level.get(level - 1) if level > 1 else None
        cur = {"code": code, "level": level,
               "name": _cell(row, _NAME_COL),
               "name_en": _cell(row, _EN_COL),
               "parent_code": parent}
        if code.endswith("-"):
            pending_col = ci          # 等下一列補後半
        else:
            pending_col = None
            last_at_level[level] = code
        for deeper in [k for k in last_at_level if k > level]:
            del last_at_level[deeper]

    close()
    return items, {"pages": pages, "rows_used": len(rows)}


def merge_continuations(items):
    """名稱空白的項目，把它併回上一筆（PDF 把長名稱斷成兩列）。"""
    out = []
    for it in items:
        if not it["name"] and out:
            continue          # 沒有名稱的代號列：目前的資料裡不應該出現
        out.append(it)
    return out


# ══════════════════════════════════════════════════════════════════
# 三道正對照（A-2 設計）—— 沒過就**不要產出**
# ══════════════════════════════════════════════════════════════════
def controls(items):
    """回 `(ok, lines)`。

    🔑 三道都是**正對照**：它們在「解析器壞掉」時會亮，
    ☠️ 而「解析出 0 筆」這種情況下，只驗「有沒有錯」的檢查會**安靜通過**。
    """
    lines = []
    ok = True

    # 🔴 **`§69` 寫「一級共 9 個（1–9）」—— 那是錯的，實際是 8 個。**
    #
    # 證據（我逐頁掃第 0 欄的每一個非空值，不是只讀前兩頁）：
    # ```
    # p1 1 資產 ／ p19 2 負債 ／ p28 3 權益 ／ p30 4 營業收入 ／ p31 5 營業成本
    # p33 6 營業費用 ／ p34 7 營業外收益及費損 ／ p39 8 綜合損益總額
    # 而整份表**結束在 `88 本期綜合損益總額`**（第 42 頁最後一列），沒有 9。
    # ```
    # ⚠️ 而這道正對照原本寫 `== 9` ⇒ 它會**永遠紅**，而紅的原因不是解析器壞了。
    # 🔑 A-2 自己講過同一句：「若你的數字與我的不同，**預設是我錯**」——
    #    它那個 9 與 589 一樣是粗估，而它只讀了前兩頁。
    EXPECT_LEVEL1 = 8
    lv1 = [i for i in items if i["level"] == 1]
    good = len(lv1) == EXPECT_LEVEL1
    ok &= good
    lines.append("① 一級項目必須正好 %d 個：實際 %d 個 %s"
                 % (EXPECT_LEVEL1, len(lv1), "✅" if good else "🔴"))
    lines.append("   " + "／".join("%s %s" % (i["code"], i["name"]) for i in lv1))

    codes = {i["code"] for i in items}
    orphan = [i for i in items
              if i["level"] > 1 and (not i["parent_code"] or i["parent_code"] not in codes)]
    ok &= not orphan
    lines.append("② 每一筆的 parent 必須存在：孤兒 %d 筆 %s"
                 % (len(orphan), "✅" if not orphan else "🔴"))
    for o in orphan[:5]:
        lines.append("   🔴 %s %s ⇒ parent=%r" % (o["code"], o["name"], o["parent_code"]))

    dup = [c for c in codes if sum(1 for i in items if i["code"] == c) > 1]
    ok &= not dup
    lines.append("③ 代號不可重複：重複 %d 個 %s"
                 % (len(dup), "✅" if not dup else "🔴"))
    for d in dup[:5]:
        lines.append("   🔴 %s" % d)

    return ok, lines


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default=None)
    ap.add_argument("--expect-sha256", default=KNOWN_SHA256)
    args = ap.parse_args()

    blob = open(args.pdf, "rb").read()
    got = hashlib.sha256(blob).hexdigest()
    print("輸入：%s" % args.pdf)
    print("  %d bytes   sha256 %s" % (len(blob), got))
    if args.expect_sha256 and got != args.expect_sha256:
        print("🔴 sha256 與預期不符 —— **停手，不產出**。")
        print("   預期 %s" % args.expect_sha256)
        print("   ⇒ 這可能是另一個年度版本：同一支解析器對它也跑得出漂亮的結果，")
        print("     **而那是另一份資料**。")
        sys.exit(1)
    print("  ✅ 與已知的那一份相同\n")

    items, stats = parse(args.pdf)
    items = merge_continuations(items)
    print("解析：%d 頁，%d 筆項目（用到 %d 列）"
          % (stats["pages"], len(items), stats["rows_used"]))
    by_lv = {}
    for i in items:
        by_lv[i["level"]] = by_lv.get(i["level"], 0) + 1
    print("  各層：%s" % "　".join("L%d=%d" % (k, by_lv[k]) for k in sorted(by_lv)))
    rng = [i["code"] for i in items if "-" in i["code"]]
    print("  範圍代號 %d 個：%s" % (len(rng), rng))

    print()
    ok, lines = controls(items)
    for l in lines:
        print(l)
    if not ok:
        print("\n🔴 正對照沒過 ⇒ **不產出**。")
        sys.exit(1)

    if args.out:
        payload = {
            "source": {
                "title": "商業會計項目表(112年度及以後適用版本)",
                "url": "https://gcis.nat.gov.tw/F/t70492_p",
                "sha256": got,
                "bytes": len(blob),
            },
            "count": len(items),
            "items": items,
        }
        io.open(args.out, "w", encoding="utf-8", newline="\n").write(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        print("\n✅ 已寫出 %s（%d 筆）" % (args.out, len(items)))


if __name__ == "__main__":
    main()
