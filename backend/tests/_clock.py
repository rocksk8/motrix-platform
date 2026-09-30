"""測試用時鐘：新測試寫時間相依內容一律用這裡的 `today()`／`now()`，不直接 `date.today()`／`datetime.now()`。

起因（2026-10-01，第二十六～二十七班建包連敗，其中四次是時間相依）：跨午夜（收集時算「明天」、執行時已過午夜）、
xdist 收集不一致（zip writestr 用現在時間進參數 id）、版本紀錄日期檢查（換日後最新一筆比 commit 日舊）、
每月 1 號（月備份保留份取「本月」）。共通點：測試的預期值取決於「跑的那一刻」，而不是輸入。

## 規則
- `MOTRIX_TEST_TODAY=YYYY-MM-DD`（建包腳本 `-ClockDate` 設，預設＝commit 日期）⇒ `today()`／`now()` 回那一天的 12:00，
  整輪測試看到同一天；不設 ⇒ 回真實時間（行為與直接呼叫相同）。
- 值不合法 ⇒ 立刻丟 ValueError（conftest 在 pytest_configure 也會擋，整輪不開跑）——不合法的日期靜默退回真實時間，
  就是「以為固定了、其實沒固定」。
- 產品端：**產品沒有全域時鐘接縫**（126 處直接 `date.today()`／`datetime.now()`）。目前只有三個既有的接縫：
  `helpers.legal_params.today`、`helpers.procurement.today`、`modules.tender_radar.source.today／now_dt`。
  `install_seams()`（conftest 的 autouse fixture 呼叫）只把這三個換成同一天，其餘產品程式碼照舊讀真實時間——
  所以 MOTRIX_TEST_TODAY 不能讓「產品內部的 datetime.now()」也變成固定日；要驗那種行為請用邊界日矩陣
  （tools/platform/boundary_days.py，整個行程的時鐘平移）或在測試裡明確 monkeypatch 該模組。
"""
import os
import sys
from datetime import date, datetime

ENV = "MOTRIX_TEST_TODAY"
FIXED_HOUR = 12


def fixed_date():
    """⇒ date（環境變數有設）或 None。不合法 ⇒ ValueError。"""
    raw = os.environ.get(ENV)
    if raw is None or raw.strip() == "":
        return None
    try:
        return datetime.strptime(raw.strip(), "%Y-%m-%d").date()
    except ValueError:
        raise ValueError("%s=%r 不是 YYYY-MM-DD" % (ENV, raw)) from None


def today():
    d = fixed_date()
    return d if d is not None else date.today()


def now():
    d = fixed_date()
    if d is None:
        return datetime.now()
    return datetime(d.year, d.month, d.day, FIXED_HOUR, 0, 0)


#: 既有的產品時鐘接縫：(模組名, 屬性, 種類)。加新接縫時在這裡加一列（並在 PLAYBOOK §G5 第 20 項註明）。
SEAMS = (
    ("helpers.legal_params", "today", "date"),
    ("helpers.procurement", "today", "date"),
    ("modules.tender_radar.source", "today", "date"),
    ("modules.tender_radar.source", "now_dt", "datetime"),
)


def install_seams(monkeypatch, seams=SEAMS, modules=None):
    """MOTRIX_TEST_TODAY 有設 ⇒ 把已存在的產品接縫換成固定日；沒設 ⇒ 什麼都不做。回傳實際換掉的 [模組.屬性]。

    - 只換「模組已經被 import」的（sys.modules 有）：不為了換時鐘去 import 產品模組（會多出 import 副作用）。
      沒被 import 的模組，之後被 import 時拿到真實時鐘——這是已知限制，見檔頭。
    - 屬性不存在 ⇒ 跳過並不聲張（接縫被拿掉不該讓所有測試紅）；接縫是否還在由 test_clock_gates 的題守。
    - 測試自己 monkeypatch 同一個屬性照樣有效（後設的覆蓋前設的）。"""
    d = fixed_date()
    if d is None:
        return []
    fixed_dt = now()
    done = []
    mods = modules if modules is not None else sys.modules
    for mod_name, attr, kind in seams:
        mod = mods.get(mod_name)
        if mod is None or not hasattr(mod, attr):
            continue
        monkeypatch.setattr(mod, attr, (lambda v=d: v) if kind == "date" else (lambda v=fixed_dt: v))
        done.append("%s.%s" % (mod_name, attr))
    return done
