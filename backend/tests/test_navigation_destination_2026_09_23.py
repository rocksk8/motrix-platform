# -*- coding: utf-8 -*-
"""`EM10` · 導航指示要走得到（`docs/windows/SPEC-EM10-NAVIGATION.md`）。

```
EM1   問「這個字懂不懂」  —— 比對字串（訊息裡的詞 vs 畫面上的詞）
EM10  問「照著這句話走，走得到嗎」 —— **照著指示點一次**
```

# 🔴 動工前自己掃過一次母體，而**不是 46**

規格 `§2` 寫「46 條」（A-2「實掃」）。獨立寫一支不同的掃描器（backend
用 `ast` 取字串常數、frontend 用剝掉註解後的逐行掃描）重新量：

```
backend  89 條（ast 走過 backend/**（排除 scripts/、rollback_snapshots/、
              tests/），只取字串常數節點，**排除 docstring 位置的節點**
              —— 這個 repo 的 docstring 大量用「請」開頭的句子寫文件，
              第一版沒排除時連自己剛寫的程式檔都撿到假警報）
frontend 55 條（frontend/**/*.html／*.js（排除 rollback），剝掉
              `<!--…-->`／`/*…*/`／整行 `//` 之後逐行找語氣詞）
合計     **144**
```
⚠️ **不是 46 錯，是兩把尺量的範圍不同**——A-2 的「實掃」大概率是人工
篩過、只算「站得住的獨立訊息」，我這把尺是機械掃描，不分辨同一組
email 樣板裡重複出現幾次、也不刻意排除掉重複率高的樣板文字。兩個數字
不必調和成同一個：**本檔的反向控制用自己這把尺量出來的 144，不是拿
46 硬套**——量測方式必須可重跑（見 `_scan_all_nav_messages()`），
數字才有意義；照抄一個量不出來的數字才是真正的風險。

⇒ 已核對：`§3` 的 5 條、`§4` 的 2 個負對照，**全部都在這 144 條掃得到的
範圍內**（見下面各題），證明這把尺至少涵蓋了規格點名的全部已知案例。

# ⚙️ 本檔做的與刻意不做的

```
✅ ① 反向控制：nav-tone 訊息總數不可以下降（防「守門逼刪訊息」那個坑）
✅ ② §3 的 4 條個別釘死（第 5 條 `STATE` 提到未落檔，待 A 補，不寫）
✅ ③ §4 的 2 個負對照（證明判準不是「全部都紅」）
❌ 不做 §5／§6 完整的「兩層判準」機械化（要求全部 144 條逐一都有可比對
   引號目的地）——那需要對每一條訊息個別判定「引號目的地在不在畫面上」，
   而 144 條裡大多數的「畫面」需要人工核對是哪一頁，機械掃描做不到
   規格 §7③ 要求的「照著指示點一次」；那件事本身就是規格寫明的**人工
   驗收**，不是這裡能自動化的部分。本檔只覆蓋規格點名的、已經人工核對
   過目的地的 4＋2 條。
```
"""
import ast
import pathlib
import re

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]

NAV_PHRASES = ("請至", "請於", "請到", "前往", "請先至", "請先到",
               "可至", "可於", "改由")

QUOTE_RE = re.compile(r"[「『]([^」』]{1,60})[」』]")


def _has_nav_tone(s):
    return any(p in s for p in NAV_PHRASES)


def _docstring_const_ids(tree):
    """`module`／`function`／`class` 的 docstring 常數節點 id 集合。

    docstring 是文件散文不是使用者可見訊息，混進來會撿到幽靈——這個 repo
    的 docstring 大量用「請」開頭的句子寫文件，不排除的話連測試檔自己都
    會被掃到假警報。
    """
    ids = set()
    candidates = [tree] + [n for n in ast.walk(tree)
                           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef,
                                             ast.ClassDef))]
    for node in candidates:
        body = getattr(node, "body", None)
        if body and isinstance(body[0], ast.Expr):
            val = body[0].value
            if isinstance(val, ast.Constant) and isinstance(val.value, str):
                ids.add(id(val))
    return ids


