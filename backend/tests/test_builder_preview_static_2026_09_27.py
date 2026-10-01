"""模組建構器即時預覽的靜態守門（BUILDER-UX §3.2／§3.3；A）。

- 預覽旗標 `window.MOTRIX_PREVIEW` 只准 custom-records.html 的預覽掛鉤設定（而且只在 ?preview=1 時）；
  其他頁從不設定 ⇒ 共用腳本的「預覽就讓位」對其他頁沒有作用（非預覽模式行為不變）。
- 共用腳本 auth-guard／notif／sidebar 看到旗標就不執行（預覽不打 API 的第一道）。
- form-preview.js 不自己畫欄位（沒有第二套渲染會漂移）：表單一律由執行頁的模板畫。
"""
import re
from pathlib import Path

FRONT = Path(__file__).resolve().parents[2] / "frontend"
FLAG_SET = re.compile(r"MOTRIX_PREVIEW\s*=\s*true")


def _front_files():
    return [p for p in FRONT.rglob("*") if p.suffix in (".html", ".js") and "vendor" not in p.parts]


def flag_setters(files):
    return sorted(p.relative_to(FRONT).as_posix() for p in files if FLAG_SET.search(p.read_text(encoding="utf-8")))


def test_only_the_runtime_page_sets_the_preview_flag():
    assert flag_setters(_front_files()) == ["pages/custom-records.html"]
    from core import source_tree
    src = source_tree.page_file("custom-records.html").read_text(encoding="utf-8")
    i = src.index("window.MOTRIX_PREVIEW = true")
    guard = src[max(0, i - 400):i]
    assert "get('preview') === '1'" in guard and "if (!on) return" in guard, "旗標只能在 ?preview=1 時設定"
    assert src.index("window.MOTRIX_PREVIEW = true") < src.index('src="../static/auth-guard.js"'), "旗標要在 auth-guard 之前設好"


#: 預覽時共用腳本要讓位：`if (window.MOTRIX_PREVIEW) return`；允許再 OR 上嵌入旗標（`|| window.MOTRIX_EMBED`，方案 B 的嵌入頁也讓位），
#: 但一定要有 PREVIEW 這個條件（不能只剩 EMBED，否則建構器預覽會載入通知／側欄）。
STAND_DOWN = re.compile(r"if \(window\.MOTRIX_PREVIEW(?: \|\| window\.MOTRIX_EMBED)?\) return")


def test_shared_scripts_stand_down_in_preview():
    for rel in ("static/auth-guard.js", "static/notif.js", "static/sidebar.js"):
        src = (FRONT / rel).read_text(encoding="utf-8")
        assert STAND_DOWN.search(src), rel


def test_stand_down_reverse_controls():
    assert STAND_DOWN.search("if (window.MOTRIX_PREVIEW) return;")                                    # 正對照：舊寫法
    assert STAND_DOWN.search("if (window.MOTRIX_PREVIEW || window.MOTRIX_EMBED) return   // x")        # 正對照：加嵌入旗標
    assert not STAND_DOWN.search("var a = 1")                                                          # 沒有讓位
    assert not STAND_DOWN.search("if (window.MOTRIX_EMBED) return")                                    # 只剩 EMBED：預覽沒讓位
    assert not STAND_DOWN.search("if (window.MOTRIX_EMBED || window.MOTRIX_PREVIEW) return")           # 條件順序不同＝沒被明確釘住，要改就要連同測試


def test_the_page_refuses_api_calls_through_one_flag():
    from core import source_tree
    src = source_tree.page_file("custom-records.html").read_text(encoding="utf-8")
    for fn in ("async api(", "async post(", "async put("):
        i = src.index(fn)
        assert "this._noApiInPreview()" in src[i:i + 120], fn
    assert "if (this.preview) return this._initPreview()" in src
    assert "if (this.preview) return            // 預覽模式：存檔無效" in src


def test_form_preview_does_not_render_fields_itself():
    src = (FRONT / "static" / "form-preview.js").read_text(encoding="utf-8")
    for needle in ("type=\"date\"", "type=\"number\"", "cr-f", "createElement('input')", "createElement('select')", "x-model"):
        assert needle not in src, "form-preview.js 不可以自己畫欄位（%s）——表單由執行頁的模板畫" % needle
    assert "/pages/custom-records.html" in src and "?preview=1" in src


def test_reverse_control_flag_scanner():
    """反向控制：另一個檔也設旗標 ⇒ 掃得到。"""
    import tempfile
    d = Path(tempfile.mkdtemp())
    try:
        a, b = d / "a.html", d / "b.js"
        a.write_text("<script>window.MOTRIX_PREVIEW = true</script>", encoding="utf-8")
        b.write_text("var x = 1", encoding="utf-8")
        got = [Path(p).name for p in (a, b) if FLAG_SET.search(Path(p).read_text(encoding="utf-8"))]
        assert got == ["a.html"]
    finally:
        for p in d.iterdir():
            p.unlink()
        d.rmdir()
