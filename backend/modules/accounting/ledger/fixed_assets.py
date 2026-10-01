# -*- coding: utf-8 -*-
"""固定資產：資產卡片、直線法折舊、總帳事件（C6；proposal-gl/06-fixed-assets.md）。表在 accounting 的單一 migration（fa_*），無新 migration。

- 折舊（採用值）：每月＝(成本−殘值)÷(耐用年數×12)，以『累計值四捨五入相減』推算 ⇒ 最後一個月自然湊足（不殘留分位差）；
  起算月＝開始使用日所在月（該月提滿一個月）；殘值預設 成本÷(耐用年數+1)（待覆核，可自填）。
- 折舊只算**已結束的月份**（月底日 ≤ 今天），並且只算 status＝active 的資產；處分（disposed）之後不再折舊（處分事件在 C6b）。
- 事件（`gl.events`，來源 `fixed_assets`）：E13a 取得（資產卡片啟用）＝借 成本科目（稅碼 IN-FA）＋進項稅額／貸 應付設備款；
  E13b 每月折舊（source_key＝fa::YYYYMM）＝借 折舊費用／貸 累計折舊，依資產類別彙總成一張。
所有函式不 commit。
"""
import calendar
import datetime as _dt

from helpers.legal_params import round_half_up

#: 預設資產類別（採用值；來源＝財政部耐用年數表 106/02/03 令，辦公傢俱歸生財器具為推論）：(代碼, 名稱, 成本科目, 累計折舊, 費用科目, 年數, 表號)
DEFAULT_CATEGORIES = (
    ("computer", "電腦及周邊設備", "1431", "1432", "6125", 3, "32002"),
    ("network", "網路傳輸設備", "1431", "1432", "6125", 3, "31904"),
    ("cloud", "雲端資料運算及儲存設備", "1431", "1432", "6125", 3, "31901-31903"),
    ("furniture", "辦公傢俱、生財器具", "1431", "1432", "6125", 5, "32003"),
    ("surveillance", "監視設備", "1431", "1432", "6125", 3, "（表中無明確條目，暫比照 31905，待覆核）"),
    ("machinery", "機器設備", "1421", "1422", "6125", 5, "依行業細目"),
    ("leasehold", "租賃權益改良", "1461", "1462", "6125", 3, "依租期與表較短者"),
)
_TAX_CAPITALIZE_MIN = 80000          # 查核準則 §77-1（稅務判定，待使用者確認）
_TAX_MIN_LIFE = 2


class AssetError(ValueError):
    pass


_today = lambda: _dt.date.today()     # noqa: E731  測試可換掉


def ensure_categories(conn):
    for code, name, cost, accum, exp, years, ref in DEFAULT_CATEGORIES:
        conn.execute("INSERT OR IGNORE INTO fa_categories(code, name, cost_account, accum_account, expense_account, default_life_years, default_tax_life_years, life_table_ref)"
                     " VALUES (?,?,?,?,?,?,?,?)", (code, name, cost, accum, exp, years, years, ref))


def _date(v, label):
    try:
        return _dt.date.fromisoformat(str(v)).isoformat()
    except ValueError:
        raise AssertionError(label)


def default_salvage(cost, life):
    return int(round_half_up(cost / (life + 1)))


