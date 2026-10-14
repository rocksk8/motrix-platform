# -*- coding: utf-8 -*-
"""H2（PDF 渲染硬化第二輪；設計 docs/platform/plans/PDF-HARDENING-ROUND2-DESIGN-T62.md）。

H2-a：`helpers/pdf_scripts.py` 註冊表（五種內嵌腳本之中走 Edge 的四種；預覽專用的不登記）＋CSP `script-src` 只認註冊表的預先算好的雜湊＋AST 守門
      ＋代理旗標（直接寫 IP 的網址也連不出去）
H2-b：出入口標籤中和（`_neutralize_html`）＋殘留檢查（`_residual_danger`）＋共用的『HTML 引數』選擇＋路徑含 #／? 與檔案不存在的處理
"""
import ast
import hashlib
import logging
import os
import re
import shutil
import socket
import subprocess
import threading
from pathlib import Path

import pytest

from helpers import pdf_scripts as PS
from helpers import startup as ST

BACKEND = Path(__file__).resolve().parents[1]
BUILDER_FILES = ["pdf_gen.py", "helpers/doc_template.py", "modules/case/completion_pdf.py", "modules/netplan/export.py", "modules/accounting/voucher_pdf.py",
                 "modules/analytics/api/reports.py", "modules/payroll/bonus_pdf.py", "modules/case/api/expense_form_pdf.py", "helpers/doc_render.py"]
#: 凍結的參考雜湊（取自 H1 當時各 builder 內嵌的原文）：註冊表的文字一個字都不能變，否則所有頁面的腳本會被 CSP 擋掉或內容改變
FROZEN = {
    "fit_a4_multi": "c13599dc4fe49922b8a92d337e4a005f803c2a3f0b3e74af9a450f7c723fd124",
    "fit_a4_single": "4d722acd301ead6b6df00fc766acfeae62620bb25a683952f0976e6c5f9cee55",
    "netplan_fit": "036d8556a31ad6101fdeae3b6e9d3e4f2d7f6dfa905763f260971666f88cd2ed",
    "payslip": "2e56758598686e5caaac66eaa47c31f4f2aba90abfb1ae52735898ae6c36c64c",
}
PREVIEW_MARK = "motrixPreviewHeight"          # pdf_gen 的預覽高度回報腳本：只加在預覽 HTML、不經 Edge，不登記


# ── H2-a：註冊表 ──────────────────────────────────────────────────────────
def test_registry_texts_are_frozen():
    assert sorted(PS.SCRIPTS) == sorted(FROZEN)
    for name, tag in PS.SCRIPTS.items():
        assert tag.startswith("<script>") and tag.endswith("</script>")
        assert hashlib.sha256(PS.inner_text(tag).encode()).hexdigest() == FROZEN[name], name


def test_hash_expression_and_allowed_list():
    import base64
    h = PS.hash_of("x")
    assert h == "'sha256-%s'" % base64.b64encode(hashlib.sha256(b"x").digest()).decode()
    allowed = PS.allowed_hashes()
    assert len(allowed) == 4 and len(set(allowed)) == 4
    assert set(allowed) == {PS.hash_of(PS.inner_text(t)) for t in PS.SCRIPTS.values()}


def test_csp_script_src_comes_from_the_registry_only_and_ignores_the_page():
    page = "<html><head></head><body><script>var evil=1;</script><script src='x.js'></script></body></html>"
    csp = ST._csp_for_html(page)
    assert csp.count("sha256-") == 4 and "script-src 'sha256-" in csp and "evil" not in csp
    assert csp == ST._csp_for_html("<html></html>"), "與頁面內容無關"
    assert "'unsafe-inline'" not in csp.split("script-src")[1]


def test_builders_use_the_registry_constants():
    from helpers import doc_template as DT
    assert DT._FIT_A4_SCRIPT == PS.FIT_A4_SINGLE and DT._PAYSLIP_SCRIPT == PS.PAYSLIP
    src = (BACKEND / "modules/netplan/export.py").read_text(encoding="utf-8")
    assert "_PS.NETPLAN_FIT" in src
    pg = (BACKEND / "pdf_gen.py").read_text(encoding="utf-8")
    assert pg.count("_PS.FIT_A4_MULTI") == 2 and pg.count("_PS.FIT_A4_SINGLE") == 2
    assert "_PS.FIT_A4_MULTI" in (BACKEND / "modules/case/completion_pdf.py").read_text(encoding="utf-8")