def _string_literals_in_py(path):
    try:
        src = path.read_text(encoding="utf-8", errors="replace")
        tree = ast.parse(src)
    except SyntaxError:
        return []
    doc_ids = _docstring_const_ids(tree)
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) not in doc_ids:
                out.append(node.value)
        elif isinstance(node, ast.JoinedStr):
            parts = [v.value for v in node.values
                    if isinstance(v, ast.Constant) and isinstance(v.value, str)]
            out.append("".join(parts))
    return out


def _backend_py_files():
    for p in (ROOT / "backend").rglob("*.py"):
        parts = p.relative_to(ROOT).parts
        if "scripts" in parts or "rollback_snapshots" in parts or "tests" in parts:
            continue
        if "__pycache__" in parts:
            continue
        yield p


def _frontend_files():
    for pat in ("*.html", "*.js"):
        for p in (ROOT / "frontend").rglob(pat):
            if "rollback" in p.relative_to(ROOT).parts:
                continue
            yield p


def _scan_all_nav_messages():
    """回傳 `[(檔案相對路徑, 訊息文字), …]`——backend 用 `ast` 取字串常數，
    frontend 剝掉常見註解後逐行找語氣詞。見檔頭「動前查母體」。
    """
    hits = []
    for p in _backend_py_files():
        for s in _string_literals_in_py(p):
            if _has_nav_tone(s):
                hits.append((str(p.relative_to(ROOT)), s))
    for p in _frontend_files():
        text = p.read_text(encoding="utf-8", errors="replace")
        text_nc = re.sub(r"<!--.*?-->", "", text, flags=re.S)
        text_nc = re.sub(r"/\*.*?\*/", "", text_nc, flags=re.S)
        for line in text_nc.splitlines():
            stripped = line.strip()
            if stripped.startswith("//"):
                continue
            if _has_nav_tone(line):
                hits.append((str(p.relative_to(ROOT)), stripped))
    return hits


def _page_text(rel):
    return (ROOT / "frontend" / "pages" / rel).read_text(
        encoding="utf-8", errors="replace")


def _system_settings_pages():
    """帶著 `pg__eyebrow">系統設定<` 這個分類標籤的頁面——這是畫面自己
    對「系統設定」這個分類的定義，不是我自己猜一個頁面名稱。
    """
    out = []
    for p in (ROOT / "frontend" / "pages").glob("*.html"):
        text = p.read_text(encoding="utf-8", errors="replace")
        if 'pg__eyebrow">系統設定<' in text:
            out.append(p.name)
    return out


# ══════════════════════════════════════════════════════════════════════
# ① 反向控制：nav-tone 訊息總數不可以下降
# ══════════════════════════════════════════════════════════════════════

