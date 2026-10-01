# -*- coding: utf-8 -*-
"""401 媒體申報檔產生器（`ledger/tax401_media.py`；附件六 112 欄）：格式規則與欄位表。

三道獨立的證據，互不借用：
① **官方文字交叉核對**：`OFFICIAL` 是從財政部附件六 PDF（存取 2026-10-01，markitdown 轉文字）逐列抽出的 `序號 屬性(長度) 代號`，
   測試用另一套解析重算，與 `FIELDS` 逐欄比對（抄表打錯一個長度或代號就紅）。
② **手工組出的整筆記錄**：`test_hand_built_record_matches_field_by_field` 用寫在測試裡的字串逐段拼出期望值（不經過 `FIELDS`）。
③ **規則題**：UTF-8 無 BOM、111 個「|」、筆間 CRLF、數字左補 0、S9 末位符號表 `{ABCDEFGHI`／`}JKLMNOPQR`、文字欄去空白／拒換行與「|」、
   必填與未知鍵報錯、113～115 沒給就列入 manual。每條規則各有一題反向（錯的輸入 ⇒ 報錯／結果不同）。
"""
import re

import pytest

from modules.accounting.ledger import tax401_media as M

OFFICIAL = """
1 X(001) -
2 X(008) -
3 X(008) -
4 X(005) -
5 X(001) -
6 X(009) -
7 X(001) -
8 9(010) -
9 S9(012) 1
10 S9(012) 5
11 S9(012) 9
12 S9(012) 13
13 S9(012) 17
14 S9(012) 21
15 S9(010) 2
16 S9(010) 6
17 S9(010) 10
18 S9(010) 14
19 S9(010) 18
20 S9(010) 22
21 S9(012) 82
22 S9(012) 7
23 S9(012) 15
24 S9(012) 19
25 S9(012) 23
26 S9(012) 4
27 S9(012) 8
28 S9(012) 12
29 S9(012) 16
30 S9(012) 20
31 S9(012) 24
32 S9(012) 52
33 S9(010) 53
34 S9(012) 54
35 S9(010) 55
36 S9(012) 56
37 S9(010) 57
38 S9(012) 58
39 S9(010) 59
40 S9(012) 60
41 S9(010) 61
42 S9(012) 62
43 S9(012) 63
44 S9(010) 64
45 S9(012) 65
46 S9(010) 66
47 S9(012) 25
48 S9(012) 26
49 S9(012) 27
50 S9(012) 28
51 S9(012) 30
52 S9(012) 32
53 S9(012) 34
54 S9(012) 36
55 S9(012) 38
56 S9(012) 40
57 S9(012) 42
58 S9(012) 44
59 S9(012) 46
60 S9(010) 29
61 S9(010) 31
62 S9(010) 33
63 S9(010) 35
64 S9(010) 37
65 S9(010) 39
66 S9(010) 41
67 S9(010) 43
68 S9(010) 45
69 S9(010) 47
70 S9(012) 48
71 S9(012) 49
72 9(003) 50
73 S9(010) 51
74 S9(012) 78
75 S9(012) 80
76 S9(012) 73
77 S9(012) 74
78 S9(010) 79
79 S9(010) 81
80 S9(010) 75
81 S9(010) 76
82 S9(010) 101
83 S9(010) 103
84 S9(010) 104
85 S9(010) 105
86 S9(010) 106
87 S9(010) 107
88 S9(010) 108
89 S9(010) 109
90 S9(010) 110
91 S9(010) 111
92 S9(010) 112
93 S9(010) 113
94 S9(010) 114
95 S9(010) 115
96 X(001) -
97 X(001) -
98 X(001) -
99 X(010) -
100 C(012) -
101 X(004) -
102 X(011) -
103 X(005) -
104 C(050) -
105 S9(012) 67
106 S9(012) 69
107 S9(012) 71
108 S9(010) 68
109 S9(010) 70
110 S9(010) 72
111 S9(012) 84
112 S9(010) 85
"""


def _official():
    rows = []
    for ln in OFFICIAL.strip().splitlines():
        m = re.match(r"^(\d+) (X|C|S9|9)\((\d+)\) (\d+|-)$", ln.strip())
        assert m, ln
        rows.append((int(m.group(1)), m.group(2), int(m.group(3)), None if m.group(4) == "-" else int(m.group(4))))
    return rows


