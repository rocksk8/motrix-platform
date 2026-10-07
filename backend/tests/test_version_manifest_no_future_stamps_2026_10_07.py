# -*- coding: utf-8 -*-
"""版本紀錄：**新條目的 date／time 不可以晚於現在**（第 45 班小項；第 44 班出貨的 `出納/簽核` 23:08、`獎金分潤` 23:10 是手打的佔位時間，
比實際完成時間晚，只影響版本紀錄的排序）。已出貨的條目不可改（見 test_version_manifest_shipped_is_immutable），所以這裡只管**基準之後新增**的條目；
時間用 `date` 取（記憶〈時間由 date 產生〉），不手寫。容許 5 分鐘的時鐘誤差。
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from tests._prod_baseline import baseline_manifest

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "backend" / "version_manifest.json"
#: 容許的時鐘誤差（分鐘）。這支守門比對的是**執行機器的現在時間**：作者機器與跑閘門的機器時鐘差超過容許（例如閘門機器的時鐘慢 >5 分鐘）會誤紅。
#: 預設 5；環境變數 `MOTRIX_MANIFEST_FUTURE_TOLERANCE_MIN` 可調（整數 0～1440；不合法 ⇒ 預設）。已知限制見 docs/quick/known-limits.md。
def _tolerance(env=None):
    raw = (os.environ if env is None else env).get("MOTRIX_MANIFEST_FUTURE_TOLERANCE_MIN", "")
    try:
        n = int(str(raw).strip())
    except ValueError:
        return timedelta(minutes=5)
    return timedelta(minutes=n) if 0 <= n <= 1440 else timedelta(minutes=5)


TOLERANCE = _tolerance()


def future_entries(manifest, baseline, now, tolerance=TOLERANCE):
    """基準（已出貨）之外、date＋time 晚於 now＋容許誤差的條目 ⇒ 違規訊息清單。純函式。
    date／time 格式壞掉 ⇒ 也列出（不猜）。"""
    shipped = {(e.get("module"), e.get("version")) for e in baseline}
    bad = []
    for e in manifest:
        key = (e.get("module"), e.get("version"))
        if key in shipped:
            continue
        try:
            stamp = datetime.strptime("%s %s" % (e.get("date"), e.get("time")), "%Y-%m-%d %H:%M")
        except (TypeError, ValueError):
            bad.append("%s %s：date／time 格式不對（%r %r）" % (key + (e.get("date"), e.get("time"))))
            continue
        if stamp > now + tolerance:
            bad.append("%s %s：%s %s 晚於現在 %s" % (key + (e["date"], e["time"], now.strftime("%Y-%m-%d %H:%M"))))
    return bad


def test_new_manifest_entries_are_not_stamped_in_the_future():
    cur = json.loads(MANIFEST.read_text(encoding="utf-8-sig"))
    bad = future_entries(cur, baseline_manifest(), datetime.now())
    assert not bad, ("版本紀錄的新條目時間晚於現在（手打的佔位時間？）：\n  " + "\n  ".join(bad)
                     + "\n⇒ time 用 `date '+%H:%M'` 取實際完成時間；已出貨的條目不要動。")


# ── 反向控制 ──────────────────────────────────────────────────────────────────

NOW = datetime(2026, 10, 7, 15, 30)


def _e(module, date, time, version="next"):
    return {"module": module, "version": version, "date": date, "time": time, "content": "x"}


def test_the_guard_catches_a_later_time_today_and_a_later_day():
    assert len(future_entries([_e("甲", "2026-10-07", "23:08")], [], NOW)) == 1      # 第 44 班那種：同一天、時間手打得太晚
    assert len(future_entries([_e("甲", "2026-10-08", "00:01")], [], NOW)) == 1      # 隔天


def test_the_guard_allows_past_now_and_the_clock_tolerance():
    assert future_entries([_e("甲", "2026-10-07", "15:30")], [], NOW) == []
    assert future_entries([_e("甲", "2026-10-07", "15:35")], [], NOW) == []           # 5 分鐘內
    assert len(future_entries([_e("甲", "2026-10-07", "15:36")], [], NOW)) == 1
    assert future_entries([_e("甲", "2026-10-06", "23:59")], [], NOW) == []


def test_shipped_entries_are_exempt_because_they_cannot_be_rewritten():
    shipped = _e("出納/簽核", "2026-10-07", "23:08", "2026-10-07b")
    assert future_entries([shipped], [shipped], NOW) == []
    assert len(future_entries([dict(shipped, version="2026-10-07c")], [shipped], NOW)) == 1    # 同名不同版 ⇒ 是新條目


def test_tolerance_is_env_tunable_with_a_safe_default():
    assert _tolerance({}) == timedelta(minutes=5)
    assert _tolerance({"MOTRIX_MANIFEST_FUTURE_TOLERANCE_MIN": "30"}) == timedelta(minutes=30)
    for bad in ("", "x", "-1", "1441", "5.5"):
        assert _tolerance({"MOTRIX_MANIFEST_FUTURE_TOLERANCE_MIN": bad}) == timedelta(minutes=5), bad
    assert future_entries([_e("甲", "2026-10-07", "15:50")], [], NOW) != []
    assert future_entries([_e("甲", "2026-10-07", "15:50")], [], NOW, tolerance=timedelta(minutes=30)) == []


def test_the_guard_reports_unparseable_stamps_instead_of_guessing():
    assert len(future_entries([_e("甲", "2026/10/07", "25:00")], [], NOW)) == 1
    assert len(future_entries([{"module": "乙", "version": "next"}], [], NOW)) == 1