#: 本檔自己這把尺量出來的基準——**只能因為新增／移除語氣詞、改變掃描
#: 範圍而調整，並且要在這裡寫下理由**；不可以因為某次改動讓訊息變少
#: 而往下調（那正是規格 §5 要防的「守門逼對方刪訊息」）。
#:
#: 第三類調整理由（hichan-0a 2026-09-24 裁 G1）：**整個功能依使用者裁示被移除時**，
#: 它的訊息跟著消失，可以往下調。⚠️ 界線：同一個功能還在、只是改寫或刪減訊息，
#: **仍然不准往下調**——那正是本題要擋的事。
#:
#: 調整紀錄：
#: - 2026-09-24　144 → 143。少掉的是舊 `frontend/js/bonus.js` 的「請至少勾選一個獎金項目。」，
#:   屬於已移除的舊「獎金項目＋分潤單」流程（SPEC-BONUS §十一；使用者原文：「重做成新流程」、
#:   舊單「舊的都是開發機測試用，直接作廢」）。移除它的 commit：
#:   「feat(bonus §十一): 以案件為中心的獎金分潤頁面；出納可見範圍（C1）」。
#:   以同一個掃描器比對 master（f57740b）與該分支，只少這一句。
_BASELINE_COUNT = 138   # 2026-09-25：只算 modules/ 以外（M11 的 6 條由 modules/tender_radar/tests/ 自己釘）
#: 〔2026-09-26 已由 `_BASELINE_BY_GROUP["_outside"]` 取代、不再被讀（B 審查建議）；原數字與下面的調整紀錄照留，
#:   要調基準請改 `_BASELINE_BY_GROUP`〕
#: 〔2026-09-26 第十班列車：139 → 138。cashier.html／receivables.html／payment-request-form.html（arap，
#:   實體不歸 modules/ 管，不在「排除 modules/」的判準內）改列進 `_MODULE_OWNED_FRONTEND_PAGES`
#:   一起排除——這 3 頁裡剛好有 1 句導航語氣字串，換位置＝這一題的排除範圍換了，不是被刪；
#:   PLAYBOOK §B-11 反向控制真的拿掉 arap 時這 3 個檔案會實體消失，不排除會把「模組真的不在」
#:   誤判成「訊息被刪掉了」〕
#: 〔2026-09-26 M05 搬遷：141 → 139。開票申請與請款單各 1 條「請至少選擇一項品項」隨 routers/ 搬進 modules/arap/api/；
#:   同一個掃描器含 modules/ 的總數搬遷前後都是 157 ⇒ 沒有任何一句被刪，只是換了位置〕
#: 〔2026-09-26 第六班列車：142 → 141。M04／M07／M08 同班搬進 modules/ 共 9 條（subcontract 2、payroll 4、analytics 3），
#:   同一個掃描器含 modules/ 的總數 origin da6ab316 與列車都是 157 ⇒ 沒有任何一句被刪，只是換了位置；
#:   modules/ 外由 150 降到 141。各包單獨時仍 ≥142，三包合起來才跨過基準〕

#: 屬於模組自己的前端頁面（module.json 的 `pages[]`）：頁面實體不歸 `modules/<key>/…` 管
#: ⇒ 上面「排除 modules/」的判準抓不到；PLAYBOOK §B-11 反向控制真的拿掉該模組時這幾頁連同
#: 它們的導航訊息會一起消失，跟 modules/ 底下的 backend 檔一樣不該算進基準
#: （第十班列車 arap 真刪反向控制實測：138 < 139，這 3 頁裡剛好有一句沒被排除）。
#: 只存裸檔名（不帶目錄）：test_page_paths_centralized.py 對「寫死頁面路徑」計數是棘輪，
#: 這裡沒有必要把目錄也寫死。
_MODULE_OWNED_FRONTEND_PAGES = {"cashier.html", "receivables.html", "payment-request-form.html"}   # arap（M05）

#: 〔2026-09-26 M06 搬遷＋稽核 D M06-M2（主持重點）：上面的做法只把模組的條目**移出計數範圍**，沒有題接手——
#:   模組裡的訊息只有 tender_radar 自己有守。改成**每一組各自一個基準**：模組外一組（`_outside`）、每個已安裝模組一組；
#:   每組都不可以低於基準；模組不在就不比；另一組多一條補不回被刪的那一組；有訊息而沒登記基準的新組 ⇒ 紅。
#:   歸屬：`modules/<key>/…` 底下的檔歸 key；frontend 的頁面依**已安裝模組 module.json 的 `pages[]`** 歸該模組
#:   （B 審查：不手列；`_MODULE_OWNED_FRONTEND_PAGES` 保留當正對照——這 3 頁要經 module.json 歸到 arap）。
#:   基準（A 2026-09-26 在 wip/a-m06-4〔afbb1b8d 之上〕以本檔掃描器實量，總數 157 不變）：
#:   模組外 120、accounting 4、analytics 8、arap 3、daily_tasks 3、netplan 1、payroll 6、subcontract 2、supply 2、tender_radar 8。
#:   模組外由 138 變 120 不是刪訊息：各模組 pages[] 的頁面（報表、獎金、傳票…）改算進各自的組〕
_BASELINE_BY_GROUP = {"_outside": 120, "accounting": 4, "analytics": 8, "arap": 3, "daily_tasks": 3,
                      "netplan": 1, "payroll": 6, "subcontract": 2, "supply": 2, "tender_radar": 8}


