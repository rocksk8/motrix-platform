# -*- coding: utf-8 -*-
"""蒐集自然人個資的表單 ⇒ 個資蒐集告知區塊（CUSTOMIZATION-SPEC §9.3；MODULE-GUIDE §11）。

機器可讀的清單：`docs/platform/pii_forms.json`（鍵＝頁面檔名，頁面可能在 L1 或模組資料夾，位置一律問
`core.source_tree.page_files()`）。每一張「有個資輸入欄位」的頁面都要在清單上有一個決定：
  - `notice`：頁面有告知區塊（列印告知書＋「已告知當事人」＋「尚未記錄個資告知」），並有伺服器端的紀錄端點。
    端點由 L2 模組提供時寫 `api_module`：那個模組不在這個安裝包 ⇒ 不比對端點（PLAYBOOK §B-11）；模組在 ⇒ 照常比對。
    **逐欄**（稽核 D PN-M1，主持裁示 2026-09-26）：`notice` 也要列 `fields`＝這個告知對象涵蓋的欄位。一頁上有兩種以上
    當事人時用 `notices`（清單），每一個對象各有 `subject`、`fields`、紀錄端點；所有對象的 `fields` 聯集＝掃描結果，
    同一欄不可以同時屬於兩個對象，而且每個對象在頁面上有自己的區塊 `data-privacy-subject="<subject>"`。
    ⇒ 告知頁多一個個資欄位（例：出貨單的收件人）一樣轉紅，要有人決定它屬於哪一個當事人。
  - `covered_by`：這頁的個資是從另一張有告知的主檔帶進來、而且**不能手打**（輸入元素是 readonly／disabled）。
    主持裁示 2026-09-26：可以手動輸入的聯絡人就是在蒐集個資 ⇒ 要 `notice`。
  - `not_natural_person`：欄位屬於法人（公司本身），不是自然人。
非 `notice` 的決定要逐欄寫出 `fields`，與掃描結果一模一樣；頁面多了一個個資欄位 ⇒ 轉紅，要有人重新決定。

偵測方式：`x-model` 綁定路徑的最後一段（去掉底線、轉小寫）以個資欄位字尾結尾（`PII_SUFFIXES`）。
⚠ 守不到：不經 `x-model` 的輸入（例：`:value` ＋ `@input`、原生 `<form>` 的 `name=`）；目前產品頁面沒有這種寫法。
⚠ 範圍：`page_files()`（L1 頁面＋模組頁面），不含入口 `index.html`（沒有表單）。

用法：python backend/tests/platform/_pii_forms.py   列出掃描結果（頁面 ⇒ 個資欄位）
"""
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BACKEND = HERE.parents[1]
REPO = BACKEND.parent
REGISTRY = REPO / "docs" / "platform" / "pii_forms.json"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

#: 自然人個資欄位的字尾（綁定路徑最後一段去底線、轉小寫後比對）。
PII_SUFFIXES = ("phone", "mobile", "email", "address", "idnumber", "contactname", "contactperson",
                "bankaccountnumber", "birthday", "birthdate",
                "recipient")      # 簽收人姓名（出貨單；稽核 D PN-M1：原本掃不到）
#: 強個資：不可以用 `covered_by`／`not_natural_person` 帶過，頁面本身一定要有告知區塊。
STRONG_SUFFIXES = ("idnumber", "birthday", "birthdate")

#: 告知區塊的必要標記（contractors.html 的 R3 寫法；新表單照抄）。
NOTICE_MARKERS = ("data-privacy-card", "data-print-notice", "data-privacy-ack", "data-privacy-missing",
                  "static/privacy-notice.js")

_XMODEL = re.compile(r'x-model(?:\.[a-z]+)*\s*=\s*"([^"]+)"')


def product_pages():
    from core import source_tree
    return source_tree.page_files()


def product_router_text():
    from core import source_tree
    return "\n".join(p.read_text(encoding="utf-8") for p in source_tree.router_files())


def _suffix_of(binding):
    last = re.split(r"[.\[\]]", binding.strip())
    last = [x for x in last if x]
    if not last:
        return None
    key = last[-1].replace("_", "").lower()
    for suf in PII_SUFFIXES:
        if key.endswith(suf):
            return suf
    return None