def _docstring_ids(tree):
    ids = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body and isinstance(n.body[0], ast.Expr) \
                and isinstance(n.body[0].value, ast.Constant) and isinstance(n.body[0].value.value, str):
            ids.add(id(n.body[0].value))
    return ids


def test_no_builder_file_embeds_an_unregistered_script_literal():
    """新增內嵌腳本必須先登記到 helpers/pdf_scripts.py；預覽專用腳本（不經 Edge）是唯一例外。"""
    bad = []
    for rel in BUILDER_FILES:
        tree = ast.parse((BACKEND / rel).read_text(encoding="utf-8"))
        docs = _docstring_ids(tree)
        for n in ast.walk(tree):
            if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and re.search(r"<script", n.value, re.I):
                if PREVIEW_MARK in n.value and rel == "pdf_gen.py":
                    continue
                bad.append("%s:%d" % (rel, n.lineno))
    assert bad == [], "未登記的 <script 字面值：%s" % bad


def test_the_preview_script_is_never_part_of_an_edge_page():
    """預覽腳本只在 build_quote_preview_html 加上（給瀏覽器 iframe 用）；PDF 路徑的 _build_quote_html 不含它。"""
    src = (BACKEND / "pdf_gen.py").read_text(encoding="utf-8")
    pre = src[src.index("def build_quote_preview_html"):]
    pre = pre[:pre.index("\ndef ", 10)]
    assert PREVIEW_MARK in pre
    core = src[src.index("def _build_quote_html"):src.index("def build_quote_preview_html")]
    assert PREVIEW_MARK not in core


# ── H2-a：旗標 ────────────────────────────────────────────────────────────
def test_proxy_flags_are_part_of_the_hardening_flags():
    assert "--proxy-server=http://127.0.0.1:9" in ST._HARDEN_FLAGS and "--proxy-bypass-list=<-loopback>" in ST._HARDEN_FLAGS
    assert "--no-sandbox" not in ST._HARDEN_FLAGS, "本輪不動 --no-sandbox"
    cmd = ["edge", "--headless", "--no-sandbox", "file:///x.html"]
    out = ST._harden_cmd(cmd)
    assert out[-1] == "file:///x.html" and out[:3] == cmd[:3] and set(ST._HARDEN_FLAGS) <= set(out)


# ── H2-b：標籤中和 ────────────────────────────────────────────────────────
N = ST._neutralize_html


def _doc(body):
    return "<!DOCTYPE html><html><head><meta charset=\"UTF-8\"><style>p{color:red}</style></head><body>%s</body></html>" % body


@pytest.mark.parametrize("danger", [
    '<meta http-equiv="refresh" content="0;url=file:///C:/Windows/win.ini">',
    "<META HTTP-EQUIV=refresh CONTENT='0; URL=http://10.0.0.5/'>",
    '<meta http-equiv="Content-Security-Policy" content="default-src *">',
    '<base href="file:///C:/">',
    '<link rel="stylesheet" href="file:///C:/x.css">',
    '<iframe src="file:///C:/Windows/win.ini"></iframe>',
    "<IFRAME SRC=file:///C:/Windows/win.ini></IFRAME>",
    '<iframe/src="file:///C:/Windows/win.ini">',
    '<object data="file:///C:/Windows/win.ini"></object>',
    '<embed src="file:///C:/Windows/win.ini">',
    '<frameset><frame src="file:///C:/Windows/win.ini"></frameset>',
    '<applet code="x"></applet>',
])
def test_dangerous_tags_are_removed(danger):
    out = N(_doc("<p>前</p>%s<p>後</p>" % danger))
    low = out.lower()
    for bad in ("<iframe", "<frame", "<object", "<embed", "<applet", "<base", "<link", "http-equiv", "win.ini\">", "refresh"):
        assert bad not in low.replace("</iframe>", "").replace("</object>", "").replace("</frameset>", "").replace("</applet>", ""), (bad, out)
    assert "<p>前</p>" in out and "<p>後</p>" in out and "<style>p{color:red}</style>" in out


