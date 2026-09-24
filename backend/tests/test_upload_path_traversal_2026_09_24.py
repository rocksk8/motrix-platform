# -*- coding: utf-8 -*-
"""共用上傳存檔 `save_document_files()`：單號／子目錄不可以把檔案寫到上傳根目錄之外。

使用者裁示（2026-09-24 午，B8）：穿越檢查**補在共用函式**，不是各呼叫端各自檢查。

在此之前 `helpers/uploads.py` 直接 `os.path.join(UPLOADS_ROOT, subfolder, doc_no)`
⇒ `doc_no='../../x'` 就寫到根目錄外面。能不能被利用取決於呼叫端有沒有先查單據
存在 —— 而那不是這支函式能保證的。

## 量法

根目錄外**真的放一個誘餌目錄與誘餌檔**：擋下來的證據是「誘餌目錄裡沒有多出任何檔案、
誘餌檔內容沒變」，不是只看回應碼（回 400 而檔案已經寫出去，一樣是穿越成功）。

## ⚙️ 縱深防禦：單層突變不紅是**預期的**

`_safe_save_dir()` 有三層彼此重疊的檢查（逐段規則、doc_no 不可含 `/`、realpath
必須在根目錄下）。單拿掉其中一層，另外兩層仍擋得住 ⇒ 這批題照樣綠。
突變驗證做的是「整個檢查拿掉 ⇒ 12 題紅」（2026-09-24）。
"""
import asyncio
import io
import os

import pytest
from fastapi import HTTPException
from starlette.datastructures import UploadFile


def _file(name="a.pdf", data=b"%PDF-1.4 test"):
    return UploadFile(file=io.BytesIO(data), filename=name)


@pytest.fixture()
def roots(tmp_path, monkeypatch):
    import helpers.uploads as up
    root = tmp_path / "uploads"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "decoy.txt").write_text("誘餌", encoding="utf-8")
    monkeypatch.setattr(up, "UPLOADS_ROOT", str(root))
    return root, outside


def _save(subfolder, doc_no):
    from helpers.uploads import save_document_files
    return asyncio.run(save_document_files(subfolder, doc_no, [_file()], "tester"))


def _outside_untouched(outside):
    names = sorted(os.listdir(outside))
    assert names == ["decoy.txt"], names
    assert (outside / "decoy.txt").read_text(encoding="utf-8") == "誘餌"


@pytest.mark.parametrize("doc_no", [
    "../outside",
    "..",
    "../../outside/x",
    "..\\outside",
    "MQ-1/../../outside",
], ids=["dotdot", "bare-dotdot", "deeper", "backslash", "nested"])
def test_doc_no_cannot_escape_the_upload_root(roots, doc_no):
    root, outside = roots
    with pytest.raises(HTTPException) as e:
        _save("quotations", doc_no)
    assert e.value.status_code == 400
    _outside_untouched(outside)


def test_absolute_doc_no_is_rejected(roots):
    root, outside = roots
    with pytest.raises(HTTPException) as e:
        _save("quotations", str(outside))
    assert e.value.status_code == 400
    _outside_untouched(outside)


def test_drive_letter_doc_no_is_rejected(roots):
    root, outside = roots
    with pytest.raises(HTTPException) as e:
        _save("quotations", "C:evil")
    assert e.value.status_code == 400
    _outside_untouched(outside)


@pytest.mark.parametrize("subfolder", ["../outside", "/abs", "a/../../outside", "a\\..\\..\\outside"],
                         ids=["dotdot", "absolute", "nested", "backslash"])
def test_subfolder_cannot_escape_the_upload_root(roots, subfolder):
    root, outside = roots
    with pytest.raises(HTTPException) as e:
        _save(subfolder, "MQ-1")
    assert e.value.status_code == 400
    _outside_untouched(outside)


def test_rejected_upload_leaves_no_directory_behind(roots):
    """擋下的路徑上不可以有副作用：原本是**先** `makedirs` 再檢查檔案。"""
    root, outside = roots
    with pytest.raises(HTTPException):
        _save("quotations", "../outside/newdir")
    assert not (outside / "newdir").exists()


# ── 正對照：既有呼叫端的形狀照舊通過 ─────────────────────────────────────

@pytest.mark.parametrize("subfolder,doc_no", [
    ("quotations", "MQ-202609-001"),
    ("quotation_payment_items", "MQ-202609-001_0"),
    ("_pending_case_changes/12", "MQ-202609-001_2"),
    ("voucher_attachments", "37"),
    ("case_extra_expense", "MQ-202609-001_5"),
], ids=["quote", "payment-item", "pending-change", "voucher", "extra-expense"])
def test_normal_document_numbers_still_save_under_the_root(roots, subfolder, doc_no):
    root, outside = roots
    saved = _save(subfolder, doc_no)
    assert len(saved) == 1
    target = root / saved[0]["path"]
    assert target.is_file()
    assert os.path.commonpath([str(target.resolve()), str(root.resolve())]) == str(root.resolve())
    _outside_untouched(outside)
