"""B55 出貨等級判定（tools/platform/ship_tier.py；設計 docs/platform/MODULE-UPDATE-DELIVERY.md §4）。

- classify：反向控制每一條都要能讓判定變嚴（改 L1 一行 ⇒ 3 …），正對照（只改一個模組 ⇒ 2、只改文件 ⇒ 1）
- 提供者判斷點（§4.3，DB-M2 甲＋DB2-M1）：能力清單＝ModuleSpec.providers ∪ 模組層 provide；取用函式由
  core/registry.py 公開介面產生；別名、常數、跨檔常數；判不了 ⇒ 退回乙；真實 repo 正對照
"""
import importlib.util
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location("_ship_tier", REPO / "tools" / "platform" / "ship_tier.py")
ST = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ST)

PG = ST.PAGES_REL + "/"      # 宣告頁面的目錄（由 core.paths 取得；test_page_paths_centralized）
PAGES = {"tender_radar": {PG + "tender-radar.html"},
         "case": {PG + "quotations.html", PG + "shared.html"},
         "crm": {PG + "shared.html"}}
IGNORED = {"backend/conftest.py", "backend/tests/test_x.py", "backend/modules/tender_radar/tests/test_a.py",
           "backend/modules/tender_radar/SPEC.md"}


def _c(files, manifest=frozenset()):
    return ST.classify(files, pages_by_module=PAGES, not_shipped=IGNORED.__contains__,
                       manifest_modules=set(manifest) if manifest is not None else None)


# ── classify：正對照 ─────────────────────────────────────────────────────────

def test_only_one_module_and_its_page_and_docs_is_tier2():
    r = _c(["backend/modules/tender_radar/source.py", PG + "tender-radar.html",
            "backend/modules/tender_radar/CHANGELOG.md", "docs/platform/RUN-PLAN.md"])
    assert (r["tier"], r["key"]) == (2, "tender_radar"), r


def test_only_docs_is_tier1():
    assert _c(["docs/platform/RUN-PLAN.md", "backend/tests/test_x.py"])["tier"] == 1


def test_module_readme_counts_as_module_not_doc():
    """路徑規則先於副檔名：模組資料夾裡的 .md 會隨包出貨 ⇒ 屬模組。"""
    r = _c(["backend/modules/tender_radar/README.md"])
    assert (r["tier"], r["key"]) == (2, "tender_radar")


def test_module_tests_only_is_tier2_not_tier1():
    """模組自己的題雖然不出貨，但在模組路徑下 ⇒ 判 2（題要跑）。"""
    assert _c(["backend/modules/tender_radar/tests/test_a.py"])["tier"] == 2


def test_manifest_entry_of_the_same_module_is_allowed():
    r = _c(["backend/modules/tender_radar/source.py", ST.MANIFEST], manifest={"tender_radar"})
    assert (r["tier"], r["key"]) == (2, "tender_radar")


# ── classify：反向控制（每一條都必須判 3）────────────────────────────────────────

@pytest.mark.parametrize("extra, why", [
    ("backend/helpers/geo.py", "L1 一行"),
    ("backend/main.py", "main.py"),
    ("backend/core/registry.py", "L0"),
    ("backend/conftest.py", "fixture 層（雖然不出貨）"),
    ("backend/requirements.txt", "requirements"),
    ("backend/tools/apply_update.ps1", "更新工具"),
    ("tools/platform/modtest.py", "開發工具"),
    ("backend/modules/case/api.py", "另一個模組"),
    ("frontend/static/js/app.js", "共用前端"),
    (PG + "undeclared.html", "沒有模組宣告的頁面"),
    (PG + "shared.html", "兩個模組都宣告的頁面"),
    ("README.md", "根目錄會出貨的 .md（不在 export-ignore）"),
])
def test_reverse_controls_are_tier3(extra, why):
    r = _c(["backend/modules/tender_radar/source.py", extra])
    assert r["tier"] == 3, "%s 沒有判成 3：%s" % (why, r)
    assert r["offenders"], "判 3 必須列出越界的檔"