@pytest.mark.parametrize("tag,expect", [
    ('<p onclick="alert(1)">x</p>', "<p>x</p>"),
    ("<p ONCLICK = 'alert(1)' class=a>x</p>", "<p class=a>x</p>"),
    ("<p onmouseover=alert(1)>x</p>", "<p>x</p>"),
    ('<img src="a.png" onerror="fetch(1)" width=5>', '<img src="a.png" width=5>'),
    ('<a href="javascript:alert(1)">x</a>', "<a>x</a>"),
    ('<a href=" JaVa\tScript:alert(1)">x</a>', "<a>x</a>"),
    ('<a href="java&#x73;cript:alert(1)">x</a>', "<a>x</a>"),
    ('<a href="data:text/html;base64,AAAA">x</a>', "<a>x</a>"),
    ('<p srcdoc="<b>x</b>">x</p>', "<p>x</p>"),
    ('<form formaction="http://x/">x</form>', "<form>x</form>"),
])
def test_dangerous_attributes_are_removed_and_the_rest_of_the_tag_is_kept(tag, expect):
    assert N(tag) == expect


def test_unregistered_scripts_are_removed_and_registered_ones_kept():
    reg = PS.FIT_A4_MULTI
    out = N(_doc("<p>a</p><script>alert(1)</script><p>b</p>" + reg + "<script src='http://x/y.js'></script><script type='x'>zzz</script>"))
    assert "alert(1)" not in out and "y.js" not in out and "zzz" not in out
    assert reg in out and "<p>a</p><p>b</p>" in out
    assert N("<p>x</p><script>never closed(); </p>") == "<p>x</p>", "沒有結尾標籤的 script：到文件結尾都拿掉"
    assert N("<script   >x</script   ><p>y</p>") == "<p>y</p>"
    assert N("<script/>") == ""


def test_plain_text_and_legitimate_markup_are_untouched_byte_for_byte():
    html = _doc('<div class="a" style="color:red;background:url(data:image/png;base64,AAAA)"><p>javascript: 這只是文字 on=1 http-equiv=refresh &lt;iframe&gt;</p>'
                '<img src="data:image/png;base64,AAAA" alt="x"><table><tr><td colspan=2>1</td></tr></table><svg><g onclick-x="1"/></svg></div>' + PS.PAYSLIP + "\n")
    out = N(html)
    # onclick-x 以 on 開頭，會被當成事件屬性拿掉（保守）；其餘逐位元不變
    assert out == html.replace(' onclick-x="1"', "")
    assert N(_doc("<p>你好</p>")) == _doc("<p>你好</p>")


def test_normal_builder_outputs_are_not_changed_by_the_neutralizer():
    import pdf_gen
    import modules.case.completion_pdf as cp
    tot = {"subtotal": 200, "pretax": 200, "tax": 10, "total": 210}
    q = {"quoteNo": "MQ-202610-001", "customerName": "甲公司", "projectName": "專案", "status": "草稿", "validDays": 30,
         "items": [{"description": "品項", "brand": "", "unit": "式", "qty": 2, "unitPrice": 100, "amount": 200, "type": "item", "cost": 50, "margin": 10}]}
    pages = [pdf_gen._build_quote_html(q, tot), pdf_gen._build_quote_html(q, tot, internal=True),
             pdf_gen._build_shipping_html({"noteNo": "DN-202610-001", "status": "已核准", "customerName": "甲", "items": [{"description": "品", "qty": 3, "unit": "台"}]}),
             pdf_gen._build_payment_request_html({"requestNo": "PR-202610-001", "status": "已核准"}),
             cp._build_completion_html({"noteNo": "CN-202610-001", "status": "已核准"}),
             pdf_gen._build_payslip_html({"companyName": "測試股份有限公司", "companyTaxId": "11111111", "companyContactInfo": "04-1111-1111"})]
    for html in pages:
        assert N(html) == html, "中和器不能動到正常文件"
        assert ST._residual_danger(html) is None


