# -*- coding: utf-8 -*-
"""H1 熱修：PDF 渲染硬化（CSP＋Edge 旗標）與五個輸出點逸出。

使用者可寫入的欄位若漏逸出，HTML 會在無頭 Edge 以 file:// 來源渲染：`<iframe src=file:///…>`／`<object>`／`<embed>` 把本機檔案畫進 PDF，`<script>` 對外發請求。
所有 HTML→PDF 都經 `helpers.startup.run_edge_pdf`（單一出入口）：①寫入 CSP `<meta>`（內嵌腳本以 SHA-256 白名單）②旗標：主機名稱解析全部失敗（只放行 localhost）、停用擴充功能與同步。

①純函式：CSP 內容、腳本雜湊、冪等、旗標   ②五個輸出點（數量、有效日數、款項百分比、階段起訖日）逸出，數字資料輸出不變
③真的渲染（需要 Edge；沒有就略過）：有 CSP 時 iframe 不顯示本機檔案、script 沒有任何對外連線；對照組（放寬的 CSP）證明測試真的能看見洩漏
④回歸：一般文件（報價單、出貨單、請款單、完工單、薪資單）硬化前後頁數、文字、圖片數相同
"""
import base64
import hashlib
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
from pathlib import Path

import pytest

from helpers import startup as ST


@pytest.fixture(autouse=True)
def _isolated_edge_profile_state(monkeypatch, tmp_path_factory):
    """本檔會真的渲染（經 run_edge_pdf）：產品的專屬 profile 池與根目錄是模組層級的狀態，不隔離的話，
    本檔跑完會留下『已用真實根目錄初始化』的池，讓後面的 tests/test_edge_profile_2026_09_25.py 看到真實的 backend/logs/edge_profiles（順序相依的紅燈）。
    ⇒ 每個測試用獨立的根目錄與全新的池／狀態，monkeypatch 結束時全部還原。"""
    monkeypatch.setattr(ST, "_EDGE_PROFILE_ROOT", str(tmp_path_factory.mktemp("h1_edge_profiles")))
    monkeypatch.setattr(ST, "_EDGE_PROFILE_POOL", [])
    monkeypatch.setattr(ST, "_EDGE_PROFILE_STATE", {"init": False, "runs": 0})

EVIL = "<b>%s&'\"</b>"
ESC = "&lt;b&gt;%s&amp;&#x27;&quot;&lt;/b&gt;"


# ── ① 純函式 ───────────────────────────────────────────────────────────────
def test_csp_has_the_required_directives_and_no_unsafe_script():
    csp = ST._csp_for_html("<html><head></head><body>x</body></html>")
    for d in ("default-src 'none'", "img-src data: file:", "style-src 'unsafe-inline'", "font-src data: file:", "frame-src 'none'", "object-src 'none'",
              "form-action 'none'", "base-uri 'none'", "connect-src 'none'", "script-src 'none'"):
        assert d in csp, d
    assert "script-src 'unsafe-inline'" not in csp and "unsafe-eval" not in csp


def test_inline_scripts_are_allowed_only_by_hash_and_external_scripts_never():
    body1, body2 = "var x=1;", "\nvar y=2\n"
    html = '<html><head></head><body><script>%s</script><script src="a.js"></script><script type="text/javascript">%s</script></body></html>' % (body1, body2)
    csp = ST._csp_for_html(html)
    for b in (body1, body2):
        assert "'sha256-%s'" % base64.b64encode(hashlib.sha256(b.encode()).digest()).decode() in csp
    assert csp.count("sha256-") == 2 and "a.js" not in csp


def test_inject_csp_is_placed_after_head_and_uses_our_own_meta():
    html = '<!DOCTYPE html><html><head><meta charset="UTF-8"></head><body>x</body></html>'
    out = ST._inject_csp(html)
    assert out.startswith('<!DOCTYPE html><html><head><meta id="motrix-csp" http-equiv="Content-Security-Policy"')
    assert ST._inject_csp("<p>no head</p>").startswith('<meta id="motrix-csp"')
    assert ST._inject_csp("<html><body>x</body></html>").startswith('<html><meta id="motrix-csp"')
    assert ST._inject_csp('<html lang="zh"><body>x</body></html>').startswith('<html lang="zh"><meta id="motrix-csp"')


def test_a_text_field_cannot_switch_the_csp_off():
    """04 M1：使用者文字含 `http-equiv=Content-Security-Policy`（沒有 < > & 引號，逸出後原樣保留）不能讓整份文件跳過我們的 CSP。"""
    for payload in ("http-equiv=Content-Security-Policy", 'http-equiv = "Content-Security-Policy" content=default-src *', "Content-Security-Policy"):
        html = "<!DOCTYPE html><html><head></head><body><p>%s</p></body></html>" % payload.replace('"', "&quot;")
        out = ST._inject_csp(html)
        assert out.count('<meta id="motrix-csp"') == 1 and "default-src 'none'" in out, payload
        assert ST._inject_csp(out).count('<meta id="motrix-csp"') == 2, "重複插入無害（政策取交集）"