def test_page_declared_by_two_modules_is_tier3_even_with_one_module():
    """頁面必須**恰好一個**模組宣告：case 自己改＋case 與 crm 都宣告的頁面 ⇒ 3（不可以歸給其中一個）。
    上面的參數題混了 tender_radar ⇒ 會以「兩個模組」判 3，驗不到這一條。"""
    r = _c(["backend/modules/case/api.py", PG + "shared.html"])
    assert r["tier"] == 3, r
    assert any(f == PG + "shared.html" for f, _ in r["offenders"]), r


@pytest.mark.parametrize("manifest", [{"tender_radar", "case"}, {"<shipped>"}, {"<unknown:系統設定/儲存位置>"}, None])
def test_manifest_with_other_or_unknown_entries_is_tier3(manifest):
    r = _c(["backend/modules/tender_radar/source.py", ST.MANIFEST], manifest=manifest)
    assert r["tier"] == 3, (manifest, r)


def _docs_path_refs(src):
    """原始碼裡把 docs 當路徑用的地方：字串以 docs/ 開頭或含 /docs/；或 "docs" 出現在 join／Path／joinpath 呼叫、`/` 運算裡。"""
    import ast
    hits = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            v = node.value.replace("\\", "/")
            if v.startswith("docs/") or "/docs/" in v:
                hits.append(node.lineno)
        elif isinstance(node, ast.Call):
            fn = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if fn in ("join", "Path", "joinpath", "root", "backend", "PurePath") and any(
                    isinstance(a, ast.Constant) and a.value == "docs" for a in node.args):
                hits.append(node.lineno)
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div) and any(
                isinstance(x, ast.Constant) and x.value == "docs" for x in (node.left, node.right)):
            hits.append(node.lineno)
    return hits


def test_docs_path_scanner_positive_control():
    """〈盤點工具的正對照〉：三種寫法都要抓得到；dict 鍵 "docs" 不算。"""
    assert _docs_path_refs('import os\nx = os.path.join(ROOT, "docs", "a.md")\n')
    assert _docs_path_refs('x = ROOT / "docs" / "a.md"\n')
    assert _docs_path_refs('x = open("docs/platform/a.md")\n')
    assert not _docs_path_refs('facts = {"docs": []}\nfacts["docs"].append(1)\n')


def test_docs_are_never_read_at_runtime():
    """§4「doc」把 docs/** 當成不影響執行（完整包雖然帶著）：前提是執行期沒有程式讀 docs/。
    ☠️ 日後有人讓程式讀 docs/ 底下的檔（說明頁、範本）⇒ 這一題紅 ⇒ 回來把 ship_tier 的 docs/ 規則收窄。"""
    hits = []
    for p in (REPO / "backend").rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if "/tests/" in rel or rel.startswith("backend/tools/") or rel == "backend/conftest.py" or "__pycache__" in rel:
            continue
        hits += ["%s:%s" % (rel, n) for n in _docs_path_refs(p.read_text(encoding="utf-8"))]
    assert not hits, "執行期程式碼把 docs/ 當路徑用：\n" + "\n".join(hits)


# ── 提供者判斷點：合成原始碼 ────────────────────────────────────────────────────

REG = '''"""registry
[公開介面] provide, providers, single_provider, loaded
[不變式] x
"""
def provide(capability, name, fn): pass
def providers(capability): pass
def single_provider(capability): pass
def loaded(): pass
'''


def _repo(files):
    src = {ST.REGISTRY: REG}
    src.update(files)
    return ST.Repo(src)


PROVIDER_INIT = '''from core.registry import ModuleSpec
from . import api
MODULE = ModuleSpec(key="p", providers={("p.cap", "p"): api.f})
'''