# ── H2-b：殘留檢查與檔案層 ────────────────────────────────────────────────
def test_residual_check_flags_what_the_parser_could_have_missed_and_masks_registered_scripts():
    assert ST._residual_danger("<p>x</p>" + PS.NETPLAN_FIT) is None
    for bad in ("<iframe src=x>", "<  object data=x>", "<embed src=x>", "<base href=x>", "<link rel=x>", '<meta http-equiv="refresh" content="0">', "<script>x</script>"):
        assert ST._residual_danger("<p>x</p>" + bad), bad
    assert ST._residual_danger("文字 javascript: iframe link base") is None, "只看標籤，不看一般文字"


_M1_PAYLOADS = [
    '<!-- --!><meta foo=">" http-equiv=refresh content="0;url=file:///C:/Windows/win.ini"> -->',
    '<![CDATA[ x > <meta foo=">" http-equiv=refresh content="0;url=file:///C:/Windows/win.ini"> ]]>',
    '<svg><style><meta foo=">" http-equiv=refresh content="0;url=file:///C:/Windows/win.ini"></style></svg>',
]


@pytest.mark.parametrize("payload", _M1_PAYLOADS)
def test_residual_check_does_not_depend_on_tag_boundaries_for_http_equiv(payload, tmp_path):
    neutral = ST._neutralize_html(_doc(payload))
    assert ("http-equiv" not in neutral.lower()) or ST._residual_danger(neutral), "要嘛中和掉，要嘛殘留檢查攔下"
    f, cmd = _page(tmp_path, _doc(payload))
    with pytest.raises(ValueError):                             # 輸入含 http-equiv ⇒ 一律拒絕，與解析器版本無關
        ST._harden_html_file(cmd)
    assert "motrix-csp" not in f.read_text(encoding="utf-8")


def test_slash_separated_attributes_are_scrubbed():
    out = ST._neutralize_html("<img/onerror=alert(1) alt=a><svg/onload=alert(1)>")
    assert "onerror" not in out and "onload" not in out and "alt=a" in out


def _page(tmp_path, html, name="a.html"):
    f = tmp_path / name
    f.write_text(html, encoding="utf-8")
    return f, ["edge", "--print-to-pdf=x.pdf", "file:///" + str(f).replace("\\", "/")]


def test_harden_file_neutralizes_then_injects_our_csp(tmp_path):
    f, cmd = _page(tmp_path, _doc('<iframe src="file:///C:/Windows/win.ini"></iframe><img src=x onerror=evil()><p>x</p><script>evil()</script>' + PS.FIT_A4_SINGLE))
    ST._harden_html_file(cmd)
    out = f.read_text(encoding="utf-8")
    assert "<iframe" not in out and "onerror" not in out and "evil()" not in out and PS.FIT_A4_SINGLE in out and out.count('id="motrix-csp"') == 1
    assert "<p>x</p>" in out
    ST._harden_html_file(cmd)                                   # r3：重複硬化同一個檔案不會被自己上一次寫的 CSP meta 擋下；結果不變、CSP 仍只有一份
    assert f.read_text(encoding="utf-8") == out


def test_meta_refresh_in_the_input_is_refused_and_the_file_is_untouched(tmp_path):
    """r3：輸入含 http-equiv（meta refresh 等）一律拒絕渲染，不是中和後繼續（解析器差異下中和不可靠）。"""
    html = _doc('<meta http-equiv="refresh" content="0;url=file:///C:/Windows/win.ini"><p>x</p>')
    f, cmd = _page(tmp_path, html)
    with pytest.raises(ValueError):
        ST._harden_html_file(cmd)
    assert f.read_text(encoding="utf-8") == html


def test_a_foreign_csp_meta_is_not_mistaken_for_ours(tmp_path):
    """冪等只認逐字相同的我們自己的 meta；長得像但內容不同（例如放寬的政策）仍被拒絕。"""
    fake = ST._csp_meta().replace("default-src 'none'", "default-src *")
    f, cmd = _page(tmp_path, _doc(fake + "<p>x</p>"))
    with pytest.raises(ValueError):
        ST._harden_html_file(cmd)


