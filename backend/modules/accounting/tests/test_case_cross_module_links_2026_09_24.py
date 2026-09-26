"""案件頁的傳票連結（M06 搬遷自 tests/ 同名檔；by-case 端點在本模組）。

2026-09-26 自 `backend/tests/test_case_cross_module_links_2026_09_24.py` 移入（PLAYBOOK §B-11：拿掉本模組時這些題跟著消失）。
"""

from tests.test_case_cross_module_links_2026_09_24 import (  # noqa: F401
    NO, OTHER, _hdr, _seed_case, _voucher,
)


def test_vouchers_by_case_finds_case_and_expense_sources(client, make_user, seed_extra_expense):
    hdr = _hdr(client, make_user, "xl_cash", modules=["cashier"])
    _seed_case()
    _seed_case(OTHER)
    exp = seed_extra_expense(NO, total_cost=5000, category="運費", description="吊車",
                             expense_date="2026-09-10")
    other_exp = seed_extra_expense(OTHER, total_cost=100, category="其他", description="別案",
                                   expense_date="2026-09-10")
    v_case = _voucher(client, hdr, "case", NO)
    v_exp = _voucher(client, hdr, "extra_expense", str(exp))
    v_other = _voucher(client, hdr, "extra_expense", str(other_exp))
    v_none = _voucher(client, hdr)
    r = client.get(f"/api/vouchers/by-case/{NO}", headers=hdr)
    assert r.status_code == 200, r.text
    ids = [v["id"] for v in r.json()["vouchers"]]
    assert set(ids) == {v_case, v_exp}, (ids, v_other, v_none)
    assert all(v.get("voucher_no") for v in r.json()["vouchers"])


def test_vouchers_by_case_needs_voucher_access(client, make_user):
    _seed_case()
    hdr = _hdr(client, make_user, "xl_nocash", role="admin", modules=["case_manage"])
    r = client.get(f"/api/vouchers/by-case/{NO}", headers=hdr)
    assert r.status_code == 403, r.text