def test_head_pattern_does_not_match_header_or_headline_tags():
    out = ST._inject_csp("<html><header>H</header><headline>x</headline><body>y</body></html>")
    assert out.startswith("<html><meta id=\"motrix-csp\""), "沒有 <head>：插在 <html> 之後，不是 <header> 之後"
    out2 = ST._inject_csp("<html><header>H</header><head><title>t</title></head><body></body></html>")
    assert out2.index('<meta id="motrix-csp"') > out2.index("<head>") and out2.index('<meta id="motrix-csp"') < out2.index("<title>")


def test_an_injected_script_does_not_get_a_hash_that_allows_the_page_scripts_only():
    page = "<html><head></head><body><script>var ok=1;</script>%s</body></html>"
    assert ST._csp_for_html(page % "") == ST._csp_for_html(page % "<p>x</p>")
    # 攻擊者注入的 script 是另一段內容 ⇒ 雜湊不同；但注意：這份 HTML 是『最終內容』，注入的 script 若在 _inject_csp 之前就在裡面，也會被算進白名單——
    # 所以第一道防線仍是輸出逸出（五個輸出點）；CSP 擋的是 iframe／object／embed／連線／事件屬性，以及渲染過程中動態產生的東西。
    assert ST._csp_for_html(page % "<script>evil()</script>").count("sha256-") == 2


def test_edge_flags_are_inserted_just_before_the_html_argument_and_existing_positions_do_not_move():
    cmd = ["edge", "--user-data-dir=P", "--headless", "--no-sandbox", "--print-to-pdf=x.pdf", "file:///x.html"]
    out = ST._harden_cmd(cmd)
    assert out[:5] == cmd[:5] and out[-1] == "file:///x.html", "既有旗標的位置不變（--user-data-dir 仍在第 2 個）"
    assert out[5:-1] == list(ST._HARDEN_FLAGS) and "--proxy-server=http://127.0.0.1:9" in out and "--proxy-bypass-list=<-loopback>" in out
    assert ST._harden_cmd(out) == out, "已經帶了就不重複"


def test_a_command_without_a_file_url_is_left_untouched():
    for cmd in (["msedge.exe", "--headless", "a"], ["msedge.exe", "--user-data-dir=X", "--headless", "a"], ["edge", "--version"]):
        assert ST._harden_cmd(cmd) == cmd


def test_harden_html_file_rewrites_the_html_that_the_command_points_to(tmp_path):
    f = tmp_path / "a.html"
    f.write_text("<html><head></head><body>x</body></html>", encoding="utf-8")
    ST._harden_html_file(["edge", "--print-to-pdf=x.pdf", "file:///" + str(f).replace("\\", "/")])
    assert "Content-Security-Policy" in f.read_text(encoding="utf-8")
    ST._harden_html_file(["edge", "--version"])          # 不是渲染 HTML 的命令 ⇒ 不做事


def test_harden_html_file_works_for_a_path_with_spaces_and_chinese(tmp_path):
    d = tmp_path / "含 空白 的 目錄"
    d.mkdir()
    f = d / "文件 一.html"
    f.write_text("<html><head></head><body>x</body></html>", encoding="utf-8")
    ST._harden_html_file(["edge", "--print-to-pdf=x.pdf", "file:///" + str(f).replace("\\", "/")])
    assert 'id="motrix-csp"' in f.read_text(encoding="utf-8"), "各 builder 組的是未編碼路徑（含空白與中文）；硬化必須照樣找得到檔案"


# ── ② 五個輸出點 ────────────────────────────────────────────────────────────
def _quote(**over):
    q = {"quoteNo": "MQ-202610-001", "customerName": "甲公司", "projectName": "專案", "status": "草稿", "validDays": 30,
         "items": [{"description": "品項", "brand": "", "unit": "式", "qty": 2, "unitPrice": 100, "amount": 200, "type": "item", "cost": 50, "margin": 10}]}
    q.update(over)
    return q


def test_quote_pdf_escapes_qty_and_valid_days():
    import pdf_gen
    tot = {"subtotal": 200, "pretax": 200, "tax": 10, "total": 210}
    for internal in (False, True):
        q = _quote(validDays=EVIL % "validDays")
        q["items"][0]["qty"] = EVIL % "qty"
        html = pdf_gen._build_quote_html(q, tot, internal=internal)
        assert EVIL % "qty" not in html and EVIL % "validDays" not in html, internal
        assert ESC % "qty" in html and ESC % "validDays" in html, internal
    base = pdf_gen._build_quote_html(_quote(), tot)
    assert "2</td>" in base and "30 日內" in base, "數字資料輸出不變"