def test_harden_file_refuses_to_render_when_a_dangerous_tag_survives_neutralization(tmp_path, monkeypatch):
    f, cmd = _page(tmp_path, _doc("<p>x</p>"))
    monkeypatch.setattr(ST, "_neutralize_html", lambda h: h + "<iframe src=x>")       # 模擬解析器差異：中和漏掉
    with pytest.raises(ValueError):
        ST._harden_html_file(cmd)
    assert "motrix-csp" not in f.read_text(encoding="utf-8"), "拒絕時不改檔"


@pytest.mark.parametrize("name", ["a#b.html", "q?x.html"])
def test_a_path_with_hash_or_question_mark_is_refused(tmp_path, name):
    cmd = ["edge", "--print-to-pdf=x.pdf", "file:///" + str(tmp_path / name).replace("\\", "/")]
    with pytest.raises(ValueError):
        ST._harden_html_file(cmd)


def test_missing_html_logs_a_warning_and_is_skipped(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="helpers.startup")
    ST._harden_html_file(["edge", "file:///" + str(tmp_path / "nope.html").replace("\\", "/")])
    assert any("不存在" in r.getMessage() for r in caplog.records)


def test_one_shared_html_argument_selector_and_non_html_file_urls_are_logged(tmp_path, caplog):
    caplog.set_level(logging.WARNING, logger="helpers.startup")
    assert ST._html_arg_index(["edge", "--x", "file:///C:/a.html"]) == 2
    assert ST._html_arg_index(["edge", "file:///C:/a.HTM?x=1#y"]) == 1
    assert ST._html_arg_index(["edge", "--version"]) is None
    assert ST._html_arg_index(["edge", "file:///C:/a.txt"]) is None
    assert any("不是 .html" in r.getMessage() for r in caplog.records)
    assert ST._harden_cmd(["edge", "file:///C:/a.txt"]) == ["edge", "file:///C:/a.txt"]
    import inspect
    assert "_html_arg_index(" in inspect.getsource(ST._harden_cmd) and "_html_arg_index(" in inspect.getsource(ST._harden_html_file), "兩處共用同一個選擇函式"


# ── 真的渲染（需要 Edge；與 H1 的對照組做法相同）──────────────────────────────
def _edge():
    try:
        from helpers import _get_edge_path
        p = _get_edge_path()
    except Exception:                                      # noqa: BLE001
        p = None
    if not p or not os.path.exists(p):
        pytest.skip("這台機器沒有 Edge")
    return p


@pytest.fixture(autouse=True)
def _isolated_edge_profile_state(monkeypatch, tmp_path_factory):
    monkeypatch.setattr(ST, "_EDGE_PROFILE_ROOT", str(tmp_path_factory.mktemp("h2_edge_profiles")))
    monkeypatch.setattr(ST, "_EDGE_PROFILE_POOL", [])
    monkeypatch.setattr(ST, "_EDGE_PROFILE_STATE", {"init": False, "runs": 0})


def _listener(host="127.0.0.1"):
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        srv.bind((host, 0))
    except OSError:
        srv.close()
        pytest.skip("無法綁定 %s" % host)
    srv.listen(8)
    srv.settimeout(0.4)
    hits, stop = [], threading.Event()

    def loop():
        while not stop.is_set():
            try:
                c, _a = srv.accept()
            except (socket.timeout, OSError):
                continue
            try:
                c.settimeout(0.4)
                hits.append(c.recv(200))
                c.sendall(b"HTTP/1.1 204 No Content\r\nConnection: close\r\n\r\n")
            except OSError:
                pass
            finally:
                c.close()
    t = threading.Thread(target=loop, daemon=True)
    t.start()
    return srv, hits, stop, t