def _compare(fields):
    got = [(f[0], f[1], f[2], f[3]) for f in fields]
    diffs = [(g, o) for g, o in zip(got, _official()) if g != o]
    return diffs + ([("欄數不同", len(got), 112)] if len(got) != 112 else [])


def test_field_table_equals_the_official_attachment_text():
    assert len(M.FIELDS) == 112 and [f[0] for f in M.FIELDS] == list(range(1, 113))
    assert _compare(M.FIELDS) == []


def test_cross_check_detects_a_wrong_width_or_code():
    """反向控制：改一欄的長度或代號 ⇒ 交叉核對必須抓到（偵測器本身有被驗過）。"""
    bad = list(M.FIELDS)
    bad[8] = (9, "S9", 10, 1, "x")                      # 序號 9 長度 12 → 10
    assert _compare(bad)
    bad = list(M.FIELDS)
    bad[40] = (41, "S9", 10, 99, "x")                    # 序號 41 代號 61 → 99
    assert _compare(bad)


# ── 手工組出的期望值（不經過 FIELDS）─────────────────────────────────────────

Z12, Z10 = "00000000000{", "000000000{"
PARAMS = {"data_type": "1", "file_no": "00000001", "tax_id": "12345678", "period": "11510", "filing_code": "1", "tax_reg_no": "A12345678",
          "consolidated_code": "0", "invoice_count": 12, "filing_kind": "1", "county_code": "B", "self_or_agent": "1",
          "filer_id": "A123456789", "filer_name": "王小明", "filer_phone_area": "04", "filer_phone": "23456789", "filer_phone_ext": "",
          "agent_license": ""}


def test_hand_built_record_matches_field_by_field():
    head = ["1", "00000001", "12345678", "11510", "1", "A12345678", "0", "0000000012"]                    # 序號 1～8
    taxable_sales = ["00000012345F"] + [Z12] * 5                                                             # 9～14（序號 9＝代號 1＝123456 ⇒ 末位 6→F）
    taxable_tax = ["000000617C"] + [Z10] * 5                                                                 # 15～20（序號 15＝代號 2＝6173 ⇒ 末位 3→C）
    free_invoice = [Z12]                                                                                     # 21
    zero_and_exempt = [Z12] * 10                                                                             # 22～31
    special = [Z12, Z10, Z12, Z10, Z12, Z10, Z12, Z10, Z12, Z10, Z12, Z12, Z10, Z12, Z10]                    # 32～46（42、43 只有銷售額；44 稅額）
    analysis = [Z12] * 3                                                                                     # 47～49
    in_amount = [Z12] * 6 + ["00000000005}"] + [Z12] * 3                                                     # 50～59（序號 56＝代號 40＝-50 ⇒ 末位 0 的負號是 }）
    in_tax = [Z10] * 10                                                                                      # 60～69
    in_total = [Z12] * 2                                                                                     # 70～71
    mixed = ["000", Z10]                                                                                     # 72 不得扣抵比例 9(3)、73
    customs_foreign = [Z12] * 4 + [Z10] * 4                                                                  # 74～77、78～81
    calc = ["000000617C"] + [Z10] * 13                                                                       # 82～95（序號 82＝代號 101＝6173）
    filer = ["1", "B", "1", "A123456789", "王小明", "04", "23456789", "", ""]                                # 96～104
    foreign_items = [Z12] * 3 + [Z10] * 3 + [Z12, Z10]                                                       # 105～107、108～110、111、112
    expected = (head + taxable_sales + taxable_tax + free_invoice + zero_and_exempt + special + analysis + in_amount + in_tax
                + in_total + mixed + customs_foreign + calc + filer + foreign_items)
    assert len(expected) == 112
    line, manual = M.build_record(PARAMS, {1: 123456, 2: 6173, 101: 6173, 40: -50})
    assert line == "|".join(expected)
    assert line.count("|") == 111 and manual == [113, 114, 115]


# ── 規則 ─────────────────────────────────────────────────────────────────

