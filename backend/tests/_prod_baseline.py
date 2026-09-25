"""正式機基準：目前正式機跑的是哪一個 commit，以及那一版的 version_manifest。

⚠️ **每次部署到正式機之後，要把 BASELINE 更新成新的正式機 commit。**
   沒更新的話，下一包會把這一包已出貨的條目當成「未出貨」（VR3 會要求它們跟新條目合併，
   而合併＝改寫已出貨的紀錄，正是 test_version_manifest_shipped_is_immutable 要擋的事）。
   BASELINE 只能往後移（新的正式機 commit 必須是舊的後代）。

📌 2026-09-25：使用者確認正式機＝46dc6ae（2026-09-24 02:46:15 部署）。
📌 2026-09-25 02:5x：使用者回報已把 20260925_023333_3a66611 更新到正式機 ⇒ 基準改 3a66611。
📌 2026-09-25 15:3x：使用者回報已部署 20260925_151234_2220aedb ⇒ 基準改 2220aedb。
"""
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BASELINE = "2220aedb"


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
