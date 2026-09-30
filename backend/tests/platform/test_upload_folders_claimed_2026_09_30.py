"""稽核 S2（sec-p0，2026-09-30）：每一個會寫進 uploads/ 的資料夾，都要有人決定「誰讀得到」。

`/api/photo-token`、`/api/uploads/…` 對沒有 `uploads.path_access` 提供者認領的資料夾一律 404（預設拒絕）。
這是安全的方向，但新增一種附件而忘了登記提供者時，症狀是「上傳成功、之後永遠打不開」——而且只在畫面上才看得到。
這道守門在讀碼階段就擋下：

- 寫入點（靜態掃描產品碼）：`save_document_files("<資料夾>" 或 f"<資料夾>/…", …)` 的第一段；
  `photos._photo_root()` 回傳的網址前綴（工作日誌照片）。第一個參數算不出字面資料夾 ⇒ 也紅（要人決定）。
- 每一個寫入的資料夾 ∈ 提供者 `FOLDERS` 的聯集，或在 `EXCLUDED`（明列理由：有自己的讀取端點）。
- `EXCLUDED` 的每一條都必須真的被掃到（過期的排除不可以留著）；擁有模組不在時略過該條（獨立訊號：module.json）。

正對照：真實掃描要看到 completion_notes、_pending_case_changes、projects。反向控制：合成原始碼／合成認領集合。
"""
import ast

from core import source_tree
from helpers import uploads as up

#: 資料夾 ⇒ (擁有模組, 理由)。只收「有自己的讀取端點、刻意不經 /api/uploads」的。
EXCLUDED = {
    "voucher_attachments": ("accounting", "傳票附件走 GET /api/vouchers/{id}/attachments/{att}/download（M06 自己的權限）"),
}
#: 資料夾前綴的 demo 別名（寫入端的前綴 ⇒ 認領時用的名稱；同 helpers.uploads._DEMO_PREFIXES）
_ALIAS = {"_demo_projects": "projects"}


def _first_seg(node):
    """save_document_files 第一個參數 ⇒ 字面資料夾第一段；算不出來 ⇒ None。"""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value.split("/")[0] or None
    if isinstance(node, ast.JoinedStr) and node.values and isinstance(node.values[0], ast.Constant):
        head = str(node.values[0].value)
        return head.split("/")[0] if "/" in head else None
    return None


def scan_writers(files_src):
    """{相對路徑: 原始碼} ⇒ ({資料夾: [出處]}, [算不出資料夾的出處])。"""
    found, unresolved = {}, []
    for rel, src in files_src.items():
        tree = ast.parse(src)
        for n in ast.walk(tree):
            if isinstance(n, ast.Call):
                f = n.func
                name = f.attr if isinstance(f, ast.Attribute) else (f.id if isinstance(f, ast.Name) else "")
                if name == "save_document_files" and n.args:
                    seg = _first_seg(n.args[0])
                    if seg is None:
                        unresolved.append("%s:%d" % (rel, n.lineno))
                    else:
                        found.setdefault(seg, []).append("%s:%d" % (rel, n.lineno))
            if isinstance(n, ast.FunctionDef) and n.name == "_photo_root":
                for r in ast.walk(n):
                    if isinstance(r, ast.Return) and isinstance(r.value, ast.Tuple) and len(r.value.elts) == 2 \
                       and isinstance(r.value.elts[1], ast.Constant):
                        seg = _ALIAS.get(r.value.elts[1].value, r.value.elts[1].value)
                        found.setdefault(seg, []).append("%s:%d" % (rel, r.lineno))
    return found, unresolved


def problems(found, unresolved, claimed, excluded, installed=lambda key: True):
    out = ["算不出資料夾（第一個參數要以字面資料夾開頭，或登記進 EXCLUDED）：%s" % u for u in unresolved]
    for seg, where in sorted(found.items()):
        if seg not in claimed and seg not in excluded:
            out.append("資料夾 %s 沒有 uploads.path_access 提供者認領、也不在 EXCLUDED：%s" % (seg, where))
    for seg, (owner, _why) in sorted(excluded.items()):
        if installed(owner) and seg not in found:
            out.append("EXCLUDED 的 %s 已經沒有寫入點（過期，刪掉）" % seg)
        if seg in claimed:
            out.append("EXCLUDED 的 %s 同時被提供者認領（二選一）" % seg)
    return out


def _real_sources():
    return {source_tree.rel(p): p.read_text(encoding="utf-8") for p in source_tree.product_files()
            if "/tests/" not in source_tree.rel(p)}


def _claimed():
    from core import registry
    return {f for prov in registry.providers(up.PATH_ACCESS).values() for f in (getattr(prov, "FOLDERS", ()) or ())}


def test_every_upload_folder_is_claimed_or_excluded(client):
    found, unresolved = scan_writers(_real_sources())
    # 正對照：掃描真的看得到 L1 與 M01 的寫入點（掃不到東西時「沒有違規」是假綠）
    assert "projects" in found, found
    if source_tree.module_installed("modules/case/"):
        assert {"completion_notes", "_pending_case_changes", "quotations"} <= set(found), sorted(found)
    bad = problems(found, unresolved, _claimed(), EXCLUDED,
                   lambda key: source_tree.module_installed("modules/%s/" % key))
    assert not bad, "\n".join(bad)


def test_rc_unclaimed_new_folder_is_reported():
    src = {"modules/zz/api.py": "async def f(files):\n    await save_document_files('zz_new', '1', files, 'u')\n"}
    found, unresolved = scan_writers(src)
    assert found == {"zz_new": ["modules/zz/api.py:2"]} and unresolved == []
    assert problems(found, unresolved, claimed=set(), excluded={}) == [
        "資料夾 zz_new 沒有 uploads.path_access 提供者認領、也不在 EXCLUDED：['modules/zz/api.py:2']"]
    assert problems(found, unresolved, claimed={"zz_new"}, excluded={}) == []


def test_rc_fstring_prefix_and_unresolvable_argument():
    src = {"a.py": "save_document_files(f'_pending_case_changes/{cid}', 'x', [], 'u')\n"
                   "save_document_files(sub, 'x', [], 'u')\n"
                   "save_document_files(f'{sub}/x', 'x', [], 'u')\n"}
    found, unresolved = scan_writers(src)
    assert set(found) == {"_pending_case_changes"} and unresolved == ["a.py:2", "a.py:3"]
    assert len(problems(found, unresolved, claimed={"_pending_case_changes"}, excluded={})) == 2


def test_rc_provider_losing_a_folder_and_stale_exclusion():
    found = {"completion_notes": ["x.py:1"]}
    assert problems(found, [], claimed=set(), excluded={})           # 提供者拿掉資料夾 ⇒ 紅
    assert problems({}, [], claimed=set(), excluded={"old": ("case", "…")}) == ["EXCLUDED 的 old 已經沒有寫入點（過期，刪掉）"]
    assert problems({}, [], claimed=set(), excluded={"old": ("gone", "…")}, installed=lambda k: False) == []
    assert problems(found, [], claimed={"completion_notes"}, excluded={"completion_notes": ("case", "…")})


def test_rc_photo_root_prefix_is_seen():
    src = {"photos.py": "def _photo_root():\n    if x:\n        return D, '_demo_projects'\n    return B, 'projects'\n"}
    found, _ = scan_writers(src)
    assert set(found) == {"projects"}
