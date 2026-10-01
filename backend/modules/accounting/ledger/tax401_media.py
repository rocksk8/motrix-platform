# -*- coding: utf-8 -*-
"""營業稅 401 媒體申報檔（附件六「營業人銷售額與稅額申報書檔」，112 欄）產生器——純函式，不碰資料庫、不接路由。

來源：財政部財政資訊中心《營業稅電子資料申報繳稅作業要點》附件六（113/04/12 台財資字第1130001073號令修正；
https://law-out.mof.gov.tw/Download.ashx?FileID=51326&id=GL009478&type=LAW ，存取 2026-10-01）。`FIELDS` 逐欄照該附件抄成。
檔案格式（附件六「說明」）：UTF-8 無 BOM；112 欄、每筆 111 個「|」；筆間 CRLF；屬性 `S9`／`9` 的數字欄不足位數左補 0；
欄內不可含換行；移除欄位前後多餘空白。`S9`＝末位帶正負號（要點第二十一點(十八)）：正 0-9 ⇒ `{ABCDEFGHI`，負 0-9 ⇒ `}JKLMNOPQR`。

公司登記資料（統編、稅籍編號、申報人…）一律是**參數**，不寫死；金額以官方「代號」為鍵（與 `tax401.py` 的 `lines` 同一套代號）。
欄 93～95（代號 113／114／115：得退稅限額合計、本期應退稅額、本期累積留抵稅額）的公式官方附件沒有（只有欄名），
主計單位尚未確認 ⇒ **不計算**：沒給就輸出 0，並在回傳的 `manual` 清單提醒呼叫端這三欄要人工填。
輸出不加任何推論：給的金額原樣編碼，不重算合計（合計欄由呼叫端依 `tax401.summarize` 提供）。
"""
import re