def _month_add(ym, k):
    y, m = int(ym[:4]), int(ym[5:7])
    t = y * 12 + (m - 1) + k
    return "%04d-%02d" % (t // 12, t % 12 + 1)


def _month_end(ym):
    return "%s-%02d" % (ym, calendar.monthrange(int(ym[:4]), int(ym[5:7]))[1])


def monthly_amount(asset, ym, revisions=()):
    """某資產某月的折舊額（整數）。第 k 個折舊月 k=1..N：累計(k)＝round(D×k÷N)，當月＝累計(k)－累計(k－1) ⇒ 最後一個月自然湊足。
    估計變動（`fa_revisions`，自 effective_month 起）：以『當時尚未提列的可折舊金額（成本－已提－新殘值）÷ 剩餘月數』重新推算；已過的月份不動。"""
    start = asset["in_service_on"][:7]
    cost = int(asset["cost"])
    revs = sorted(((r["effective_month"], int(r["life_years"]), int(r["salvage"])) for r in revisions), key=lambda x: x[0])
    seg_n, seg_dep, k = int(asset["life_years"]) * 12, max(0, cost - int(asset["salvage"])), 0
    booked, m, out = 0, start, 0
    while m <= ym:
        for eff, life, salv in [r for r in revs if r[0] == m or (r[0] < start and m == start)]:
            elapsed = _months_between(start, m)
            seg_n = max(1, life * 12 - elapsed)
            seg_dep = max(0, cost - booked - salv)
            k = 0
        k += 1
        if k <= seg_n:
            amt = int(round_half_up(seg_dep * k / seg_n)) - int(round_half_up(seg_dep * (k - 1) / seg_n))
        else:
            amt = 0
        booked += amt
        out = amt
        m = _month_add(m, 1)
    return int(out) if ym >= start else 0


def _months_between(a, b):
    return (int(b[:4]) - int(a[:4])) * 12 + int(b[5:7]) - int(a[5:7])


def _assets(conn, statuses=("active", "fully_depreciated")):
    ph = ",".join("?" * len(statuses))
    return [dict(r) for r in conn.execute("SELECT * FROM fa_assets WHERE status IN (%s) ORDER BY id" % ph, statuses)]


def _revisions(conn):
    out = {}
    for r in conn.execute("SELECT * FROM fa_revisions ORDER BY effective_month, id"):
        out.setdefault(r["asset_id"], []).append(dict(r))
    return out


def _cats(conn):
    return {r["code"]: dict(r) for r in conn.execute("SELECT * FROM fa_categories")}


# ── 資產卡片 ──────────────────────────────────────────────────────────

def next_asset_no(conn, year):
    n = conn.execute("SELECT COUNT(*) FROM fa_assets WHERE asset_no LIKE ?", ("FA-%d-%%" % year,)).fetchone()[0] + 1
    while conn.execute("SELECT 1 FROM fa_assets WHERE asset_no=?", ("FA-%d-%03d" % (year, n),)).fetchone():
        n += 1
    return "FA-%d-%03d" % (year, n)


def create_asset(conn, b, user):
    ensure_categories(conn)
    cat = _cats(conn).get(str(b.get("category") or ""))
    if not cat or not cat["is_active"]:
        raise AssetError("資產類別不存在或已停用。")
    name = str(b.get("name") or "").strip()
    if not name:
        raise AssetError("請填資產名稱。")
    try:
        acq = _date(b.get("acquired_on"), "取得日")
        svc = _date(b.get("in_service_on") or b.get("acquired_on"), "開始使用日")
    except AssertionError as e:
        raise AssetError("%s格式要是 YYYY-MM-DD。" % e)
    if svc < acq:
        raise AssetError("開始使用日不可早於取得日。")
    try:
        cost = int(b.get("cost"))
        tax = int(b.get("input_tax") or 0)
        life = int(b.get("life_years") or cat["default_life_years"])
    except (TypeError, ValueError):
        raise AssetError("成本、進項稅額、耐用年數要是整數。")
    if cost <= 0 or tax < 0 or life < 1 or life > 50:
        raise AssetError("成本要大於 0、進項稅額不可為負、耐用年數 1～50。")
    salvage = default_salvage(cost, life) if b.get("salvage") in (None, "") else int(b.get("salvage"))
    if salvage < 0 or salvage >= cost:
        raise AssetError("殘值要不小於 0 且小於成本。")
    tax_life = int(b.get("tax_life_years") or cat["default_tax_life_years"])
    tax_cap = 1 if (cost >= _TAX_CAPITALIZE_MIN and tax_life >= _TAX_MIN_LIFE) else 0
    no = next_asset_no(conn, int(acq[:4]))
    now = _dt.datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO fa_assets(asset_no, name, category, acquired_on, in_service_on, cost, input_tax, life_years, salvage, tax_life_years, tax_salvage,"
        " method, tax_capitalized, refund_flag, supplier_key, invoice_no, invoice_date, source_doc, case_no, dept_code, status, note, created_by, created_at)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?,'straight_line',?,?,?,?,?,?,?,?,'draft',?,?,?)",
        (no, name, cat["code"], acq, svc, cost, tax, life, salvage, tax_life, salvage, tax_cap, 1 if b.get("refund_flag") else 0,
         str(b.get("supplier_key") or ""), str(b.get("invoice_no") or ""), str(b.get("invoice_date") or "")[:10], str(b.get("source_doc") or ""),
         str(b.get("case_no") or ""), str(b.get("dept_code") or ""), str(b.get("note") or ""), user, now))
    return {"id": cur.lastrowid, "asset_no": no, "tax_capitalized": bool(tax_cap), "salvage": salvage}


def activate(conn, asset_id, user):
    a = conn.execute("SELECT * FROM fa_assets WHERE id=?", (asset_id,)).fetchone()
    if a is None:
        raise AssetError("找不到資產卡片。")
    if a["status"] != "draft":
        raise AssetError("只有草稿狀態的資產卡片可以啟用。")
    cat = _cats(conn).get(a["category"])
    if not cat or not cat["cost_account"] or not cat["accum_account"]:
        raise AssetError("資產類別沒有設定成本科目／累計折舊科目。")
    conn.execute("UPDATE fa_assets SET status='active' WHERE id=?", (asset_id,))
    return a["asset_no"]


def update_draft(conn, asset_id, b):
    a = conn.execute("SELECT status FROM fa_assets WHERE id=?", (asset_id,)).fetchone()
    if a is None:
        raise AssetError("找不到資產卡片。")
    if a["status"] != "draft":
        raise AssetError("啟用後的資產卡片不可直接修改；耐用年數／殘值的變動請用估計變動。")
    allowed = ("name", "acquired_on", "in_service_on", "cost", "input_tax", "life_years", "salvage", "invoice_no", "invoice_date", "supplier_key",
               "case_no", "dept_code", "note", "refund_flag")
    sets = {k: b[k] for k in allowed if k in b}
    if not sets:
        raise AssetError("沒有可更新的欄位。")
    for k in ("cost", "input_tax", "life_years", "salvage", "refund_flag"):
        if k in sets:
            try:
                sets[k] = int(sets[k])
            except (TypeError, ValueError):
                raise AssetError("%s 要是整數。" % k)
    conn.execute("UPDATE fa_assets SET " + ",".join("%s=?" % k for k in sets) + " WHERE id=?", list(sets.values()) + [asset_id])


def add_revision(conn, asset_id, effective_month, life_years, salvage, reason, user):
    a = conn.execute("SELECT * FROM fa_assets WHERE id=?", (asset_id,)).fetchone()
    if a is None or a["status"] not in ("active", "fully_depreciated"):
        raise AssetError("只有已啟用的資產可以做估計變動。")
    if not (isinstance(effective_month, str) and len(effective_month) == 7 and effective_month[4] == "-"):
        raise AssetError("生效月份格式要是 YYYY-MM。")
    if not reason or not str(reason).strip():
        raise AssetError("會計估計變動必須填原因。")
    if int(life_years) < 1 or int(salvage) < 0 or int(salvage) >= int(a["cost"]):
        raise AssetError("耐用年數要大於 0、殘值不小於 0 且小於成本。")
    posted = conn.execute("SELECT 1 FROM gl_source_events WHERE source_type='fa_depr' AND source_key >= ? AND status IN ('posted','drafted','drift') LIMIT 1",
                          ("fa::" + effective_month.replace("-", ""),)).fetchone()
    if posted:
        raise AssetError("該月份（含）之後已有折舊分錄；估計變動只能從尚未產生折舊草稿的月份起生效（不追溯）。")
    conn.execute("INSERT INTO fa_revisions(asset_id, effective_month, life_years, salvage, reason, created_by, created_at) VALUES (?,?,?,?,?,?,?)",
                 (asset_id, effective_month, int(life_years), int(salvage), str(reason).strip(), user, _dt.datetime.now().isoformat(timespec="seconds")))


# ── 折舊表 ────────────────────────────────────────────────────────────

def schedule(conn, ym):
    """截至某月（含）的折舊表：每資產 本期折舊、累計折舊、帳面價值，合計；與總帳成本／累計折舊科目對比。"""
    ensure_categories(conn)
    cats, revs = _cats(conn), _revisions(conn)
    rows, tot = [], {"cost": 0, "period": 0, "accum": 0, "book": 0}
    for a in _assets(conn):
        if a["in_service_on"][:7] > ym:
            continue
        rv = revs.get(a["id"], [])
        m, accum, period = a["in_service_on"][:7], 0, 0
        while m <= ym:
            amt = monthly_amount(a, m, rv)
            accum += amt
            if m == ym:
                period = amt
            m = _month_add(m, 1)
        rows.append({"id": a["id"], "asset_no": a["asset_no"], "name": a["name"], "category": a["category"], "acquired_on": a["acquired_on"],
                     "in_service_on": a["in_service_on"], "cost": a["cost"], "life_years": a["life_years"], "salvage": a["salvage"],
                     "life_table_ref": cats.get(a["category"], {}).get("life_table_ref", ""), "period": period, "accum": accum, "book": a["cost"] - accum})
        tot["cost"] += a["cost"]
        tot["period"] += period
        tot["accum"] += accum
        tot["book"] += a["cost"] - accum
    checks = []
    end = _month_end(ym)
    for label, key, side in (("成本科目", "cost_account", "D"), ("累計折舊科目", "accum_account", "C")):
        codes = sorted({c[key] for c in cats.values() if c[key]})
        if not codes:
            continue
        ph = ",".join("?" * len(codes))
        r = conn.execute("SELECT COALESCE(SUM(l.debit),0), COALESCE(SUM(l.credit),0) FROM voucher_lines l JOIN vouchers_all v ON v.id=l.voucher_id "
                         "WHERE v.status='已過帳' AND v.voided_at='' AND v.kind<>'closing' AND l.account_code IN (%s) AND substr(v.voucher_date,1,10) <= ?" % ph,
                         codes + [end]).fetchone()
        gl = int(r[0] - r[1]) if side == "D" else int(r[1] - r[0])
        want = tot["cost"] if side == "D" else tot["accum"]
        checks.append({"key": key, "label": "資產卡片合計 ＝ 總帳%s（%s）" % (label, "、".join(codes)), "left": want, "right": gl, "ok": want == gl,
                       "note": "不符多半是尚有未過帳的取得／折舊草稿，或科目上有手工傳票。"})
    return {"ym": ym, "rows": rows, "totals": tot, "checks": checks}


# ── 總帳事件提供者（gl.events，來源 fixed_assets）──────────────────────────────

def _acct(conn_cat, key):
    return conn_cat.get(key) or ""


def gl_events(start, end, *, changed_since=""):
    from db import get_db
    conn = get_db()
    try:
        ensure_categories(conn)
        conn.commit()
        cats, revs, assets = _cats(conn), _revisions(conn), _assets(conn)
        all_active = assets
    finally:
        conn.close()
    events, notices = [], []
    no_dates = 0
    for a in assets:
        cat = cats.get(a["category"]) or {}
        d = a["acquired_on"][:10]
        if start <= d <= end and a["cost"] > 0:
            cost_line = {"role": "FA_COST", "side": "D", "amount": int(a["cost"]), "memo": "取得 %s %s" % (a["asset_no"], a["name"]), "account_code": _acct(cat, "cost_account"),
                         "tax_code": "IN-FA", "case_no": a["case_no"]}
            lines = [cost_line]
            if a["input_tax"]:
                lines.append({"role": "INPUT_TAX", "side": "D", "amount": int(a["input_tax"]), "memo": "進項稅額 " + a["asset_no"], "tax_code": "IN-FA"})
            lines.append({"role": "FA_PAYABLE", "side": "C", "amount": int(a["cost"]) + int(a["input_tax"]), "memo": "應付設備款 " + a["asset_no"]})
            events.append({"source_type": "fa_asset", "source_key": a["asset_no"], "event_code": "E13a", "event_date": d, "doc_no": a["invoice_no"] or a["asset_no"],
                           "case_no": a["case_no"], "party": {"key": a["supplier_key"], "name": ""}, "tax_code": "IN-FA", "mode": "snapshot", "lines": lines,
                           "meta": {"category": a["category"], "refund_flag": bool(a["refund_flag"]), "tax_estimated": False}})
            if not a["invoice_no"]:
                no_dates += 1
    # 每月折舊：範圍內每個『已結束』的月份一張
    today = _today().isoformat()
    ym = start[:7]
    while ym <= end[:7]:
        me = _month_end(ym)
        if me <= today and me <= end:
            by_cat, detail = {}, []
            for a in all_active:
                if a["disposed_on"] and a["disposed_on"][:7] < ym:
                    continue
                amt = monthly_amount(a, ym, revs.get(a["id"], []))
                if amt:
                    by_cat[a["category"]] = by_cat.get(a["category"], 0) + amt
                    detail.append({"asset_no": a["asset_no"], "amount": amt})
            lines = []
            for code, amt in sorted(by_cat.items()):
                cat = cats.get(code) or {}
                lines.append({"role": "EXP_DEPR", "side": "D", "amount": amt, "memo": "折舊 %s %s" % (ym, cat.get("name", code)), "account_code": _acct(cat, "expense_account")})
                lines.append({"role": "ACCUM_DEPR", "side": "C", "amount": amt, "memo": "累計折舊 %s %s" % (ym, cat.get("name", code)), "account_code": _acct(cat, "accum_account")})
            if lines:
                events.append({"source_type": "fa_depr", "source_key": "fa::" + ym.replace("-", ""), "event_code": "E13b", "event_date": me,
                               "doc_no": "折舊" + ym, "case_no": "", "party": {"key": "", "name": ""}, "tax_code": "", "mode": "snapshot", "lines": lines,
                               "meta": {"assets": len(detail), "month": ym}})
        ym = _month_add(ym, 1)
    if no_dates:
        notices.append("%d 張資產卡片沒有取得發票號碼：取得分錄照常產生，請補發票資料（401 固定資產進項需要）。" % no_dates)
    return {"events": events, "notice": " ".join(notices)}
