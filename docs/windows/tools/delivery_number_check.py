# -*- coding: utf-8 -*-
"""交件前自檢：同一個數字／SHA 出現在哪幾份交件文件裡。

🔑 **答案在「缺席」那一欄，不在「一致」那一欄。**
   2026-09-23 抓到的實例：`e70527e` 與 `2,440` 出現在 TEST-BASELINE 與
   TEST-CONFIDENCE，而 **HANDOVER 裡 0 次** —— 那不是抄錯，是 §2d 那一節
   沒有被回頭改（它還寫著「今天沒有跑過一次全量」，而全量已經跑完了）。
   ☠️ 而「一致的那些」會讓人覺得檢查通過了。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
🔴 新增交件文件時，**要回來把它加進 DELIVERY 這個清單**。
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
   ⚠️ 這個母體**算不出來** —— 「哪些檔算交件文件」是人定的，不是結構決定的。
   🔑 而那正是〈算得出來的數字不可以寫成常數〉的**反面**：
      算得出來的不可以寫死；算不出來的就要有一句話擋住遺忘。
   ☠️ 沒有這一行的話，失敗的樣子是「檢查全過，而它沒有看新加的那一份」——
      與 2026-09-23 那次「我的檢查只涵蓋 3/5 而輸出讀起來像 5/5」同一個形狀。

⚠️ 這是**交件前的自檢**，不要進 CI（理由同 refcheck）：
   它的判準是「人要不要看一眼」，不是「對或錯」——
   進 CI 會逼人把正常的差異寫進排除清單，而那會讓它變成一道擺設。

用法：
    python docs/windows/tools/delivery_number_check.py
"""
import io
import os
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# ── 🔴 交件文件母體 —— 新增交件文件時要回來加 ──────────────────────
DELIVERY = [
    "HANDOVER-2026-09-23.md",        # ① 出貨阻擋＋做完了什麼＋證據強弱（A）
    "TEST-BASELINE-2026-09-23.md",   # ⑤ 原始量測紀錄（D 量、A 落檔）
    "TEST-CONFIDENCE.md",            # ② 測試能保證到哪裡（A-2）
    "KNOWN-GAPS.md",                 # ③ 我們知道自己沒查的（A-2）
    "PENDING-RULINGS.md",            # ④ 待使用者裁示的（A-2）
]
BASE = "docs/windows"

# 要比對的東西。每一項 = (標籤, regex, 是否只看跨檔的)
PATTERNS = [
    ("測試結果數",  r'([0-9],?[0-9]{3})\s*(?:passed|failed|過|沒過)'),
    ("題數／母體",  r'\*\*([0-9],?[0-9]{3})\*\*'),
    ("commit SHA", r'(?<![0-9a-zA-Z])([0-9a-f]{7})(?![0-9a-zA-Z])'),
    ("百分比",      r'([0-9]{1,3})\s*%'),
]


def norm(x):
    """`2,440` 與 `2440` 是同一個數字。"""
    return x.replace(",", "")


def main():
    missing = []
    for path in DELIVERY:
        if not os.path.exists(os.path.join(BASE, path)):
            missing.append(path)
    if missing:
        print("🔴 母體裡有檔案不存在（改名或刪掉了？請更新 DELIVERY）：")
        for m in missing:
            print("     %s" % m)
        print()

    texts = {}
    for path in DELIVERY:
        p = os.path.join(BASE, path)
        if os.path.exists(p):
            texts[path] = io.open(p, encoding="utf-8", errors="replace").read()

    print("交件文件 %d 份（母體是人定的，見檔頭）" % len(texts))
    print("=" * 78)

    total_absent = 0
    for label, pat in PATTERNS:
        rx = re.compile(pat)
        hits = {}          # 正規化後的值 -> {檔名: [(行號, 該行)]}
        for path, t in texts.items():
            for i, line in enumerate(t.split("\n"), 1):
                for m in rx.finditer(line):
                    hits.setdefault(norm(m.group(1)), {}).setdefault(path, []).append(
                        (i, line.strip()[:58]))

        cross = {k: v for k, v in hits.items() if len(v) > 1}
        print()
        print("## %s —— 跨檔出現的有 %d 個" % (label, len(cross)))
        if not cross:
            print("   （沒有跨檔出現的值）")
            continue
        for k in sorted(cross, key=lambda x: (-len(cross[x]), x)):
            present = sorted(cross[k])
            absent = [p for p in texts if p not in cross[k]]
            total_absent += len(absent)
            print()
            print("  %-10s 出現在 %d 份" % (k, len(present)))
            for p in present:
                i, line = cross[k][p][0]
                print("     ✅ %-28s :%-4d %s" % (p[:28], i, line))
            # 🔑 缺席欄 —— 這才是要看的那一欄
            for p in absent:
                print("     ⬜ %-28s **0 次**" % p[:28])

    print()
    print("=" * 78)
    print("🔑 ⬜ 那一欄才是要看的：**一個數字在某一份裡是 0 次**，")
    print("   可能是那一份不該提它（正常），也可能是**那一節沒有被回頭改**（過期）。")
    print("   ⇒ 工具答不出是哪一種，**它只負責讓你看見**。")
    print()
    print("⚙️ 本次共 %d 個「值 × 缺席檔」組合要人看一眼。" % total_absent)


if __name__ == "__main__":
    main()
