"""正式機基準：目前正式機跑的是哪一個 commit，以及那一版的 version_manifest。

⚠️ **每次部署到正式機之後，要把 BASELINE 更新成新的正式機 commit。**
   沒更新的話，下一包會把這一包已出貨的條目當成「未出貨」（VR3 會要求它們跟新條目合併，
   而合併＝改寫已出貨的紀錄，正是 test_version_manifest_shipped_is_immutable 要擋的事）。
   BASELINE 只能往後移（新的正式機 commit 必須是舊的後代）。

📌 2026-09-25：使用者確認正式機＝46dc6ae（2026-09-24 02:46:15 部署）。
📌 2026-09-25 02:5x：使用者回報已把 20260925_023333_3a66611 更新到正式機 ⇒ 基準改 3a66611。
📌 2026-09-25 15:3x：使用者回報已部署 20260925_151234_2220aedb ⇒ 基準改 2220aedb。
📌 2026-09-28：正式機已部署 c006a2a0（主持派工第十四班）⇒ 基準改 c006a2a0。
📌 2026-09-28 16:33（記錄時間）：正式機已部署 54a2d6b6（第十六班；主持確認地圖 28g、標案雷達 28h 已出貨）⇒ 基準改 54a2d6b6。
📌 2026-09-29 04:28：正式機已更新到 29e435df（第二十、二十一班合成一次上線，RUN-PLAN §6）⇒ 基準改 29e435df；第二十二班列車才發現漏更新（VR3 把已出貨的 29a／28k 當未出貨）。
📌 2026-09-30：正式機已是 a806ba19（第二十三班勞報單，RUN-PLAN §6；第二十二班 b6182dbf 亦已上線）⇒ 基準改 a806ba19（W3 標案雷達 1.5.2 新條目 VR3 交會才發現仍停在 29e435df）。
📌 2026-09-30 11:22：正式機已更新到 0c20864a（第二十四班，RUN-PLAN §6）⇒ 基準改 0c20864a。
📌 2026-10-01 22:32：正式機已更新到 47db5613（第二十九班＝併第三十班；使用者貼 apply_update 套用成功、無回滾）⇒ 基準改 47db5613。
📌 2026-10-02 07:15：正式機已更新到 6b5d2865（第三十班；正式機 Claude 依使用者「套用」執行 apply_update，成功、無回滾，result.json status=success）⇒ 基準改 6b5d2865。
📌 2026-10-02 14:10：正式機已更新到 a5dea50c（第三十一班；正式機 Claude 依主持「可以套用」與使用者授權執行 apply_update，成功、無回滾，result.json status=success）⇒ 基準改 a5dea50c。
📌 2026-10-02 20:45：正式機已更新到 52033606（第三十二班；正式機 Claude 依主持「可以套用」與使用者當場指示執行 apply_update，成功、無回滾，result.json status=success）⇒ 基準改 52033606。
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "345a34cd"


def baseline_manifest():
    """正式機那一版的 manifest（list）。讀不到就 fail —— 不可以當成「沒有已出貨的條目」。"""
    try:
        out = subprocess.run(["git", "show", "%s:backend/version_manifest.json" % BASELINE],
                             cwd=ROOT, capture_output=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired) as exc:
        pytest.fail("讀不到正式機基準 %s 的 manifest（%s）" % (BASELINE, exc))
    if out.returncode != 0:
        pytest.fail("讀不到正式機基準 %s 的 manifest：%s" % (BASELINE, out.stderr.decode("utf-8", "replace")))
    base = json.loads(out.stdout.decode("utf-8-sig"))
    assert len(base) > 300, "基準讀出來太少（%d 筆），多半讀錯了東西" % len(base)
    return base
