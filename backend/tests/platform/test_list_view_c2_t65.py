# -*- coding: utf-8 -*-
"""T65 C2：案件清單的個人檢視偏好（預設頁籤、每次載入筆數）與公司層頁籤組合（合併重複的「已成案」）。預設全關＝與今天相同。"""
import pathlib
import re

from helpers import settings_groups  # noqa: F401
from helpers import settings_registry as SR

FRONT = pathlib.Path(__file__).resolve().parents[3] / "frontend"
LIST = (FRONT / "js" / "case-management-list.js").read_text(encoding="utf-8")
PAGE = (FRONT / "pages" / "case-management.html").read_text(encoding="utf-8")
OPTS = ("cases_personal_default_tab", "cases_personal_page_size", "cases_merge_won_tab")


def test_options_default_off_and_have_consumers():
    f = SR._g("list_view")["fields"]
    for k in OPTS:
        assert f[k].default == 0 and f[k].type == "int" and f[k].risk == "none" and not f[k].loosen
        for txt in (f[k].question, f[k].label, f[k].help, f[k].impact):
            assert "_" not in txt and k not in txt
        assert "lv." + k in LIST.replace(" ", "") or ("lv.%s === 1" % k) in LIST, k
        assert SR.get("list_view", k) == 0
    assert "案件管理" in f["cases_personal_default_tab"].help and "報價單清單" not in f["cases_personal_default_tab"].help


def test_off_state_adds_nothing_and_list_view_is_read_only_after_layout_on():
    assert "list-view-prefs.js" not in PAGE
    assert PAGE.index("this.layoutOn = true") < PAGE.index("await this.initListView(s.token)")
    assert "read(['list_view'], { token: tk })" in LIST and "builder_layout', 'builder_custom_fields', 'builder_rules', 'builder_slots', 'builder_status_display', 'builder_stage_templates', 'ui_format']" in PAGE
    assert "if (!(this.lvAny || this.lvOn.mergeWon)) return" in LIST


def test_default_keeps_all_four_tabs_and_the_same_queries():
    assert "showWonTab() { return !this.lvOn.mergeWon }" in LIST
    for t in ("all", "已成案", "已結案", "待精算"):
        assert "@click=\"setListTab('%s')\"" % t in PAGE, t
    assert re.search(r"x-show=\"showWonTab\(\)\" :class=\"\{active: listTab==='已成案'\}\"", PAGE)
    assert "casePageSize: 100," in LIST and "qs.set('deal_tag', '已成案')" in LIST       # 查詢與預設筆數不變


def test_personal_choices_stay_inside_the_displayed_tabs_and_fixed_sizes():
    assert "get lvTabs() { return this.lvOn.mergeWon ? ['all', '已結案', '待精算'] : ['all', '已成案', '已結案', '待精算'] }" in LIST
    assert "LV.sanitize(await LV.load(tk, 'case_list.view'), { tabs: this.lvTabs })" in LIST
    assert "this.lvOn.mergeWon && this.listTab === '已成案'" in LIST                      # 合併後停在已成案的人退回進行中
    assert "case_list.view" in LIST and "/api/list-prefs" not in LIST