def _page_owners():
    """frontend 頁面檔名 ⇒ 模組 key（已安裝模組的 module.json `pages[]`；模組不在 ⇒ 它的頁面不在這張表）。"""
    import json
    from core import source_tree
    out = {}
    for d in source_tree.module_dirs():
        m = json.loads((d / "module.json").read_text(encoding="utf-8"))
        for pg in m.get("pages", []):
            # 組名一律用資料夾名：installed() 與 modules/<x> 路徑都是資料夾名；key 若不同，那一組會被默默跳過（B 審查建議）
            assert (m.get("key") or d.name) == d.name, "module.json 的 key %r 與資料夾名 %r 不一致" % (m.get("key"), d.name)
            out[str(pg.get("path", "")).replace("\\", "/").rsplit("/", 1)[-1]] = d.name
    return out


def _group_of(path, owners):
    parts = str(path).replace("\\", "/").split("/")
    if "modules" in parts:
        return parts[parts.index("modules") + 1]
    return owners.get(parts[-1], "_outside")


def em10_problems(hits_by_group, baseline, installed):
    """hits_by_group：{組: [(檔, 字串)]}；installed(組) ⇒ 模組在不在（`_outside` 永遠在）。回問題清單（附該組前幾條命中）。"""
    out = []
    for g, want in sorted(baseline.items()):
        if g != "_outside" and not installed(g):
            continue                                   # 模組不在（選配／反向控制）⇒ 它的條目本來就不在
        got = hits_by_group.get(g, [])
        if len(got) < want:
            out.append("%s：含導航語氣的可見字串 %d 條，低於基準 %d；目前命中的前幾條：\n%s" % (
                g, len(got), want, "\n".join("    %s :: %r" % (pp, ss[:60]) for pp, ss in got[:8])))
    for g in sorted(set(hits_by_group) - set(baseline)):
        out.append("%s：有 %d 條含導航語氣的字串而沒有基準 ⇒ 在 _BASELINE_BY_GROUP 登記（否則刪了沒有題會紅）"
                   % (g, len(hits_by_group[g])))
    return out


def test_em10_the_navigation_tone_message_count_does_not_drop():
    """🔴🔴 **反向控制：含導航語氣的可見字串，每一組都不可以低於基準。**

    ☠️ 若沒有這一題，「兩層判準」的守門（要求訊息附上可比對的目的地）
    最省力的反應是**把整句導航直接刪掉**——刪掉之後判準全綠，而使用者
    連一個錯的指路牌都沒有了，比原本更糟。這一題釘住「訊息只能變得
    更可比對，不能就地消失」。
    ⚙️ 2026-09-26（稽核 D M06-M2）：原本只算模組外（模組的條目被排除之後沒有人守）⇒ 每組一個基準（見上方註記）。
    """
    from core import source_tree
    owners = _page_owners()
    by_group = {}
    for pp, ss in _scan_all_nav_messages():
        by_group.setdefault(_group_of(pp, owners), []).append((pp, ss))
    bad = em10_problems(by_group, _BASELINE_BY_GROUP, lambda g: source_tree.module_installed("modules/%s/" % g))
    assert not bad, "\n".join(bad) + "\n☠️ 若是因為某次改動把導航語句直接刪掉才變少的，那正是這一題要擋住的事。"


def test_em10_page_ownership_comes_from_module_json():
    """正對照：頁面歸屬讀 module.json（不手列）——原本手列的 arap 3 頁要經 module.json 歸到 arap；模組底下的檔歸模組。"""
    from core import source_tree
    owners = _page_owners()
    if source_tree.module_installed("modules/arap/"):
        assert {pg: owners.get(pg) for pg in _MODULE_OWNED_FRONTEND_PAGES} == \
            {pg: "arap" for pg in _MODULE_OWNED_FRONTEND_PAGES}, owners
    assert _group_of("backend/modules/accounting/api/vouchers.py", {}) == "accounting"
    assert _group_of("pages/voucher.html", {"voucher.html": "accounting"}) == "accounting"
    assert _group_of("backend\\routers\\quotations.py", {}) == "_outside"