def test_getter_names_come_from_registry_public_interface():
    assert ST.getter_names(REG) == {"providers", "single_provider"}
    real = ST.getter_names((REPO / "backend" / "core" / "registry.py").read_text(encoding="utf-8"))
    assert {"providers", "single_provider"} <= real and "provide" not in real, real


@pytest.mark.parametrize("consumer_src", [
    'from core import registry\nx = registry.single_provider("p.cap")\n',
    'from core import registry as _registry\nx = _registry.providers("p.cap")\n',
    'import core.registry as r\nx = r.single_provider("p.cap")\n',
    'from core.registry import single_provider as sp\nx = sp("p.cap")\n',
    'from core import registry\nCAP = "p.cap"\ndef f():\n    return registry.providers(CAP)\n',
    'from core import registry\nfrom helpers.consts import PCAP\nx = registry.single_provider(PCAP)\n',
    'from core import registry\nfrom helpers import consts\nx = registry.single_provider(consts.PCAP)\n',
    'from core import registry\nx = registry.single_provider(capability="p.cap")\n',
])
def test_consumer_forms_are_found(consumer_src):
    files = {"backend/modules/p/__init__.py": PROVIDER_INIT, "backend/modules/p/api.py": "def f(): pass\n",
             "backend/modules/c/api.py": consumer_src}
    if "consts" in consumer_src:
        # 只在消費端真的用到時才放：沒人用的能力常數本身就是「散落的能力字串」（DB4-S1 ③ 判不了，見下一題）
        files["backend/helpers/consts.py"] = 'PCAP = "p.cap"\n'
    pc = ST.provider_check(_repo(files), "p", ["backend/modules/p/api.py"], policy="consumers")
    assert pc["provider_changed"] and pc["caps"] == ["p.cap"], pc
    assert pc["consumers"] == ["backend/modules/c/api.py"] and not pc["reject"], pc


def test_unused_capability_constant_is_unresolved():
    """定義了能力常數卻沒有任何已解析的取用用到它 ⇒ 可能經別的路徑（getattr、字串拼接）被取用 ⇒ 判不了。"""
    files = {"backend/modules/p/__init__.py": PROVIDER_INIT, "backend/modules/p/api.py": "def f(): pass\n",
             "backend/helpers/consts.py": 'PCAP = "p.cap"\n'}
    pc = ST.provider_check(_repo(files), "p", ["backend/modules/p/api.py"], policy="consumers")
    assert pc["reject"] and any(u.startswith("backend/helpers/consts.py:") for u in pc["unresolved"]), pc


@pytest.mark.parametrize("consumer_src, why", [
    ('from core import registry\ndef f(cap):\n    return registry.providers(cap)\n', "函式參數"),
    ('from core import registry\nx = registry.single_provider(f"p.{1}")\n', "f-string"),
    ('from core import registry\nCAP = "a"\nCAP = "p.cap"\nx = registry.providers(CAP)\n', "常數被重新指派"),
    ('from core import registry\nget = registry.single_provider\n', "取用函式當值傳遞"),
    ('from core import registry\nfrom helpers.nowhere import X\nx = registry.providers(X)\n', "跨檔常數找不到"),
])
def test_unresolvable_consumer_falls_back_to_reject(consumer_src, why):
    """🔴 判不了 ≠ 沒有消費端：任何一處取用判不了 ⇒ 退回乙（即使它取的可能不是 p 的能力）。"""
    repo = _repo({"backend/modules/p/__init__.py": PROVIDER_INIT,
                    "backend/modules/p/api.py": "def f(): pass\n",
                    "backend/modules/c/api.py": consumer_src})
    pc = ST.provider_check(repo, "p", ["backend/modules/p/api.py"], policy="consumers")
    assert pc["reject"] and pc["unresolved"], (why, pc)