def test_shipping_pdf_escapes_qty():
    import pdf_gen
    n = {"noteNo": "DN-202610-001", "status": "草稿", "customerName": "甲", "items": [{"description": "品", "qty": EVIL % "qty", "unit": "台"}]}
    html = pdf_gen._build_shipping_html(n)
    assert EVIL % "qty" not in html and ESC % "qty" in html


@pytest.mark.parametrize("x", [5, 2.5, "3", "", None, 0, "10"])
def test_wrapping_numbers_and_plain_text_does_not_change_the_output(x):
    esc = lambda s: (s or '').replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('\n', '<br>')   # noqa: E731  pdf_gen 的區域 esc
    assert esc(str(x)) == "%s" % (x,), "esc(str(x)) 與 f-string 直接內插相同（None 仍印 'None'，與舊行為一致）"


def test_the_stage_period_and_pct_sinks_are_wrapped_in_the_source():
    src = (Path(__file__).resolve().parents[1] / "pdf_gen.py").read_text(encoding="utf-8")
    assert src.count("{esc(_stage_period(st))}") == 2 and "{esc(str(pr[\"pct\"]))}%" in src
    assert "{item.get(\"qty\",\"\")}" not in src and "{q.get(\"validDays\",30)}" not in src and "{_stage_period(st)}" not in src


# ── ③ 真的渲染 ─────────────────────────────────────────────────────────────
def _edge():
    try:
        from helpers import _get_edge_path
        p = _get_edge_path()
    except Exception:                                      # noqa: BLE001
        p = None
    if not p or not os.path.exists(p):
        pytest.skip("這台機器沒有 Edge")
    return p


