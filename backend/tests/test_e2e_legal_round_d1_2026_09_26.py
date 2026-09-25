# -*- coding: utf-8 -*-
"""稽核 D-1／S-1／S-2（2026-09-26）e2e：勞報單頁的試算與後端一致、日期用台北時間。

- 前端捨入（frontend/static/legal-round.js）20,000～2,000,000 逐元與「四捨五入」一致（校驗和比對，
  Python 端用獨立的整數算法）；正對照：把捨入換成銀行家捨入（後端原本的 round()），校驗和要對不上。
  〔註：實測 Math.round(g × 0.0211) 在這個範圍與四捨五入一致（浮點誤差沒有剛好落在 .5 上），
    所以不拿它當正對照；前端改用整數算法是為了與後端同一套、不依賴「剛好沒碰到」〕
- 頁面實際試算 35,000（9A）⇒ 畫面 739，存檔後資料庫也是 739（畫面與存檔一致）。
- 瀏覽器時區 UTC、台北時間清晨 ⇒ 新單的開單日期、告知書日期都是台北的今天（不是 UTC 的昨天）。
"""
from datetime import datetime, timedelta, timezone
from fractions import Fraction

import pytest

pytest.importorskip("playwright.sync_api")

from helpers import legal_params as lp  # noqa: E402

ROOT = "Alpine.$data(document.querySelector('[x-data]'))"


def _open_form(page, base):
    page.goto(base + "/pages/payslip-form.html")
    page.wait_for_function(f"() => window.Alpine && document.querySelector('[x-data]') && {ROOT}.rulesVersion !== ''",
                           timeout=20000)


@pytest.mark.e2e
def test_frontend_rounding_matches_half_up_over_the_whole_range(live_server, make_user, new_page, login_as):
    u = make_user(username="dfix_e1", role="superadmin")
    page = new_page()
    login_as(page, u)
    _open_form(page, live_server)
    rate = page.evaluate(f"() => {ROOT}.rules.nhi.rate")
    assert rate == lp.DEFAULT_TAX_RULE_VERSIONS[0]["nhi"]["rate"]
    got = page.evaluate("""(rate) => {
        const LR = window.MotrixLegalRound
        // 銀行家捨入（正對照用）：rate 以十進位字串轉成 分子/分母
        const [ip, fp = ''] = String(rate).split('.')
        const rn = BigInt(ip + fp), rd = 10n ** BigInt(fp.length)
        let sum = 0n, wsum = 0n, bsum = 0n, bankerDiff = 0
        for (let g = 20000; g <= 2000000; g++) {
          const v = LR.halfUp(g, rate)
          sum += BigInt(v); wsum += BigInt(v) * BigInt(g % 9973)
          const n = BigInt(g) * rn, q = n / rd, r2 = 2n * (n % rd)
          const b = (r2 > rd || (r2 === rd && q % 2n === 1n)) ? q + 1n : q
          bsum += b
          if (Number(b) !== v) bankerDiff++
        }
        return { sum: sum.toString(), wsum: wsum.toString(), bsum: bsum.toString(), bankerDiff,
                 f1: LR.floor(20009, 0.1), f2: LR.floor(12345, 0.05), neg: LR.halfUp(-35000, rate) }
    }""", rate)
    f = Fraction(repr(rate))
    s = w = 0
    for g in range(20000, 2000001):
        v = (2 * g * f.numerator + f.denominator) // (2 * f.denominator)
        s += v
        w += v * (g % 9973)
    assert (int(got["sum"]), int(got["wsum"])) == (s, w), "前端捨入與四捨五入不一致"
    assert (got["f1"], got["f2"], got["neg"]) == (2000, 617, -739)
    # 正對照：銀行家捨入（後端原本的 round()）在這個範圍有 99 個金額不同，校驗和對不上 ⇒ 比對抓得到差異
    assert got["bankerDiff"] == 99 and int(got["bsum"]) != s


@pytest.mark.e2e
def test_the_page_shows_what_the_server_stores(live_server, make_user, new_page, login_as, client):
    u = make_user(username="dfix_e2", role="superadmin")
    page = new_page()
    login_as(page, u)
    _open_form(page, live_server)
    page.evaluate(f"""() => {{ const d = {ROOT}; d.q.contractorName = '受領人'; d.q.serviceContent = '測試';
        d.q.incomeType = '9A'; d.q.grossAmount = 35000; d.calc() }}""")
    shown = page.evaluate(f"() => {ROOT}.result")
    assert (shown["nhiSupplement"], shown["taxWithheld"], shown["netAmount"]) == (739, 3500, 30761)
    tok = client.post("/api/auth/login", json={"username": u[0], "password": u[1]}).json()["token"]
    h = {"Authorization": "Bearer " + tok}
    data = page.evaluate(f"() => JSON.parse(JSON.stringify({ROOT}.q))")
    r = client.post("/api/payslips", headers=h, json={"data": data})
    assert r.status_code == 201, r.text
    assert r.json()["calc"]["nhiSupplement"] == shown["nhiSupplement"]


@pytest.mark.e2e
def test_new_slip_and_notice_dates_use_taipei_time(live_server, make_user, new_page, login_as):
    # 台北今天的 01:30 ＝ UTC 前一天 17:30；瀏覽器時區設成 UTC
    taipei_today = (datetime.now(timezone.utc) + timedelta(hours=8)).date()
    fixed = datetime(taipei_today.year, taipei_today.month, taipei_today.day, 1, 30,
                     tzinfo=timezone(timedelta(hours=8)))
    u = make_user(username="dfix_e3", role="superadmin")
    page = new_page(timezone_id="UTC")
    page.clock.set_fixed_time(fixed)
    login_as(page, u)
    _open_form(page, live_server)
    utc_day = page.evaluate("() => new Date().toISOString().slice(0, 10)")
    assert utc_day == (taipei_today - timedelta(days=1)).isoformat(), "前提：UTC 還是前一天"
    assert page.evaluate(f"() => {ROOT}.q.slipDate") == taipei_today.isoformat()
    doc = page.evaluate("() => window.MotrixPrivacyNotice.documentHtml({company: '甲', text: 't'}, '乙')")
    assert "日期：" + taipei_today.isoformat() in doc