def test_em10_reverse_control_each_group_is_held_on_its_own():
    """反向控制（合成）：任一組少一條 ⇒ 紅（訊息附該組命中）；別的組多一條補不回來；新的組沒登記 ⇒ 紅；模組不在 ⇒ 不比。"""
    base = dict(_BASELINE_BY_GROUP)
    everywhere = lambda g: True                        # noqa: E731

    def hits(counts):
        return {g: [("f_%s" % g, "x%d" % i) for i in range(n)] for g, n in counts.items()}
    assert em10_problems(hits(base), base, everywhere) == []
    for g in base:
        bad = em10_problems(hits(dict(base, **{g: base[g] - 1})), base, everywhere)
        assert len(bad) == 1 and bad[0].startswith("%s：" % g), (g, bad)
        assert base[g] == 1 or "f_%s" % g in bad[0], ("失敗訊息要附該組剩下的命中", g, bad)
    swapped = dict(base, accounting=base["accounting"] - 1, payroll=base["payroll"] + 1)
    assert len(em10_problems(hits(swapped), base, everywhere)) == 1, "多的那一組不可以補回被刪的那一組"
    assert em10_problems(hits(dict(base, newmod=1)), base, everywhere)[0].startswith("newmod：")
    gone = {g: n for g, n in base.items() if g != "accounting"}
    assert em10_problems(hits(gone), base, lambda g: g != "accounting") == []


# ══════════════════════════════════════════════════════════════════════
# ② `§3` 的四條——個別釘死，目的地字串要對得上畫面
# ══════════════════════════════════════════════════════════════════════

def test_em10_edge_path_message_points_to_a_findable_label():
    """🔴🔴 **`①` `startup.py:42`：訊息說「Edge 執行檔路徑」，畫面上沒有這個字。**

    實際畫面（`company-profile-settings.html`）那張卡片的標題是
    「**Edge 瀏覽器路徑**」——使用者在正確的頁面上，看著正確的欄位，
    而不認得它。
    """
    src = (ROOT / "backend" / "helpers" / "startup.py").read_text(
        encoding="utf-8", errors="replace")
    msg = next((s for s in _string_literals_in_py(
                   ROOT / "backend" / "helpers" / "startup.py")
               if "Edge 執行檔" in s), None)
    assert msg is not None, "找不到 Edge 執行檔的訊息——退回改本檔的錨點。"
    m = QUOTE_RE.search(msg)
    assert m, "訊息裡找不到引號目的地：%r" % msg
    target = m.group(1).split("→")[-1].strip()
    page = _page_text("company-profile-settings.html")
    assert target in page, (
        "訊息說要去「%s」，而 `company-profile-settings.html` 裡找不到\n"
        "這個字——實際的卡片標題是「Edge 瀏覽器路徑」。" % target)