def pii_fields(text):
    """頁面裡的個資欄位綁定（排序、去重）。"""
    out = set()
    for m in _XMODEL.finditer(text):
        if _suffix_of(m.group(1)):
            out.add(m.group(1).strip())
    return sorted(out)


#: 一個輸入元素：屬性值可以含 `>`（例：`@click="a => b"`），所以按引號走，不在第一個 `>` 截斷
_TAG = re.compile(r'<(?:input|textarea|select)\b(?:[^>"\']|"[^"]*"|\'[^\']*\')*>')
#: 屬性名稱：前面是空白，後面接空白、`>`、`/`、`=` 或結尾（稽核 D PN-S3：屬性值裡的同名單字不算）
_ATTR_NAME = re.compile(r'\s([:@]?[\w.:-]+)(?=\s|/?>|=|$)')


def _attr_names(tag):
    """標籤裡的屬性名稱（先把引號內的屬性值拿掉，值裡的字不會被當成屬性名稱）。"""
    bare = re.sub(r'"[^"]*"|\'[^\']*\'', '""', tag)
    return {m.group(1) for m in _ATTR_NAME.finditer(bare)}


def _not_typeable(text, binding):
    """這個綁定的每一個輸入元素都帶靜態 `readonly` 或 `disabled` **屬性**（不是 `:disabled` 這種依狀態的，
    也不是 `title="readonly …"`、`:class="{ disabled }"` 這種出現在屬性值裡的字）。"""
    tags = [m.group(0) for m in _TAG.finditer(text)
            if re.search(r'x-model(?:\.[a-z]+)*\s*=\s*"' + re.escape(binding) + '"', m.group(0))]
    return bool(tags) and all(_attr_names(t) & {"readonly", "disabled"} for t in tags)


def scan(pages=None):
    """{頁面檔名: [個資欄位綁定]}（只列有個資欄位的頁面）。pages 預設＝產品全部頁面。"""
    res = {}
    for f in (product_pages() if pages is None else pages):
        fields = pii_fields(Path(f).read_text(encoding="utf-8"))
        if fields:
            res[Path(f).name] = fields
    return res