# ── 欄位表（序號, 屬性, 長度, 代號, 名稱）；與附件六逐欄一致（測試另以附件文字交叉核對）────────────────────────
#  屬性：X＝文字、C＝中文字（以字元數計）、9＝無號數字（9(n)）、S9＝帶正負號數字（末位 overpunch）
FIELDS = (
    (1, "X", 1, None, "資料別"), (2, "X", 8, None, "檔案編號"), (3, "X", 8, None, "統一編號"), (4, "X", 5, None, "所屬年月"),
    (5, "X", 1, None, "申報代號"), (6, "X", 9, None, "稅籍編號"), (7, "X", 1, None, "總繳代號"), (8, "9", 10, None, "使用發票份數"),
    (9, "S9", 12, 1, "應稅銷售額—三聯式發票"), (10, "S9", 12, 5, "應稅銷售額—收銀機發票(三聯式)及電子發票"),
    (11, "S9", 12, 9, "應稅銷售額—二聯式收銀機(二聯式)發票"), (12, "S9", 12, 13, "應稅銷售額—免用發票"),
    (13, "S9", 12, 17, "應稅銷售額—退回及折讓"), (14, "S9", 12, 21, "應稅銷售額—合計"),
    (15, "S9", 10, 2, "應稅稅額—三聯式發票"), (16, "S9", 10, 6, "應稅稅額—收銀機發票(三聯式)及電子發票"),
    (17, "S9", 10, 10, "應稅稅額—二聯式收銀機(二聯式)發票"), (18, "S9", 10, 14, "應稅稅額—免用發票"),
    (19, "S9", 10, 18, "應稅稅額—退回及折讓"), (20, "S9", 10, 22, "應稅稅額—合計"),
    (21, "S9", 12, 82, "免稅出口區內之區內事業…按進口報關程序銷售貨物至我國境內其他地區之免開立統一發票銷售額"),
    (22, "S9", 12, 7, "零稅率銷售額—非經海關出口應附證明文件者"), (23, "S9", 12, 15, "零稅率銷售額—經海關出口免附證明文件者"),
    (24, "S9", 12, 19, "零稅率銷售額—退回及折讓"), (25, "S9", 12, 23, "零稅率銷售額—合計"),
    (26, "S9", 12, 4, "免稅銷售額—三聯式發票"), (27, "S9", 12, 8, "免稅銷售額—收銀機發票(三聯式)及電子發票"),
    (28, "S9", 12, 12, "免稅銷售額—二聯式收銀機(二聯式)發票"), (29, "S9", 12, 16, "免稅銷售額—免用發票"),
    (30, "S9", 12, 20, "免稅銷售額—退回及折讓"), (31, "S9", 12, 24, "免稅銷售額—合計"),
    (32, "S9", 12, 52, "特種稅額—特種飲食 25% 銷售額"), (33, "S9", 10, 53, "特種稅額—特種飲食 25% 稅額"),
    (34, "S9", 12, 54, "特種稅額—特種飲食 15% 銷售額"), (35, "S9", 10, 55, "特種稅額—特種飲食 15% 稅額"),
    (36, "S9", 12, 56, "特種稅額—銀行保險信託 其他專屬本業收入 2% 銷售額"), (37, "S9", 10, 57, "特種稅額—銀行保險信託 其他專屬本業收入 2% 稅額"),
    (38, "S9", 12, 58, "特種稅額—銀行保險信託 非專屬本業收入 5% 銷售額"), (39, "S9", 10, 59, "特種稅額—銀行保險信託 非專屬本業收入 5% 稅額"),
    (40, "S9", 12, 60, "特種稅額—再保收入 1% 銷售額"), (41, "S9", 10, 61, "特種稅額—再保收入 1% 稅額"),
    (42, "S9", 12, 62, "特種稅額—免稅收入 銷售額"), (43, "S9", 12, 63, "特種稅額—退回及折讓 銷售額"),
    (44, "S9", 10, 64, "特種稅額—退回及折讓 稅額"), (45, "S9", 12, 65, "特種稅額—合計 銷售額"), (46, "S9", 10, 66, "特種稅額—合計 稅額"),
    (47, "S9", 12, 25, "銷售額分析—銷售額總計"), (48, "S9", 12, 26, "銷售額分析—土地"), (49, "S9", 12, 27, "銷售額分析—其他固定之資產"),
    (50, "S9", 12, 28, "進項金額—統一發票扣抵聯 進貨及費用"), (51, "S9", 12, 30, "進項金額—統一發票扣抵聯 固定資產"),
    (52, "S9", 12, 32, "進項金額—三聯式收銀機發票扣抵聯及電子發票 進貨及費用"), (53, "S9", 12, 34, "進項金額—三聯式收銀機發票扣抵聯及電子發票 固定資產"),
    (54, "S9", 12, 36, "進項金額—載有稅額之其他憑證 進貨及費用"), (55, "S9", 12, 38, "進項金額—載有稅額之其他憑證 固定資產"),
    (56, "S9", 12, 40, "進項金額—退出及折讓 進貨及費用"), (57, "S9", 12, 42, "進項金額—退出及折讓 固定資產"),
    (58, "S9", 12, 44, "進項金額—合計 進貨及費用"), (59, "S9", 12, 46, "進項金額—合計 固定資產"),
    (60, "S9", 10, 29, "進項稅額—統一發票扣抵聯 進貨及費用"), (61, "S9", 10, 31, "進項稅額—統一發票扣抵聯 固定資產"),
    (62, "S9", 10, 33, "進項稅額—三聯式收銀機發票扣抵聯及電子發票 進貨及費用"), (63, "S9", 10, 35, "進項稅額—三聯式收銀機發票扣抵聯及電子發票 固定資產"),
    (64, "S9", 10, 37, "進項稅額—載有稅額之其他憑證 進貨及費用"), (65, "S9", 10, 39, "進項稅額—載有稅額之其他憑證 固定資產"),
    (66, "S9", 10, 41, "進項稅額—退出及折讓 進貨及費用"), (67, "S9", 10, 43, "進項稅額—退出及折讓 固定資產"),
    (68, "S9", 10, 45, "進項稅額—合計 進貨及費用"), (69, "S9", 10, 47, "進項稅額—合計 固定資產"),
    (70, "S9", 12, 48, "進項總金額 進貨及費用"), (71, "S9", 12, 49, "進項總金額 固定資產"),
    (72, "9", 3, 50, "兼營—不得扣抵比例"), (73, "S9", 10, 51, "兼營—得扣抵之進項稅額"),
    (74, "S9", 12, 78, "海關代徵營業稅繳納證扣抵聯 進貨及費用金額"), (75, "S9", 12, 80, "海關代徵營業稅繳納證扣抵聯 固定資產金額"),
    (76, "S9", 12, 73, "進口免稅貨物"), (77, "S9", 12, 74, "購買國外勞務給付額之購買國外勞務稅額計算"),
    (78, "S9", 10, 79, "海關代徵營業稅繳納證扣抵聯 進貨及費用稅額"), (79, "S9", 10, 81, "海關代徵營業稅繳納證扣抵聯 固定資產稅額"),
    (80, "S9", 10, 75, "營業稅額之購買國外勞務稅額計算"), (81, "S9", 10, 76, "應納稅額之購買國外勞務稅額計算"),
    (82, "S9", 10, 101, "本(期)月銷項稅額合計"), (83, "S9", 10, 103, "購買國外勞務應納稅額"), (84, "S9", 10, 104, "特種稅額計算應納稅額"),
    (85, "S9", 10, 105, "中途歇業年底調整補徵應繳稅額"), (86, "S9", 10, 106, "小計(1+3+4+5)"), (87, "S9", 10, 107, "得扣抵進項稅額合計"),
    (88, "S9", 10, 108, "上期(月)累積留抵稅額"), (89, "S9", 10, 109, "中途歇業或年底調整應退稅額"), (90, "S9", 10, 110, "小計(7+8+9)"),
    (91, "S9", 10, 111, "本期(月)應實繳稅額(6-10)"), (92, "S9", 10, 112, "本期(月)申報留抵稅額(10-6)"),
    (93, "S9", 10, 113, "得退稅限額合計"), (94, "S9", 10, 114, "本期(月)應退稅額"), (95, "S9", 10, 115, "本期(月)累積留抵稅額"),
    (96, "X", 1, None, "申報種類"), (97, "X", 1, None, "縣市別"), (98, "X", 1, None, "自行或委託辦理申報註記"),
    (99, "X", 10, None, "申報人身分證統一編號"), (100, "C", 12, None, "申報人姓名"), (101, "X", 4, None, "申報人電話區域碼"),
    (102, "X", 11, None, "申報人電話"), (103, "X", 5, None, "申報人電話分機"), (104, "C", 50, None, "代理申報人登錄（文）字號"),
    (105, "S9", 12, 67, "購買國外勞務—外國保險業再保費收入給付金額"), (106, "S9", 12, 69, "購買國外勞務—第11條各業專屬本業勞務給付金額"),
    (107, "S9", 12, 71, "購買國外勞務—其他給付金額"), (108, "S9", 10, 68, "購買國外勞務—外國保險業再保費收入稅額"),
    (109, "S9", 10, 70, "購買國外勞務—第11條各業專屬本業勞務稅額"), (110, "S9", 10, 72, "購買國外勞務—其他稅額"),
    (111, "S9", 12, 84, "銀行業、保險業經營銀行、保險本業收入5% 銷售額"), (112, "S9", 10, 85, "銀行業、保險業經營銀行、保險本業收入5% 稅額"),
)

