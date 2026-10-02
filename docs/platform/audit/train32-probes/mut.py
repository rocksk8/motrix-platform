import subprocess, sys, os, shutil, re
ROOT = r"D:\開發測試檔\wt-t32pkg"
BE = ROOT + r"\backend"
PY = r"D:\MOTRIX-PLATFORM\.venv312\Scripts\python.exe"
T = r"C:\Users\hichan\AppData\Local\Temp\motrix-pytest-c7mut-adhoc"
CNW = 0x08000000
L = "modules/case/tests/"
MUTS = [
 ("M1 po_line_taken off", "backend/modules/case/purchase_items.py",
  'if link_ok and order.get("poLine") not in (None, ""):', 'if False and link_ok and order.get("poLine") not in (None, ""):',
  [L+"test_probe_t32_pkg_link_c7.py::test_a1_concurrent_submits_on_the_same_po_line_only_one_wins", L+"test_probe_t32_pkg_link_c7.py::test_a1b_after_the_first_is_withdrawn_the_line_is_free_again", L+"test_material_link_api_2026_10_02.py"]),
 ("M2 LINK_VALIDATOR not wired", "backend/modules/case/api/material_approvals.py",
  "_MG.LINK_VALIDATOR = _PI.link_validator", "pass",
  [L+"test_probe_t32_pkg_link_c7.py", L+"test_material_link_seam_2026_10_02.py"]),
 ("M3 drafts counted as cost", "backend/modules/case/material_approval.py",
  "if status in (S_DRAFT, S_RETURNED, S_CANCELLED):", "if status in (S_RETURNED, S_CANCELLED):",
  [L+"test_material_reports_gate_2026_10_02.py", L+"test_probe_t32_pkg_link_c7.py::test_b1b_draft_surfaces"]),
 ("M4 legacyModified not written", "backend/modules/subcontract/api/vendor_contractors.py",
  'marker["legacyModified"] = {"at": now,', 'marker["__x"] = {"at": now,',
  ["modules/subcontract/tests/test_dispatch_legacy_edit_2026_10_02.py", "modules/subcontract/tests/test_probe_t32_pkg_dispatch_c7.py::test_c1b_legacy_edit_then_completion_request_keeps_the_marker_and_the_code_is_issued"]),
 ("M5 legacy edit resets to draft again", "backend/modules/subcontract/api/vendor_contractors.py",
  'reset = changed and existing["approval_status"] == _flow.APPROVED', 'reset = changed and existing["approval_status"] in (_flow.APPROVED, "")',
  ["modules/subcontract/tests/test_dispatch_legacy_edit_2026_10_02.py", "tests/test_probe_t30_dispatch_c7.py"]),
 ("M6 queue_tags leaks amount", "backend/modules/case/purchase_items.py",
  'return [{"text": st["text"], "tone": "warn"}] if st["state"] == "none" else []', 'return [{"text": st["text"] + " $%s" % order.get("totalPrice"), "tone": "warn"}] if st["state"] == "none" else []',
  [L+"test_probe_t32_pkg_link_c7.py::test_f2_tag_text_never_contains_amounts_or_names", L+"test_material_order_link_keys_2026_10_02.py"]),
 ("M7 base_item without tags", "backend/helpers/approval_queue.py",
  '"tags":               [],', '',
  [L+"test_material_order_link_keys_2026_10_02.py"]),
 ("M8 queue lists drafts", "backend/modules/case/api/material_approvals.py",
  "WHERE a.status IN ('待審核','簽核中') ORDER BY a.rowid DESC", "WHERE a.status IN ('草稿','待審核','簽核中') ORDER BY a.rowid DESC",
  [L+"test_probe_t32_pkg_link_c7.py::test_b1_draft_is_not_in_the_queue_or_the_dot_and_tags_are_correct", L+"test_material_approval_api_2026_10_02.py"]),
]
only = sys.argv[1:] 
for name, f, old, new, tests in MUTS:
    if only and name.split()[0] not in only: continue
    p = os.path.join(ROOT, f.replace("/", "\\"))
    src = open(p, encoding="utf-8", newline="").read()
    assert src.count(old) == 1, (name, "anchor count", src.count(old))
    open(p, "w", encoding="utf-8", newline="").write(src.replace(old, new))
    try:
        r = subprocess.run([PY, "-m", "pytest", *tests, "-p", "no:cacheprovider", "-q", "--basetemp=" + T, "-x"], cwd=BE, capture_output=True, text=True, encoding="utf-8", errors="replace", creationflags=CNW,
                           env=dict(os.environ, PYTHONIOENCODING="utf-8"))
        tail = [l for l in r.stdout.splitlines() if re.search(r"passed|failed|error|FAILED", l)][-3:]
        print(name, "=>", "RED(caught)" if r.returncode == 1 else ("GREEN(NOT caught)" if r.returncode == 0 else "rc=%s" % r.returncode), "|", " / ".join(tail)[:230], flush=True)
    finally:
        subprocess.run(["git", "checkout", "--", f], cwd=ROOT, creationflags=CNW)
        shutil.rmtree(T, ignore_errors=True)
print("restored; git status:", subprocess.run(["git", "status", "--short"], cwd=ROOT, capture_output=True, text=True, creationflags=CNW).stdout.replace("\n", "; ")[:300])
