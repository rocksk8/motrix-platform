"""`JV26` · `voucher_lines` 的三個寫入點，欄位清單必須一致（`docs/windows/SPEC-JV26.md` §3）。

今天三支（`create_voucher`／作廢重開／`update_voucher`）都寫同一組 6 欄，另有 7 欄已規劃未接線。
☠️ 接線那天只改其中一支 ⇒ 建立的單沒有值、重開的有值，而兩者都是「正常的傳票」。
⇒ 這道守門釘的是**一致**，不是**欄數**：三支一起多一欄（一起接線）是對的。

⚙️ 量法照規格：`ast` 取字串常數（跨行串接的 SQL 在 ast 裡是一個 Constant），
   解析 `INSERT INTO voucher_lines (...)` 的欄名，比對集合。**不用逐行 regex**（只看得到半句）。
⚙️ 誘餌 A–D 用**合成原始碼**，不改產品碼。
"""
import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]
_INS = re.compile(r"INSERT\s+INTO\s+voucher_lines\s*\(([^)]*)\)", re.I)


def _column_sets(src):
    """原始碼裡每一句 `INSERT INTO voucher_lines (...)` 的欄名集合（照出現順序）。"""
    out = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            m = _INS.search(node.value)
            if m:
                out.append(frozenset(c.strip() for c in m.group(1).split(",") if c.strip()))
    return out


def _disagree(sets):
    return len(set(sets)) > 1


def test_jv26_the_three_voucher_lines_inserts_write_the_same_columns():
    sets = _column_sets((ROOT / "backend" / "routers" / "vouchers.py").read_text(encoding="utf-8"))
    assert len(sets) == 3, (
        "`vouchers.py` 裡 `INSERT INTO voucher_lines` 有 %d 句，規格記的是 3 句" % len(sets)
        + "（create／作廢重開／update）。多了或少了都要先看是哪一支，再更新本題。")
    assert not _disagree(sets), (
        "三個寫入點的欄位不一致：%r\n" % [sorted(s) for s in sets]
        + "☠️ 只接線其中一支 ⇒ 同一種傳票有的有值、有的沒有，而兩者看起來都正常。")


def _src(*cols_per_insert, comment=""):
    body = [comment]
    for i, cols in enumerate(cols_per_insert):
        body.append('q%d = ("INSERT INTO voucher_lines (%s,"\n      " %s) VALUES (?)")'
                    % (i, cols[0], ", ".join(cols[1:])))
    return "\n".join(body)


SIX = ("voucher_id", "line_no", "account_code", "summary", "debit", "credit")


def test_jv26_decoy_a_one_insert_missing_a_column_is_caught():
    assert _disagree(_column_sets(_src(SIX, SIX, SIX[:-1])))


def test_jv26_decoy_b_three_identical_inserts_pass():
    sets = _column_sets(_src(SIX, SIX, SIX))
    assert len(sets) == 3 and not _disagree(sets)


def test_jv26_decoy_c_all_three_wired_together_pass():
    """🔑 這道守門的目的：三支一起多一欄 ⇒ **不可以亮**（守一致，不守欄數）。"""
    more = SIX + ("dept_code",)
    sets = _column_sets(_src(more, more, more))
    assert len(sets) == 3 and not _disagree(sets)


def test_jv26_decoy_d_a_fake_insert_in_a_comment_is_ignored():
    src = _src(SIX, SIX, SIX,
               comment="# INSERT INTO voucher_lines (voucher_id) VALUES (?)  <- 註解，ast 看不到")
    sets = _column_sets(src)
    assert len(sets) == 3 and not _disagree(sets)