def load_registry(path=REGISTRY):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def violations(registry=None, pages=None, router_text=None):
    """清單與頁面對不上的地方（空清單＝全部有人決定過，而且決定還成立）。"""
    reg = registry if registry is not None else load_registry()
    forms = reg.get("forms", {})
    pages = product_pages() if pages is None else list(pages)
    by_name = {Path(p).name: Path(p) for p in pages}
    found = scan(pages)
    routers = router_text
    errs = []
    for page, fields in found.items():
        if page not in forms:
            errs.append(f"{page}：有個資欄位 {fields}，但 pii_forms.json 沒有決定（加告知區塊，或寫明 covered_by／not_natural_person）")
    for page, dec in forms.items():
        f = by_name.get(page)
        if f is None or not f.is_file():
            errs.append(f"{page}：清單上有，但頁面不存在（過期的決定）")
            continue
        text = f.read_text(encoding="utf-8")
        fields = found.get(page, [])
        if not fields:
            errs.append(f"{page}：清單上有，但掃描不到個資欄位（過期的決定，或偵測規則壞了）")
        kinds = [k for k in ("notice", "notices", "covered_by", "not_natural_person") if k in dec]
        if len(kinds) != 1:
            errs.append(f"{page}：要剛好一種決定（notice／notices／covered_by／not_natural_person），現在是 {kinds}")
            continue
        kind = kinds[0]
        if kind in ("notice", "notices"):
            subjects = [dec["notice"]] if kind == "notice" else list(dec["notices"] or [])
            if not subjects:
                errs.append(f"{page}：notices 是空的")
                continue
            missing = [m for m in NOTICE_MARKERS if m not in text]
            if missing:
                errs.append(f"{page}：決定是 notice，但頁面缺告知區塊的標記 {missing}")
            if routers is None:
                routers = product_router_text()
            seen = {}
            told = [n for n in subjects if not ({"covered_by", "not_natural_person"} & set(n))]
            for n in subjects:
                who = n.get("subject") or "notice"
                nf = n.get("fields")
                if {"covered_by", "not_natural_person"} & set(n):
                    # 逐欄的其他決定（例：報價單上業務自己的 Email／電話由使用者帳號涵蓋），規則同整頁的 covered_by／not_natural_person
                    sub = "covered_by" if "covered_by" in n else "not_natural_person"
                    errs += _other_decision_errors(page, forms, text, sub, n, nf or [], who)
                    for x in nf or []:
                        if x in seen:
                            errs.append(f"{page}：欄位 {x} 同時屬於 {seen[x]} 與 {who}（一欄只能有一個告知對象）")
                        seen[x] = who
                    continue
                if n.get("purpose") not in ("contractor", "contact", "user"):
                    errs.append(f"{page}：{who}.purpose 不認得：{n.get('purpose')!r}")
                apis = n.get("ack_api") or []
                if not apis:
                    errs.append(f"{page}：{who} 要列出伺服器端的紀錄端點 ack_api")
                mod = n.get("api_module")
                if mod is not None:
                    from core import source_tree
                    if not source_tree.module_installed("modules/%s/" % mod):
                        apis = []                        # 端點的模組不在這個安裝包（PLAYBOOK §B-11）
                for a in apis:
                    if f'"{a}"' not in routers:
                        errs.append(f"{page}：ack_api {a} 在 router 裡找不到")
                if not nf:
                    errs.append(f"{page}：{who} 要逐欄列出它涵蓋的 fields（稽核 D PN-M1）")
                for x in nf or []:
                    if x in seen:
                        errs.append(f"{page}：欄位 {x} 同時屬於 {seen[x]} 與 {who}（一欄只能有一個告知對象）")
                    seen[x] = who
                if len(told) > 1:
                    if not n.get("subject"):
                        errs.append(f"{page}：notices 有兩個以上對象，每一個都要寫 subject")
                    elif f'data-privacy-subject="{n["subject"]}"' not in text:
                        errs.append(f"{page}：告知對象 {n['subject']} 在頁面上沒有自己的區塊（data-privacy-subject=\"{n['subject']}\"）")
            if sorted(seen) != fields:
                errs.append(f"{page}：notice 的 fields 與掃描結果不同（多了或少了個資欄位，要決定它屬於哪一個告知對象）："
                            f"清單 {sorted(seen)}，掃描 {fields}")
            continue
        if sorted(dec.get("fields") or []) != fields:
            errs.append(f"{page}：{kind} 的 fields 與掃描結果不同（多了或少了個資欄位，要重新決定）："
                        f"清單 {sorted(dec.get('fields') or [])}，掃描 {fields}")
        errs += _other_decision_errors(page, forms, text, kind, dec, fields, kind)
    return errs


def _is_notice(dec):
    return bool(dec) and ("notice" in dec or any(not ({"covered_by", "not_natural_person"} & set(n))
                                                 for n in dec.get("notices") or []))


def _other_decision_errors(page, forms, text, kind, dec, fields, who):
    """`covered_by`／`not_natural_person`（整頁或逐欄）的規則。"""
    errs = []
    if not str(dec.get("reason") or "").strip():
        errs.append(f"{page}：{who} 要寫 reason（誰決定、為什麼）")
    if not fields:
        errs.append(f"{page}：{who} 要逐欄列出 fields")
    strong = [x for x in fields if _suffix_of(x) in STRONG_SUFFIXES]
    if strong:
        errs.append(f"{page}：有強個資欄位 {strong}，不可以用 {kind} 帶過，頁面要有告知區塊")
    if kind == "covered_by":
        # 主持裁示 2026-09-26：手動輸入的聯絡人就是在蒐集個資 ⇒ 只有「不能手打」（readonly／disabled）的欄位可以用 covered_by
        typed = [x for x in fields if not _not_typeable(text, x)]
        if typed:
            errs.append(f"{page}：covered_by 的欄位 {typed} 可以手動輸入，要有告知區塊（notice），不可以用 covered_by 帶過")
        tgts = dec["covered_by"] if isinstance(dec["covered_by"], list) else [dec["covered_by"]]
        if not tgts:
            errs.append(f"{page}：covered_by 是空的")
        for tgt in tgts:
            if tgt == page or not _is_notice(forms.get(tgt)):
                errs.append(f"{page}：covered_by 指向 {tgt}，它不是有告知區塊（notice）的表單")
    return errs


if __name__ == "__main__":
    for k, v in scan().items():
        print(k, v)
