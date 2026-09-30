# -*- coding: utf-8 -*-
"""財務報表的列定義（gl_fs_lines）與現金流量分類（cashflow_class）。設計：proposal-gl/04-reports.md §3、§5。

B1：只做「定義與守門」——報表本身（資產負債表、綜合損益表、權益變動表、現金流量表）在 B2～B4。
會計師可調整列的名稱、排序、停用與科目的歸屬，列代碼固定（報表程式依代碼取數）。
"""
import re

#: 現金流量分類：cash＝現金及約當現金；operating／investing／financing＝三大活動（間接法下，每個非現金資產負債科目的
#: 期間變動歸入其中一類；累計折舊等調整科目歸 operating；保留盈餘變動扣除本期淨利後歸 financing，見 B4）。
CASHFLOW_CLASSES = ("cash", "operating", "investing", "financing")

#: 需要現金流量分類的科目類別（資產負債表科目）。損益科目不分類（淨利整體進營業活動）。
BS_TYPES = ("asset", "liability", "equity")

# 列定義：(代碼, 報表, 名稱, 排序, 方向, 類型)。方向＝呈現時的正常方向；類型 line＝有科目歸入、computed＝由其他列計算。
_BS = [
    ("BS_CA_CASH", "現金及約當現金", "D"), ("BS_CA_FIN", "金融資產—流動", "D"), ("BS_CA_NOTES", "應收票據淨額", "D"),
    ("BS_CA_AR", "應收帳款淨額", "D"), ("BS_CA_OTHER_AR", "其他應收款", "D"), ("BS_CA_TAX", "本期所得稅資產", "D"),
    ("BS_CA_INV", "存貨", "D"), ("BS_CA_BIO", "生物資產—流動", "D"), ("BS_CA_PREPAID", "預付款項", "D"),
    ("BS_CA_OTHER", "其他流動資產", "D"),
    ("BS_NCA_FIN", "金融資產—非流動", "D"), ("BS_NCA_EQUITY_INV", "採用權益法之投資", "D"),
    ("BS_NCA_INVPROP", "投資性不動產", "D"), ("BS_NCA_PPE", "不動產、廠房及設備", "D"), ("BS_NCA_MINERAL", "礦產資源", "D"),
    ("BS_NCA_BIO", "生物資產—非流動", "D"), ("BS_NCA_INTANGIBLE", "無形資產", "D"), ("BS_NCA_DTA", "遞延所得稅資產", "D"),
    ("BS_NCA_OTHER", "其他非流動資產", "D"),
    ("BS_CL_STB", "短期借款及應付短期票券", "C"), ("BS_CL_FIN", "金融負債—流動", "C"), ("BS_CL_NOTES", "應付票據", "C"),
    ("BS_CL_AP", "應付帳款", "C"), ("BS_CL_CONTRACT", "應付建造合約款", "C"), ("BS_CL_OTHER_AP", "其他應付款", "C"),
    ("BS_CL_TAX", "本期所得稅負債", "C"), ("BS_CL_ADV", "預收款項", "C"), ("BS_CL_LTD_CUR", "一年內到期長期負債", "C"),
    ("BS_CL_PROV", "負債準備—流動", "C"), ("BS_CL_OTHER", "其他流動負債", "C"), ("BS_NCL", "非流動負債", "C"),
    ("BS_EQ_CAPITAL", "股本", "C"), ("BS_EQ_CAPSURPLUS", "資本公積", "C"), ("BS_EQ_RE", "保留盈餘（累積盈虧）", "C"),
    ("BS_EQ_OTHER", "其他權益", "C"), ("BS_EQ_TREASURY", "庫藏股票", "D"),
]
_IS = [
    ("IS_REV", "營業收入", "C", "line"), ("IS_REV_ALLOW", "銷貨退回及折讓", "D", "line"), ("IS_COST", "營業成本", "D", "line"),
    ("IS_GP", "營業毛利", "C", "computed"), ("IS_OPEX", "營業費用", "D", "line"), ("IS_OP", "營業淨利", "C", "computed"),
    ("IS_NONOP_INC", "營業外收益", "C", "line"), ("IS_NONOP_EXP", "營業外費損", "D", "line"),
    ("IS_PBT", "稅前淨利", "C", "computed"), ("IS_TAX", "所得稅費用", "D", "line"), ("IS_DISCONT", "停業單位損益", "C", "line"),
    ("IS_NI", "本期淨利", "C", "computed"), ("IS_OCI", "其他綜合損益", "C", "line"), ("IS_TCI", "本期綜合損益總額", "C", "computed"),
]


def seed_rows():
    rows = []
    for i, (code, label, side) in enumerate(_BS, start=1):
        rows.append((code, "BS", label, i * 10, side, "line"))
    for i, (code, label, side, kind) in enumerate(_IS, start=1):
        rows.append((code, "IS", label, i * 10, side, kind))
    return rows