def test_signed_digit_sign_map_exhaustive():
    for d in range(1, 10):
        assert M.encode_s9(d, 3) == "00" + "{ABCDEFGHI"[d]                         # 正 1-9
        assert M.encode_s9(-d, 3) == "00" + "}JKLMNOPQR"[d]                        # 負 1-9
    assert M.encode_s9(0, 3) == "00{"
    assert M.encode_s9(-10, 3) == "01}" and M.encode_s9(10, 3) == "01{"            # 末位 0：正 { 負 }
    assert M.encode_s9(0, 12) == "00000000000{" and M.encode_s9(-123, 12) == "00000000012L" and M.encode_s9(123, 10) == "000000012C"


def test_signed_digit_overflow_and_non_integers_are_errors_not_truncation():
    for bad in (10 ** 12, -(10 ** 12), "12", 1.5, None, True):
        with pytest.raises(M.Tax401MediaError):
            M.encode_s9(bad, 12)
    assert M.encode_s9(999999999999, 12) == "99999999999I"                         # 剛好滿位
    assert M.encode_s9(1000.0, 12) == "00000000100{"                               # 整數值的 float 容許


def test_unsigned_9_left_zero_pad_and_range():
    assert M.encode_9(0, 3) == "000" and M.encode_9(7, 3) == "007" and M.encode_9(100, 3) == "100" and M.encode_9("12", 10) == "0000000012"
    for bad in (-1, 1000, "x", None):
        with pytest.raises(M.Tax401MediaError):
            M.encode_9(bad, 3)


def test_text_rules_trim_reject_newline_pipe_and_length():
    assert M.clean_text("  A12  ", 9, "x") == "A12"
    for bad in ("a\nb", "a\rb", "a|b"):
        with pytest.raises(M.Tax401MediaError):
            M.clean_text(bad, 9, "x")
    with pytest.raises(M.Tax401MediaError):
        M.clean_text("1234567890", 9, "x")
    with pytest.raises(M.Tax401MediaError):
        M.clean_text("123", 8, "x", exact=True)
    assert M.clean_text(None, 5, "x") == ""


def test_required_and_unknown_inputs_are_errors():
    with pytest.raises(M.Tax401MediaError, match="缺必填參數"):
        M.build_record({k: v for k, v in PARAMS.items() if k != "tax_id"}, {})
    with pytest.raises(M.Tax401MediaError, match="未知的參數鍵"):
        M.build_record(dict(PARAMS, taxid="x"), {})
    with pytest.raises(M.Tax401MediaError, match="未知的代號"):
        M.build_record(PARAMS, {999: 1})
    for k, v in (("tax_id", "1234567"), ("period", "1151"), ("file_no", "1"), ("tax_reg_no", "A1234567"), ("data_type", "12")):
        with pytest.raises(M.Tax401MediaError):
            M.build_record(dict(PARAMS, **{k: v}), {})                              # 長度固定的欄位少一位也不行


def test_113_to_115_are_manual_unless_given():
    _line, manual = M.build_record(PARAMS, {})
    assert manual == [113, 114, 115]
    line, manual = M.build_record(PARAMS, {113: 10, 114: 5, 115: 7})
    assert manual == [] and line.split("|")[92:95] == ["000000001{", "000000000E", "000000000G"]


def test_file_bytes_utf8_no_bom_crlf_between_and_111_pipes():
    a, _ = M.build_record(PARAMS, {1: 1})
    b, _ = M.build_record(dict(PARAMS, file_no="00000002"), {1: 2})
    data = M.to_file_bytes([a, b])
    assert not data.startswith(b"\xef\xbb\xbf")                                    # 無 BOM
    assert data.decode("utf-8") == a + "\r\n" + b and data.count(b"\r\n") == 1       # 筆間 CRLF（不是 LF）
    assert b"\n" not in data.replace(b"\r\n", b"")
    assert all(rec.count(b"|") == 111 for rec in data.split(b"\r\n"))
    assert "王小明".encode("utf-8") in data                                          # 中文以 UTF-8 輸出
    assert M.to_file_bytes([a], trailing_newline=True).endswith(b"\r\n")
    with pytest.raises(M.Tax401MediaError):
        M.to_file_bytes(["a|b"])                                                    # 不是 111 個「|」


def test_reverse_control_wrong_sign_table_would_change_the_output(monkeypatch):
    before = M.encode_s9(-5, 12)
    monkeypatch.setattr(M, "_NEG", "0123456789")
    assert M.encode_s9(-5, 12) != before