def test_module_level_provide_counts_and_function_level_provide_rejects():
    """能力清單＝ModuleSpec.providers ∪ 模組層 provide；函式內的 provide ⇒ 判不了（DB3-S2）。"""
    top = _repo({"backend/modules/p/api.py":
                   'from core import registry as _registry\ndef g(): pass\n_registry.provide("p.late", "p", g)\n'})
    caps, un = ST.capabilities(top, "p")
    assert caps == {"p.late"} and not un
    inner = _repo({"backend/modules/p/api.py":
                     'from core import registry\ndef setup():\n    registry.provide("p.late", "p", setup)\n'})
    caps, un = ST.capabilities(inner, "p")
    assert un, "函式內的 provide 必須判不了（不可以略過）"
    pc = ST.provider_check(inner, "p", ["backend/modules/p/api.py"], policy="consumers")
    assert pc["reject"]


def test_no_provider_change_when_only_pages_or_docs_change():
    repo = _repo({"backend/modules/p/__init__.py": PROVIDER_INIT})
    pc = ST.provider_check(repo, "p", ["backend/modules/p/CHANGELOG.md", PG + "p.html"])
    assert not pc["provider_changed"] and not pc["reject"]


def test_policy_reject_turns_provider_change_into_tier3():
    repo = _repo({"backend/modules/p/__init__.py": PROVIDER_INIT})
    pc = ST.provider_check(repo, "p", ["backend/modules/p/api.py"], policy="reject")
    assert pc["reject"] and "reject" in pc["reason"]


def test_default_policy_is_user_ruling():
    assert ST.PROVIDER_CHANGE_POLICY == "consumers", "使用者裁示甲（CORE-SPEC ee383527）"


# ── DB4-S1（主持裁示必做）：繞過取用函式的讀法 ⇒ 判不了 ──────────────────────────────

_P_FILES = {"backend/modules/p/__init__.py": PROVIDER_INIT, "backend/modules/p/api.py": "def f(): pass\n"}


@pytest.mark.parametrize("src, why", [
    ('from core import registry\nx = registry._LEGACY_PROVIDERS[("p.cap", "p")]\n', "讀 registry 內部取用（主持指定的反向控制）"),
    ('from core import registry as R\nfor k in R._LEGACY_PROVIDERS: pass\n', "別名讀內部"),
    ('from core.registry import _LEGACY_PROVIDERS\n', "import 內部名稱"),
    ('from core.registry import *\nx = single_provider(CAP)\n', "星號 import"),
    ('from core import registry\nfor m in registry.loaded():\n    fn = m.spec.providers[("p.cap", "p")]\n', "經 loaded() 取 spec.providers（能力字串出現在非取用位置）"),
    ('from core import registry\nfrom helpers.consts import PCAP\nfor m in registry.loaded():\n    fn = m.spec.providers[(PCAP, "p")]\n',
     "能力常數（跨檔）用在非取用位置"),
    ('from core import registry\nfrom helpers.consts import PCAP\nok = registry.providers(PCAP)\nfor m in registry.loaded():\n    fn = m.spec.providers[(PCAP, "p")]\n',
     "同一檔有合法取用、另一處繞過（消費端檔不整檔豁免）"),
    ('from core import registry\nfrom helpers import consts\nok = registry.providers(consts.PCAP)\nfor m in registry.loaded():\n    fn = m.spec.providers[(consts.PCAP, "p")]\n',
     "能力常數以屬性形式（consts.PCAP）用在非取用位置"),
    ('from core import registry\nfor (cap, name), fn in registry._LEGACY_PROVIDERS.items():\n    fn()\n',
     "讀 registry 內部、完全沒有能力字串（只有 ① 抓得到）"),
    ('from core.registry import *\nx = single_provider(cap_from_somewhere)\n', "星號 import（只有 ② 抓得到）"),
])
def test_bypassing_the_getters_is_unresolved(src, why):
    files = {**_P_FILES, "backend/modules/c/api.py": src}
    if "consts" in src or "PCAP" in src:
        files["backend/helpers/consts.py"] = 'PCAP = "p.cap"\n'     # 只在用到時放（沒人用的能力常數本身就判不了，會混淆這一題）
    repo = _repo(files)
    pc = ST.provider_check(repo, "p", ["backend/modules/p/api.py"], policy="consumers")
    assert pc["reject"] and pc["unresolved"], (why, pc)


