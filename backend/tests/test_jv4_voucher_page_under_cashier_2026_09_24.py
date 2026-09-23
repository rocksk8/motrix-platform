"""`JV4` · 傳票頁 `frontend/pages/voucher.html`：出納底下的獨立頁（`STATE.md` 總表 `JV4`）。

驗三件事（結構層；執行期那一半由 `test_e2e_voucher_feedback_2026_09_23.py` 真的開頁存檔）：
① 側欄入口緊接在「出納」之後，**用同一個旗標** `cCash`（使用者原話「要由出納獨立作業」）
② 後端的模組閘（`routers/vouchers.py::_VOUCHER_MODULES`）收 `cashier` —— 看得到入口的人打得到 API
③ 頁面是獨立的：自己的 Alpine 元件、有「儲存」與「送出審核」

⚠️ 規格的「填寫體驗比照報價單」**沒有逐項對照表**，這一題不宣稱驗到那一句；
   只驗「它是出納底下一個可以填、可以存、可以送審的獨立頁」。
"""
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _nav_lines():
    src = (ROOT / "frontend" / "static" / "sidebar.js").read_text(encoding="utf-8")
    return [l.strip() for l in src.splitlines() if l.strip().startswith("ni(pg(")]


def test_jv4_the_voucher_entry_sits_right_after_cashier_with_the_same_flag():
    lines = _nav_lines()
    idx = {i: l for i, l in enumerate(lines)}
    cash = [i for i, l in idx.items() if "pg('cashier.html')" in l]
    vouch = [i for i, l in idx.items() if "pg('voucher.html')" in l]
    assert len(cash) == 1 and len(vouch) == 1, (
        "側欄的出納／傳票入口各應恰好一個：cashier %r、voucher %r" % (cash, vouch))
    assert vouch[0] == cash[0] + 1, (
        "傳票入口不在出納的下一個：出納 #%d、傳票 #%d\n%s" % (cash[0], vouch[0], idx[vouch[0]]))
    flag = lambda l: l.rstrip("),").split(",")[-1].strip()
    assert flag(idx[vouch[0]]) == flag(idx[cash[0]]) == "cCash", (
        "傳票與出納的顯示旗標不同：%r vs %r" % (flag(idx[vouch[0]]), flag(idx[cash[0]])))


def test_jv4_the_backend_module_gate_accepts_the_cashier_module():
    src = (ROOT / "backend" / "routers" / "vouchers.py").read_text(encoding="utf-8")
    m = re.search(r"_VOUCHER_MODULES\s*=\s*\(([^)]*)\)", src)
    assert m, "找不到 `_VOUCHER_MODULES` —— 退回改本檔的錨點。"
    assert "'cashier'" in m.group(1) or '"cashier"' in m.group(1), (
        "`_VOUCHER_MODULES` = (%s) 不含 cashier —— 看得到側欄入口的人會被 API 擋下。" % m.group(1))


def test_jv4_the_page_is_a_standalone_form_that_can_save_and_submit():
    page = (ROOT / "frontend" / "pages" / "voucher.html").read_text(encoding="utf-8")
    assert 'x-data="voucherPage()"' in page, "voucher.html 不是自己的 Alpine 元件"
    assert '@click="save()"' in page, "voucher.html 沒有儲存"
    assert '@click="submit()"' in page, "voucher.html 沒有送出審核"
    assert "voucher.js" in page, "voucher.html 沒有載入 voucher.js"