def _raw_render(html, tmp, name, flags=()):
    """對照／探針渲染：不經 run_edge_pdf（沒有中和、沒有 CSP），只帶指定旗標。"""
    edge = _edge()
    f = tmp / (name + ".html")
    out = tmp / (name + ".pdf")
    f.write_text(html, encoding="utf-8")
    cmd = [edge, "--user-data-dir=%s" % (tmp / ("p_" + name)), "--headless", "--disable-gpu", "--no-sandbox", "--print-to-pdf=%s" % out, "--no-pdf-header-footer"] + list(flags) + ["file:///" + str(f).replace("\\", "/")]
    subprocess.run(cmd, timeout=120, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return out.exists()


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.2"])
def test_proxy_flags_stop_navigation_to_a_literal_ip(host, tmp_path):
    """直接寫 IP 的導航（meta refresh）：沒有代理旗標 ⇒ 連得到（對照組）；帶代理旗標 ⇒ 0 次連線。
    注意：這一題只測旗標本身（不經中和／CSP）；在受管機器上群組原則可能覆蓋代理設定，正式機要再驗一次。"""
    srv, hits, stop, t = _listener(host)
    try:
        port = srv.getsockname()[1]
        html = ('<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="0;url=http://%s:%d/nav"></head><body>x</body></html>' % (host, port))
        _raw_render(html, tmp_path, "ctl", flags=[])
        control = len(hits)
        del hits[:]
        _raw_render(html, tmp_path, "prx", flags=[f for f in ST._HARDEN_FLAGS if f.startswith("--proxy")])
        assert control >= 1, "對照組沒有連線——這台機器無法證明代理旗標有效"
        assert len(hits) == 0, "帶了代理旗標仍連到 %s：%r" % (host, hits[:2])
    finally:
        stop.set()
        t.join(2)
        srv.close()


def test_full_pipeline_removes_navigation_and_unregistered_scripts(tmp_path):
    """整條產品管線（run_edge_pdf）：meta refresh、注入的腳本、iframe 都不會生效；對照組（原始渲染）會。"""
    pytest.importorskip("pypdf")
    import io
    import pypdf
    srv, hits, stop, t = _listener()
    try:
        port = srv.getsockname()[1]
        body = ('<h2>MARK-OK</h2><script>document.write("INJECTED-RAN")</script>'
                '<iframe src="http://127.0.0.1:%d/frame"></iframe><img src="http://127.0.0.1:%d/i.png">' % (port, port))
        html = '<!DOCTYPE html><html><head><meta charset="UTF-8"><meta http-equiv="refresh" content="3;url=http://127.0.0.1:%d/nav"></head><body>%s</body></html>' % (port, body)
        _raw_render(html, tmp_path, "ctl")
        ctl_text = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(str(tmp_path / "ctl.pdf")).pages)
        control_hits = len(hits)
        del hits[:]
        f = tmp_path / "hard.html"
        out = tmp_path / "hard.pdf"
        # r3：輸入含 meta refresh 的頁面整份被拒絕（不產出、不連線）；其餘危險內容（腳本、iframe、外部圖片）的中和用不含 http-equiv 的頁面驗
        refused = tmp_path / "refused.html"
        refused.write_text(html, encoding="utf-8")
        ST.run_edge_pdf([_edge(), "--headless", "--disable-gpu", "--no-sandbox", "--print-to-pdf=%s" % (tmp_path / "refused.pdf"), "--no-pdf-header-footer", "file:///" + str(refused).replace("\\", "/")])
        assert not (tmp_path / "refused.pdf").exists() and len(hits) == 0, "含 http-equiv 的輸入必須不渲染、不連線"
        html = html.replace('<meta http-equiv="refresh" content="3;url=http://127.0.0.1:%d/nav">' % port, "")
        assert "http-equiv" not in html
        f.write_text(html, encoding="utf-8")
        ST.run_edge_pdf([_edge(), "--headless", "--disable-gpu", "--no-sandbox", "--print-to-pdf=%s" % out, "--no-pdf-header-footer", "file:///" + str(f).replace("\\", "/")])
        text = "\n".join((p.extract_text() or "") for p in pypdf.PdfReader(io.BytesIO(out.read_bytes())).pages)
        assert "INJECTED-RAN" in ctl_text and control_hits >= 1, "對照組沒有重現（無法證明硬化有效）"
        assert "MARK-OK" in text and "INJECTED-RAN" not in text
        assert len(hits) == 0, "硬化後仍有連線：%r" % hits[:2]
    finally:
        stop.set()
        t.join(2)
        srv.close()