#: 公式未確認、不計算的代號（欄 93～95）：沒給金額就輸出 0，並列在回傳的 manual 清單
MANUAL_CODES = (113, 114, 115)

#: 參數鍵（文字欄）⇒ 序號。公司登記資料等由呼叫端提供，這裡不寫死任何值。
PARAM_SEQ = {"data_type": 1, "file_no": 2, "tax_id": 3, "period": 4, "filing_code": 5, "tax_reg_no": 6, "consolidated_code": 7,
             "invoice_count": 8, "filing_kind": 96, "county_code": 97, "self_or_agent": 98, "filer_id": 99, "filer_name": 100,
             "filer_phone_area": 101, "filer_phone": 102, "filer_phone_ext": 103, "agent_license": 104}
#: 這些文字欄必須剛好這個長度（官方：檔案編號 8 位補零、統編 8 碼、所屬年月 3 位民國年＋2 位月、稅籍編號 9 碼；資料別／代號類 1 碼）
_EXACT_LEN = {1: 1, 2: 8, 3: 8, 4: 5, 5: 1, 6: 9, 7: 1, 96: 1, 97: 1, 98: 1}
#: 必填的參數（其餘可留空 ⇒ 輸出空字串，欄位仍保留分隔符）
REQUIRED_PARAMS = ("data_type", "file_no", "tax_id", "period", "filing_code", "tax_reg_no", "consolidated_code", "invoice_count", "filing_kind")

_POS = "{ABCDEFGHI"
_NEG = "}JKLMNOPQR"


class Tax401MediaError(ValueError):
    pass