def test_em10_t100_account_code_message_points_to_the_wrong_place():
    """🔴🔴 **`④` `accounting_export.py:422`：訊息叫使用者去系統設定，
    T100 科目代號其實在出納頁的 T100 子頁籤。**

    `FN3` 把這個功能從報表頁搬到出納頁，訊息沒有跟著搬——同一個成因，
    `③` 是搬家前的舊指標，這一題是搬家前的另一個舊指標。核心斷言與
    `③` 同一種形狀：訊息不可以再提「系統設定」，下面兩段是佐證。

    出納頁（cashier.html）屬於 M05 應收應付（arap），該模組不在這個安裝包時本題最後一段驗證的
    對象不存在（PLAYBOOK §B-11 反向控制；第十班列車 arap 真刪實測發現：本題原本沒有這一道略過）。
    """
    from core import source_tree
    if not source_tree.module_installed("modules/arap/"):
        pytest.skip("應收應付模組未安裝：cashier.html 不存在，本題最後一段驗證的正是這一頁")
    # ⚠️ 這句訊息在原始碼裡是三段字串常數用 `+` 接起來的
    # （`"…科目代號：" + "、".join(...) + "（請至系統設定…）"`），
    # `ast` 把它們拆成三個獨立的 `Constant` 節點——「科目代號」與
    # 「請至系統設定」不在同一個節點裡，錨點只能定在含語氣詞的那一段。
    from core import source_tree
    if not source_tree.module_installed("modules/accounting/"):
        pytest.skip("會計（M06）不在這個安裝包（PLAYBOOK §B-11）")
    msg = next((s for s in _string_literals_in_py(
                   ROOT / "backend" / "modules" / "accounting" / "api" / "accounting_export.py")
               if "匯入 T100" in s and _has_nav_tone(s)), None)
    assert msg is not None, "找不到 T100 那句導航訊息——退回改本檔的錨點。"
    assert "系統設定" not in msg, (
        "`accounting_export.py` 的科目代號訊息仍然說「系統設定」：%r\n"
        % msg
        + "☠️ 實際的設定入口在出納頁的 T100 子頁籤，不在系統設定裡。")

    settings_pages = _system_settings_pages()
    assert settings_pages, "一頁『系統設定』分類的頁面都找不到——退回改本檔的判定法。"
    for name in settings_pages:
        text = _page_text(name)
        assert "科目代號" not in text, (
            "『系統設定』分類裡的 %s 找到了「科目代號」——\n" % name
            + "這一題的前提已經不成立，請確認並更新本題。")
    cashier_text = _page_text("cashier.html")
    assert "科目代號" in cashier_text and "toggleT100Config" in cashier_text, (
        "`cashier.html` 裡反而找不到 T100 科目代號的設定入口——前置不對。")


# ══════════════════════════════════════════════════════════════════════
# ③ `§4` 的負對照——判準不是「全部都紅」
# ══════════════════════════════════════════════════════════════════════

def test_em10_the_daily_tasks_password_message_is_a_correct_positive_control():
    """⚙️ **正對照：`daily-tasks.html` 那句「請至使用者管理…」逐段都對得上。**

    ☠️ 少了正對照，判準若壞成「只要含語氣詞就紅」，`②` 那四題會全部
    通過而**理由是錯的**（不是因為判準真的比對過目的地）。
    """
    hits = _scan_all_nav_messages()
    msg = next((s for p, s in hits
               if "每日工作事項密碼" in s and "使用者管理" in s
               and p.endswith("daily-tasks.html")), None)
    assert msg is not None, "找不到那句訊息——退回改本檔的錨點。"

    users_page = _page_text("users.html")
    # 逐段驗：目的地頁面標題／欄位標籤都要在 users.html 裡找得到。
    assert 'pg__t">使用者管理' in users_page, (
        "`users.html` 找不到「使用者管理」這個頁面標題。")
    assert "每日工作事項密碼" in users_page, (
        "`users.html` 找不到「每日工作事項密碼」這個欄位標籤——\n"
        "訊息叫使用者去那裡設定，而那裡沒有這個欄位。")


def test_em10_the_notification_email_message_is_a_correct_positive_control():
    """⚙️ **第二個正對照：`notification-settings.html` 那句話也逐段對得上。**

    ⚙️ 與上一題**同一種形狀、不同頁**——兩個負對照都是「引號目的地 →
    前端標籤」，確認判準不是只在一個特例上剛好對。
    """
    hits = _scan_all_nav_messages()
    msg = next((s for p, s in hits
               if "使用者管理" in s and "Email" in s), None)
    assert msg is not None, "找不到那句訊息——退回改本檔的錨點。"

    users_page = _page_text("users.html")
    assert 'pg__t">使用者管理' in users_page
    assert 'type="email"' in users_page and "x-model=\"form.email\"" in users_page, (
        "`users.html` 找不到 Email 欄位——訊息叫使用者去那裡填，\n"
        "而那裡沒有這個欄位。")