def ensure_fs_lines(conn):
    """補齊缺的報表列（不覆蓋會計師改過的名稱／排序／停用）。回新增筆數。不 commit。"""
    have = {r[0] for r in conn.execute("SELECT code FROM gl_fs_lines")}
    added = 0
    for code, stmt, label, sort, side, kind in seed_rows():
        if code not in have:
            conn.execute("INSERT INTO gl_fs_lines(code,statement,label,sort,side,kind) VALUES(?,?,?,?,?,?)",
                         (code, stmt, label, sort, side, kind))
            added += 1
    return added


# ── 現金流量分類的預設推導 ────────────────────────────────────────────────
# 依項目表 L3 群組（祖先鏈由近到遠第一個命中）。營運＝營運資金與調整；投資＝長期資產；籌資＝借款與權益。
_CF_BY_GROUP = {
    "111": "cash",
    "112": "investing", "113": "investing", "114": "investing", "115": "investing", "117": "investing",
    "118": "operating", "119": "operating", "120": "operating", "121": "operating", "122": "operating",
    "123-124": "operating", "125": "operating", "126-127": "operating", "128": "operating",
    "131": "investing", "132": "investing", "133": "investing", "134": "investing", "136": "investing",
    "137": "investing", "138": "investing", "139": "investing", "147": "investing", "148": "investing",
    "149-155": "investing", "156": "operating", "157-158": "investing",
    "211": "financing", "212": "financing", "213": "financing", "214": "financing", "215": "financing",
    "216": "operating", "217": "operating", "218": "operating", "219-220": "operating", "221": "operating",
    "222": "operating", "223": "financing", "224": "operating", "225": "operating", "23": "financing",
    "31": "financing", "32": "financing", "33": "financing", "34": "operating", "35": "financing",
}
_CF_BY_CODE = {
    "1283": "operating", "1284": "operating", "1584": "financing", "1585": "financing", "1583": "operating",
    "2198": "investing", "2199": "investing", "2201": "financing", "2371": "operating", "2372": "operating",
    "2373": "operating", "2374": "operating", "2391": "operating", "2392": "operating", "2393": "financing",
    "2394": "financing", "2395": "operating",
}
_ACCUM = re.compile(r"累計(折舊|攤銷|折耗|減損)|備抵")


def derive_cashflow(code, acct_type, name, chain):
    """回 cashflow_class；損益類回 ''（不分類）。`chain`＝自己到最上層的代號鏈。"""
    if acct_type not in BS_TYPES:
        return ""
    if code in _CF_BY_CODE:
        return _CF_BY_CODE[code]
    if acct_type == "asset" and _ACCUM.search(name or ""):
        return "operating"               # 累計折舊／攤銷／減損、備抵：非現金調整，間接法下歸營業活動
    for c in chain:
        if c in _CF_BY_GROUP:
            return _CF_BY_GROUP[c]
    return ""


def fill_cashflow_defaults(conn, meta_rows, parents, names):
    """把 gl_account_meta 中 cashflow_class 為空的資產負債科目補上預設（不覆蓋已設定的）。回補的筆數。不 commit。
    `meta_rows`：{code: (acct_type, 已有的 cashflow_class)}；自訂科目繼承最近一層已分類的祖先。"""
    from modules.accounting.ledger.roles import _ancestors
    n = 0
    have = {c: v[1] for c, v in meta_rows.items()}
    for code in sorted(meta_rows, key=lambda c: (len(c), c)):
        typ, cur = meta_rows[code]
        if cur or typ not in BS_TYPES:
            continue
        chain = _ancestors(code, parents)
        cf = derive_cashflow(code, typ, names.get(code, ""), chain)
        if not cf:
            for anc in chain[1:]:
                if have.get(anc):
                    cf = have[anc]
                    break
        if cf:
            conn.execute("UPDATE gl_account_meta SET cashflow_class=? WHERE code=? AND cashflow_class=''", (cf, code))
            have[code] = cf
            n += 1
    return n


# ── 守門查詢 ─────────────────────────────────────────────────────────────

def unclassified_cashflow(conn):
    """可過帳、未停用、資產負債類、卻沒有現金流量分類的科目（B4 的現金流量表會漏算它們）。"""
    return [r[0] for r in conn.execute(
        "SELECT code FROM gl_account_meta WHERE postable=1 AND is_active=1 AND cashflow_class='' AND acct_type IN ('asset','liability','equity')"
        " ORDER BY code")]


def unknown_fs_lines(conn):
    """gl_account_meta 用到、卻不在 gl_fs_lines 的報表列代碼（報表會找不到這一列）。"""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT m.fs_line FROM gl_account_meta m LEFT JOIN gl_fs_lines f ON f.code=m.fs_line"
        " WHERE m.fs_line<>'' AND f.code IS NULL ORDER BY 1")]


def inactive_lines_in_use(conn):
    """已停用的報表列卻仍有可過帳科目歸屬（停用會讓報表漏算它們）。"""
    return [r[0] for r in conn.execute(
        "SELECT DISTINCT f.code FROM gl_fs_lines f JOIN gl_account_meta m ON m.fs_line=f.code"
        " WHERE f.is_active=0 AND m.postable=1 AND m.is_active=1 ORDER BY 1")]


def list_fs_lines(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM gl_fs_lines ORDER BY statement, sort, code")]