def encode_s9(value, width: int) -> str:
    """整數 ⇒ 寬度 `width` 的 S9 字串：左補 0，末位數字換成帶正負號的字元（正 `{ABCDEFGHI`、負 `}JKLMNOPQR`）。超出寬度 ⇒ 報錯（不截斷）。"""
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, float) and value == int(value):
            value = int(value)
        else:
            raise Tax401MediaError("S9 欄位只收整數（元）：%r" % (value,))
    digits = str(abs(value))
    if len(digits) > width:
        raise Tax401MediaError("金額 %d 超出 S9(%d) 的位數" % (value, width))
    digits = digits.rjust(width, "0")
    table = _NEG if value < 0 else _POS
    return digits[:-1] + table[int(digits[-1])]


def encode_9(value, width: int) -> str:
    """無號整數 ⇒ 寬度 `width` 左補 0 的數字字串。負數或超出位數 ⇒ 報錯。"""
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and value.strip().isdigit():
            value = int(value.strip())
        else:
            raise Tax401MediaError("9 欄位只收非負整數：%r" % (value,))
    if value < 0 or len(str(value)) > width:
        raise Tax401MediaError("數值 %d 不合 9(%d)" % (value, width))
    return str(value).rjust(width, "0")


def clean_text(value, length: int, label: str, exact: bool = False) -> str:
    """文字欄：去前後空白；不可含換行或欄位分隔符「|」；長度（以字元計）不可超過 `length`（`exact` ⇒ 必須剛好）。"""
    s = "" if value is None else str(value).strip()
    if any(c in s for c in "\r\n|"):
        raise Tax401MediaError("%s 不可含換行或「|」" % label)
    if len(s) > length or (exact and len(s) != length):
        raise Tax401MediaError("%s 長度必須%s %d 個字元：%r" % (label, "剛好" if exact else "不超過", length, s))
    return s


def build_record(params: dict, amounts: dict = None):
    """一筆 401 記錄 ⇒ `(字串, manual)`。

    `params`：公司登記與申報資料（鍵見 `PARAM_SEQ`；`REQUIRED_PARAMS` 必填，其餘可省略）。
    `amounts`：官方代號 ⇒ 整數（元；負數 OK）。沒給的欄位輸出 0；未知代號 ⇒ 報錯（打錯字不可無聲吃掉）。
    `manual`：公式未確認而被預設成 0 的代號（113／114／115 沒給時）。
    """
    params = dict(params or {})
    amounts = {int(k): v for k, v in (amounts or {}).items()}
    unknown = set(params) - set(PARAM_SEQ)
    if unknown:
        raise Tax401MediaError("未知的參數鍵：%s" % ", ".join(sorted(unknown)))
    missing = [k for k in REQUIRED_PARAMS if params.get(k) in (None, "")]
    if missing:
        raise Tax401MediaError("缺必填參數：%s" % ", ".join(missing))
    known_codes = {f[3] for f in FIELDS if f[3] is not None}
    bad = sorted(set(amounts) - known_codes)
    if bad:
        raise Tax401MediaError("未知的代號：%s" % ", ".join(str(c) for c in bad))
    by_seq = {seq: key for key, seq in PARAM_SEQ.items()}
    out = []
    for seq, attr, length, code, name in FIELDS:
        label = "第 %d 欄「%s」" % (seq, name)
        if code is None:
            key = by_seq[seq]
            v = params.get(key)
            if attr == "9":
                out.append(encode_9(0 if v in (None, "") else v, length))
            else:
                out.append(clean_text(v, length, label, exact=seq in _EXACT_LEN))
        elif attr == "S9":
            out.append(encode_s9(amounts.get(code, 0), length))
        else:                                                  # "9"（72 不得扣抵比例）
            out.append(encode_9(amounts.get(code, 0), length))
    assert len(out) == 112
    manual = [c for c in MANUAL_CODES if c not in amounts]
    return "|".join(out), manual


def to_file_bytes(records, trailing_newline: bool = False) -> bytes:
    """多筆記錄 ⇒ 檔案位元組：UTF-8 無 BOM、筆間 CRLF（`trailing_newline` ⇒ 最後一筆後面也加 CRLF，視申報軟體而定）。"""
    for r in records:
        if r.count("|") != 111 or "\r" in r or "\n" in r:
            raise Tax401MediaError("記錄格式不合：必須 111 個「|」且不含換行")
    text = "\r\n".join(records) + ("\r\n" if trailing_newline and records else "")
    return text.encode("utf-8")
