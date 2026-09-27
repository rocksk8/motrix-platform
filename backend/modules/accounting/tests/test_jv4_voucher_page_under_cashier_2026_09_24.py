"""`JV4` · 傳票頁 `pages/voucher.html`：出納底下的獨立頁（`STATE.md` 總表 `JV4`）。

驗三件事（結構層；執行期那一半由 `test_e2e_voucher_feedback_2026_09_23.py` 真的開頁存檔）：
① 側欄入口緊接在「出納」之後，**用同一個旗標** `cCash`（使用者原話「要由出納獨立作業」）
② 後端的模組閘（`routers/vouchers.py::_VOUCHER_MODULES`）收 `cashier` —— 看得到入口的人打得到 API
③ 頁面是獨立的：自己的 Alpine 元件、有「儲存」與「送出審核」

⚠️ 規格的「填寫體驗比照報價單」**沒有逐項對照表**，這一題不宣稱驗到那一句；
   只驗「它是出納底下一個可以填、可以存、可以送審的獨立頁」。
"""
import pathlib
import re
from core import source_tree

ROOT = pathlib.Path(__file__).resolve().parents[4]


def test_jv4_the_voucher_entry_sits_right_after_cashier_with_the_same_flag():
    """C4：讀選單宣告（tests/_menu_decl.py），不再解析 sidebar.js 的 ni() 行；原本的旗標 `cCash`＝perm ["cashier"]。"""
    from tests._menu_decl import declared_items
    items = declared_items()
    cash = [i for i, it in enumerate(items) if it["href"] == "cashier.html"]
    vouch = [i for i, it in enumerate(items) if it["href"] == "voucher.html"]
    # 〔C 發現（M05 真刪時紅）：出納入口屬 M05（arap）——M05 不在時改驗「傳票入口照樣在、權限仍是 cashier、沒有出納入口」，
    #   不整題略過（§G5 #7：驗「另一邊照常」的不可以標 requires_module）〕
    if not source_tree.module_installed("modules/arap/"):
        assert cash == [] and len(vouch) == 1, "M05 不在：出納入口應該不見、傳票入口恰好一個：cashier %r、voucher %r" % (cash, vouch)
        assert items[vouch[0]]["perm"] == ["cashier"], "M05 不在時傳票入口的權限變了：%r" % items[vouch[0]]["perm"]
        return
    assert len(cash) == 1 and len(vouch) == 1, (
        "選單的出納／傳票入口各應恰好一個：cashier %r、voucher %r" % (cash, vouch))
    assert vouch[0] == cash[0] + 1 and items[vouch[0]]["group"] == items[cash[0]]["group"], (
        "傳票入口不在出納的下一個：出納 #%d、傳票 #%d" % (cash[0], vouch[0]))
    assert items[vouch[0]]["perm"] == items[cash[0]]["perm"] == ["cashier"], (
        "傳票與出納的權限不同：%r vs %r" % (items[vouch[0]]["perm"], items[cash[0]]["perm"]))


def test_jv4_the_backend_module_gate_accepts_the_cashier_module():
    src = (ROOT / "backend" / "modules" / "accounting" / "api" / "vouchers.py").read_text(encoding="utf-8")   # M06 搬遷
    m = re.search(r"_VOUCHER_MODULES\s*=\s*\(([^)]*)\)", src)
    assert m, "找不到 `_VOUCHER_MODULES` —— 退回改本檔的錨點。"
    assert "'cashier'" in m.group(1) or '"cashier"' in m.group(1), (
        "`_VOUCHER_MODULES` = (%s) 不含 cashier —— 看得到側欄入口的人會被 API 擋下。" % m.group(1))


def test_jv4_the_page_is_a_standalone_form_that_can_save_and_submit():
    page = source_tree.page_file("voucher.html").read_text(encoding="utf-8")
    assert 'x-data="voucherPage()"' in page, "voucher.html 不是自己的 Alpine 元件"
    assert '@click="save()"' in page, "voucher.html 沒有儲存"
    assert '@click="submit()"' in page, "voucher.html 沒有送出審核"
    assert "voucher.js" in page, "voucher.html 沒有載入 voucher.js"