def test_co_providers_of_the_same_capability_are_not_stray():
    """同一能力可以有多個提供者：別的模組在 ModuleSpec.providers／provide 登記同一個 cap，不是取用、不算判不了。"""
    other = ('from core.registry import ModuleSpec\nfrom core import registry\nfrom . import api\n'
             'MODULE = ModuleSpec(key="q", providers={("p.cap", "q"): api.g})\n'
             'registry.provide("p.cap", "q2", api.g)\n')
    repo = _repo({**_P_FILES, "backend/modules/q/__init__.py": other, "backend/modules/q/api.py": "def g(): pass\n"})
    pc = ST.provider_check(repo, "p", ["backend/modules/p/api.py"], policy="consumers")
    assert not pc["reject"], pc


def test_registry_internals_allowlist_is_needed_and_minimal(real_repo):
    """白名單的正對照：拿掉 core/catalog.py ⇒ 它真的會被抓（白名單不是空設）；白名單外沒有任何人讀 registry 內部。"""
    assert set(ST.REGISTRY_INTERNALS_ALLOWED) == {"backend/core/catalog.py"}
    assert not ST.registry_bypasses(real_repo, "case"), "白名單外有人讀 registry 內部"
    saved = dict(ST.REGISTRY_INTERNALS_ALLOWED)
    try:
        ST.REGISTRY_INTERNALS_ALLOWED.clear()
        hits = ST.registry_bypasses(real_repo, "case")
    finally:
        ST.REGISTRY_INTERNALS_ALLOWED.update(saved)
    assert any(h.startswith("backend/core/catalog.py:") for h in hits), hits


def test_capability_string_allowlist_entries_are_live(real_repo):
    """例外清單每一筆今天仍對得上（那個檔真的在非取用位置出現那個字串）；拿掉它 ⇒ 真的會被抓（例外不是空設）。"""
    for (rel, cap), why in ST.CAPABILITY_STRING_ALLOWED.items():
        assert why, (rel, cap)
        consts = [n for n in ast_walk(real_repo, rel) if getattr(n, "value", None) == cap]
        assert consts, "例外清單過期：%s 已沒有 %r ⇒ 刪掉這一筆" % (rel, cap)
    saved = dict(ST.CAPABILITY_STRING_ALLOWED)
    try:
        ST.CAPABILITY_STRING_ALLOWED.clear()
        pc = ST.provider_check(ST.Repo(real_repo.sources), "case", ["backend/modules/case/x.py"], policy="consumers")
    finally:
        ST.CAPABILITY_STRING_ALLOWED.update(saved)
    assert any(u.startswith("backend/routers/approval_queue.py:") for u in pc["unresolved"]), pc["unresolved"]


def ast_walk(repo, rel):
    import ast
    return list(ast.walk(repo.file(rel).tree))


def test_real_repo_every_provider_module_resolves(real_repo):
    """今天所有提供串接點的模組都要判得出來（否則單模組包對它們一律退回乙——要知道是哪一處）。"""
    bad = {}
    for d in sorted((REPO / "backend" / "modules").iterdir()):
        if (d / "module.json").is_file():
            pc = ST.provider_check(real_repo, d.name, ["backend/modules/%s/x.py" % d.name], policy="consumers")
            if pc["reject"]:
                bad[d.name] = pc["unresolved"][:5]
    assert not bad, bad


# ── 真實 repo 正對照（DB2-M1 補題；讀碼 2026-09-28 核對的實際消費端）──────────────────

@pytest.fixture(scope="module")
def real_repo():
    src = {}
    for p in (REPO / "backend").rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if "__pycache__" not in rel:
            src[rel] = p.read_text(encoding="utf-8")
    return ST.Repo(src)


