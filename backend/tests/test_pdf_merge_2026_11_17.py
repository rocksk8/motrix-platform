# -*- coding: utf-8 -*-
"""modules/case/pdf_merge.py：規格 PDF 併入的純函式單元測試（備註事項 B；四條不變式見該檔檔頭）。"""
import io
import os

import pypdf
import pytest

from modules.case import pdf_merge as PM


def _pdf(pages: int, text_marker: bool = False) -> bytes:
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _encrypted(pages: int = 1) -> bytes:
    w = pypdf.PdfWriter()
    for _ in range(pages):
        w.add_blank_page(width=200, height=200)
    w.encrypt("secret")
    out = io.BytesIO()
    w.write(out)
    return out.getvalue()


def _f(tmp_path, name: str, raw: bytes, fid: str = None) -> dict:
    p = tmp_path / name
    p.write_bytes(raw)
    return {"id": fid or name, "name": name, "abs_path": str(p)}


def _pages(b: bytes) -> int:
    return len(pypdf.PdfReader(io.BytesIO(b)).pages)


def test_no_files_returns_body_untouched(tmp_path):
    body = _pdf(2)
    out, sk = PM.merge_pdf_bytes(body, [])
    assert out is body and sk == []


def test_merges_in_order_and_counts_pages(tmp_path):
    body = _pdf(2)
    out, sk = PM.merge_pdf_bytes(body, [_f(tmp_path, "a.pdf", _pdf(3)), _f(tmp_path, "b.pdf", _pdf(1))])
    assert sk == [] and _pages(out) == 6


@pytest.mark.parametrize("kind,raw,reason", [
    ("encrypted", _encrypted(), "encrypted"),
    ("broken", b"%PDF-1.4\nthis is not a pdf at all", "broken"),
    ("empty", None, "empty"),
])
def test_bad_files_skipped_with_fixed_reason_and_body_kept(tmp_path, kind, raw, reason):
    if kind == "empty":
        w = pypdf.PdfWriter()
        buf = io.BytesIO()
        w.write(buf)
        raw = buf.getvalue()
    body = _pdf(2)
    good = _f(tmp_path, "good.pdf", _pdf(1))
    bad = _f(tmp_path, "bad.pdf", raw)
    out, sk = PM.merge_pdf_bytes(body, [bad, good])
    assert sk == [{"id": "bad.pdf", "name": "bad.pdf", "reason": reason}]
    assert _pages(out) == 3                                           # 本體 2 ＋ good 1；bad 沒有任何殘頁


def test_missing_file_is_skipped(tmp_path):
    f = {"id": "x", "name": "x.pdf", "abs_path": str(tmp_path / "nope.pdf")}
    out, sk = PM.merge_pdf_bytes(_pdf(1), [f])
    assert sk == [{"id": "x", "name": "x.pdf", "reason": "missing"}] and _pages(out) == 1


def test_reasons_are_only_from_fixed_vocabulary(tmp_path):
    files = [_f(tmp_path, "e.pdf", _encrypted()), _f(tmp_path, "b.pdf", b"junk"),
             {"id": "m", "name": "m", "abs_path": str(tmp_path / "zz")}, _f(tmp_path, "big.pdf", _pdf(5))]
    _, sk = PM.merge_pdf_bytes(_pdf(1), files, max_pages=3)
    assert {s["reason"] for s in sk} <= set(PM.SKIP_REASONS)
    assert {s["id"]: s["reason"] for s in sk} == {"e.pdf": "encrypted", "b.pdf": "broken", "m": "missing", "big.pdf": "over_pages"}


def test_over_pages_judged_before_merge_later_smaller_file_still_merged(tmp_path):
    big = _f(tmp_path, "big.pdf", _pdf(4))
    small = _f(tmp_path, "small.pdf", _pdf(2))
    out, sk = PM.merge_pdf_bytes(_pdf(1), [small, big, _f(tmp_path, "s2.pdf", _pdf(1))], max_pages=3)
    # small(2)＋s2(1)＝3 ≤ 3；big 放在 small 後面，會超過 ⇒ 略過
    assert [s["id"] for s in sk] == ["big.pdf"] and sk[0]["reason"] == "over_pages"
    assert _pages(out) == 1 + 2 + 1


def test_over_size_judged_by_file_bytes_not_merged_result(tmp_path):
    a = _f(tmp_path, "a.pdf", _pdf(1))
    b = _f(tmp_path, "b.pdf", _pdf(1))
    cap_mb = (os.path.getsize(a["abs_path"]) + 10) / (1024 * 1024)   # 只容得下一個
    out, sk = PM.merge_pdf_bytes(_pdf(1), [a, b], max_total_mb=cap_mb)
    assert [s["reason"] for s in sk] == ["over_size"] and sk[0]["id"] == "b.pdf" and _pages(out) == 2


def test_failure_midway_leaves_no_partial_pages(tmp_path, monkeypatch):
    """附件在途中丟例外（前幾頁已併進 writer）⇒ 整份從頭重建、該檔不在裡面、沒有殘頁。"""
    body = _pdf(2)
    ok1 = _f(tmp_path, "ok1.pdf", _pdf(2))
    flaky = _f(tmp_path, "flaky.pdf", _pdf(5))
    ok2 = _f(tmp_path, "ok2.pdf", _pdf(1))
    real_append = pypdf.PdfWriter.append

    def boom(self, fileobj, *a, **kw):
        res = real_append(self, fileobj, *a, **kw)
        if getattr(fileobj, "stream", None) is not None and len(fileobj.pages) == 5:
            raise RuntimeError("simulated mid-append failure after pages were appended")
        return res

    monkeypatch.setattr(pypdf.PdfWriter, "append", boom)
    out, sk = PM.merge_pdf_bytes(body, [ok1, flaky, ok2])
    assert sk == [{"id": "flaky.pdf", "name": "flaky.pdf", "reason": "broken"}]
    assert _pages(out) == 2 + 2 + 1                                   # 沒有 flaky 的任何一頁


def test_unreadable_body_is_returned_as_is(tmp_path):
    body = b"%PDF-1.4 not really"
    out, sk = PM.merge_pdf_bytes(body, [_f(tmp_path, "a.pdf", _pdf(1))])
    assert out == body and [s["reason"] for s in sk] == ["broken"]


def test_skip_reasons_are_not_printed_into_pdf(tmp_path):
    """略過原因只回傳、不寫進 PDF：輸出頁數＝本體＋成功的附件，且任何頁面的文字都不含原因字串／檔名。"""
    out, sk = PM.merge_pdf_bytes(_pdf(1), [_f(tmp_path, "secret_name.pdf", _encrypted()), _f(tmp_path, "g.pdf", _pdf(1))])
    assert sk and _pages(out) == 2
    r = pypdf.PdfReader(io.BytesIO(out))
    text = "".join((p.extract_text() or "") for p in r.pages)
    assert "encrypted" not in text and "secret_name" not in text and "略過" not in text
    assert not r.outline and "/Names" not in (r.trailer["/Root"])


def test_probe_pdf_statuses(tmp_path):
    assert PM.probe_pdf(_f(tmp_path, "a.pdf", _pdf(3))["abs_path"]) == ("ok", 3)
    assert PM.probe_pdf(_f(tmp_path, "e.pdf", _encrypted())["abs_path"]) == ("encrypted", 0)
    assert PM.probe_pdf(_f(tmp_path, "b.pdf", b"junk")["abs_path"]) == ("broken", 0)
    assert PM.probe_pdf(str(tmp_path / "none.pdf")) == ("broken", 0)