def _render(html: str, harden: bool, tmp: Path, name="r") -> bytes:
    """渲染一份 HTML。harden=True ⇒ 走產品的 run_edge_pdf（CSP＋旗標）；False ⇒ 對照組：放寬的 CSP、原始指令（沒有硬化旗標）。"""
    edge = _edge()
    f = tmp / (name + ".html")
    out = tmp / (name + ".pdf")
    if not harden:
        html = html.replace("<head>", "<head><meta http-equiv=\"Content-Security-Policy\" content=\"default-src * 'unsafe-inline' data: file:\">", 1) if "<head>" in html else (
            "<meta http-equiv=\"Content-Security-Policy\" content=\"default-src * 'unsafe-inline' data: file:\">" + html)
    f.write_text(html, encoding="utf-8")
    url = "file:///" + str(f).replace("\\", "/")
    prof = tmp / ("prof_" + name)
    cmd = [edge, "--headless", "--disable-gpu", "--no-sandbox", "--print-to-pdf=%s" % out, "--no-pdf-header-footer", "--run-all-compositor-stages-before-draw", url]
    if harden:
        ST.run_edge_pdf(cmd)
    else:
        subprocess.run(cmd[:1] + ["--user-data-dir=%s" % prof] + cmd[1:], timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    assert out.exists() and out.stat().st_size > 0, "沒有產出 PDF（%s）" % ("硬化" if harden else "對照")
    return out.read_bytes()


def _text(pdf: bytes) -> str:
    pypdf = pytest.importorskip("pypdf")
    import io
    r = pypdf.PdfReader(io.BytesIO(pdf))
    return "\n".join((p.extract_text() or "") for p in r.pages)


WININI = "C:/Windows/win.ini"


def test_file_iframe_object_embed_cannot_pull_local_files_into_the_pdf(tmp_path):
    pytest.importorskip("pypdf")
    if not os.path.exists(WININI):
        pytest.skip("沒有 C:/Windows/win.ini（非 Windows）")
    html = ("<!DOCTYPE html><html><head><meta charset=\"UTF-8\"></head><body><h2>MARK-OK</h2>"
            "<iframe src=\"file:///%s\" width=\"600\" height=\"300\"></iframe>"
            "<object data=\"file:///%s\" width=\"600\" height=\"300\"></object>"
            "<embed src=\"file:///%s\" width=\"600\" height=\"300\"></body></html>" % (WININI, WININI, WININI))
    control = _text(_render(html, False, tmp_path, "ctl"))
    if "[fonts]" not in control and "[extensions]" not in control:
        pytest.skip("對照組（放寬 CSP）也沒有顯示 win.ini——這台機器的 Edge 不渲染本機 iframe，無法證明硬化有效")
    hardened = _text(_render(html, True, tmp_path, "hard"))
    assert "MARK-OK" in hardened
    assert "[fonts]" not in hardened and "[extensions]" not in hardened and "for 16-bit app support" not in hardened, "硬化後仍把 win.ini 畫進 PDF"


def _listener():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(8)
    srv.settimeout(0.5)
    hits = []
    stop = threading.Event()

    def loop():
        while not stop.is_set():
            try:
                c, _a = srv.accept()
            except (socket.timeout, OSError):
                continue
            try:
                c.settimeout(0.5)
                hits.append(c.recv(200))
                c.sendall(b"HTTP/1.1 200 OK\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                c.close()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return srv, hits, stop, t


def test_script_and_resource_requests_make_no_outbound_connection(tmp_path):
    _edge()
    srv, hits, stop, t = _listener()
    port = srv.getsockname()[1]
    try:
        html = ("<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><link rel=\"stylesheet\" href=\"http://127.0.0.1:%d/s.css\"></head><body><h2>MARK</h2>"
                "<script>fetch('http://127.0.0.1:%d/fetch').catch(function(){});new Image().src='http://127.0.0.1:%d/beacon.png';</script>"
                "<img src=\"http://127.0.0.1:%d/i.png\" onerror=\"fetch('http://127.0.0.1:%d/onerror')\">"
                "<iframe src=\"http://127.0.0.1:%d/frame\"></iframe></body></html>" % ((port,) * 6))
        _render(html, False, tmp_path, "ctl")
        control_hits = len(hits)
        del hits[:]
        _render(html, True, tmp_path, "hard")
        assert control_hits >= 1, "對照組（放寬 CSP）沒有任何連線——這台機器上測試無法證明硬化有效"
        assert len(hits) == 0, "硬化後仍有對外連線：%r" % hits[:3]
    finally:
        stop.set()
        t.join(2)
        srv.close()


# ── ④ 回歸：一般文件硬化前後相同 ───────────────────────────────────────────
def _doc_htmls():
    import pdf_gen
    import modules.case.completion_pdf as cp
    tot = {"subtotal": 200, "pretax": 200, "tax": 10, "total": 210}
    out = {
        "quote": pdf_gen._build_quote_html(_quote(), tot),
        "quote_internal": pdf_gen._build_quote_html(_quote(), tot, internal=True),
        "shipping": pdf_gen._build_shipping_html({"noteNo": "DN-202610-001", "status": "已核准", "customerName": "甲", "items": [{"description": "品", "qty": 3, "unit": "台"}]}),
        "payment_request": pdf_gen._build_payment_request_html({"requestNo": "PR-202610-001", "status": "已核准"}),
        "completion": cp._build_completion_html({"noteNo": "CN-202610-001", "status": "已核准"}),
        "payslip": pdf_gen._build_payslip_html({"companyName": "測試股份有限公司", "companyTaxId": "11111111", "companyContactInfo": "04-1111-1111"}),
    }
    return out


@pytest.mark.parametrize("name", ["quote", "quote_internal", "shipping", "payment_request", "completion", "payslip"])
def test_normal_documents_render_the_same_before_and_after_hardening(name, tmp_path):
    pypdf = pytest.importorskip("pypdf")
    import io
    html = _doc_htmls()[name]
    a = _render(html, False, tmp_path, "before_" + name)
    b = _render(html, True, tmp_path, "after_" + name)
    ra, rb = pypdf.PdfReader(io.BytesIO(a)), pypdf.PdfReader(io.BytesIO(b))
    assert len(ra.pages) == len(rb.pages), "頁數不同"
    assert _text(a) == _text(b), "文字內容不同"
    assert [len(p.images) for p in ra.pages] == [len(p.images) for p in rb.pages], "圖片數不同"
    assert _text(b).strip(), "硬化後的 PDF 沒有任何文字（字型被擋？）"


def test_hardening_also_applies_when_the_temp_path_has_spaces_and_chinese(tmp_path):
    """各 builder 組的 file URL 不編碼：路徑含空白與中文時，硬化仍要找得到檔案並生效（否則 iframe 會把 win.ini 畫進 PDF）。"""
    pytest.importorskip("pypdf")
    if not os.path.exists(WININI):
        pytest.skip("沒有 C:/Windows/win.ini（非 Windows）")
    d = tmp_path / "含 空白 的 目錄"
    d.mkdir()
    html = ("<!DOCTYPE html><html><head><meta charset=\"UTF-8\"></head><body><h2>MARK-OK</h2>"
            "<iframe src=\"file:///%s\" width=\"600\" height=\"300\"></iframe></body></html>" % WININI)
    text = _text(_render(html, True, d, "文件 一"))
    assert "MARK-OK" in text and "[fonts]" not in text and "[extensions]" not in text and "for 16-bit app support" not in text


def test_a_missing_html_file_is_skipped_not_fatal(tmp_path):
    ST._harden_html_file(["edge", "--print-to-pdf=x.pdf", "file:///" + str(tmp_path / "nope.html").replace("\\", "/")])      # 不丟例外