def test_real_arap_attachments_provider_reaches_accounting(real_repo):
    """arap 在模組層 provide 了 attachments.for_document（invoice_vouchers.py）與 calendar.writeback ⇒ 消費端含
    accounting 的附件彙整（voucher_attachments.py）與 L1 google_calendar。〔更正 D 複審：case 是同一能力的另一個提供者，不是消費端〕"""
    pc = ST.provider_check(real_repo, "arap", ["backend/modules/arap/api/invoice_vouchers.py"], policy="consumers")
    assert {"attachments.for_document", "calendar.writeback"} <= set(pc["caps"]), pc["caps"]
    assert "backend/modules/accounting/voucher_attachments.py" in pc["consumers"], pc["consumers"]
    assert "backend/helpers/google_calendar.py" in pc["consumers"], pc["consumers"]
    assert not pc["reject"], pc["reason"]


def test_real_case_access_reaches_netplan_and_accounting(real_repo):
    """case.access：netplan 是**直接**消費端（netplan/api.py single_provider，DB3-S1）；L1 helpers/case_access 也是；
    accounting 經 helpers/case_access 間接用到（voucher_attachments.py import case_access）⇒ 要靠 modtest 選題展開。"""
    pc = ST.provider_check(real_repo, "case", ["backend/modules/case/api/quotations.py"], policy="consumers")
    assert "case.access" in pc["caps"]
    assert "backend/modules/netplan/api.py" in pc["consumers"], pc["consumers"]
    assert "backend/helpers/case_access.py" in pc["consumers"], pc["consumers"]
    assert not pc["reject"], pc["reason"]


def test_real_ast_capabilities_match_runtime_registry(client, real_repo):
    """能力清單的交叉比對（取代設計裡的 dep_graph 比對：dep_graph.json 沒有 capability 資料）：
    載入後 registry 實際登記的（ModuleSpec.providers＋模組層 provide），依提供函式所屬模組歸戶，必須 ⊆ AST 算出來的。
    ☠️ AST 漏掉一種登記寫法 ⇒ 這一題紅（找不到 ≠ 沒有）。"""
    from core import registry
    runtime = {}
    for m in registry.loaded():
        for (cap, _name), _fn in m.spec.providers.items():
            runtime.setdefault(m.key, set()).add(cap)
    for (cap, _name), fn in registry._LEGACY_PROVIDERS.items():
        mod = getattr(fn, "__module__", "") or ""
        if mod.startswith("modules."):
            runtime.setdefault(mod.split(".")[1], set()).add(cap)
    assert runtime, "正對照：載入後應該有模組提供串接點"
    missing = {}
    for key, caps in runtime.items():
        ast_caps, un = ST.capabilities(real_repo, key)
        assert not un, (key, un)
        if caps - ast_caps:
            missing[key] = sorted(caps - ast_caps)
    assert not missing, "AST 能力清單漏了執行期實際登記的：%s" % missing


def test_real_history_tender_only_commit_is_tier2():
    """正對照（〈盤點工具的正對照〉）：a4071fab 只改 tender_radar 的 SPEC 與對照表 ⇒ 2。"""
    try:
        subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", "a4071fab^{commit}"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pytest.skip("repo 沒有 a4071fab（淺複製）")
    r = ST.tier_for("a4071fab^", "a4071fab")
    assert (r["tier"], r["key"]) == (2, "tender_radar"), r


def test_real_history_l1_commit_is_tier3():
    """反向控制：d0f1078a 改了 L1 helpers/geo.py ⇒ 3。"""
    try:
        subprocess.run(["git", "-C", str(REPO), "cat-file", "-e", "d0f1078a^{commit}"], check=True, capture_output=True)
    except subprocess.CalledProcessError:
        pytest.skip("repo 沒有 d0f1078a（淺複製）")
    r = ST.tier_for("d0f1078a^", "d0f1078a")
    assert r["tier"] == 3 and any(f == "backend/helpers/geo.py" for f, _ in r["offenders"]), r
