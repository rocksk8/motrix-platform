"""網路拓樸圖：依規劃書「設備清單」（category=交換器 者）＋「交換器 Port 對應」
明細，即時產生 switch faceplate 樣式的視覺化拓樸 SVG，供表單分頁預覽與 PDF 匯出
內嵌。

沿用使用者原本個案腳本（B1F 拓樸圖產生器）的繪圖手法一般化而來：不再是寫死的
Python EDIT ZONE，改成直接讀 network_plans 的 data_json（devices／switchPorts）
——使用者只要在既有表格填「型號規格」「連接對象」等文字欄位，圖就會跟著變，
不用另外維護一份腳本。

埠位顏色：依既有 portProfile 文字雜湊到固定調色盤（同 profile 同色，不用另外
挑色欄位）；交換器之間／外部上行的連線一律用琥珀色（沿用原腳本 'up' 語意）。

防呆設計（2026-09-03 嚴謹複查後補強，見同輪對話）：
- 單一設備的埠數欄位打錯（非數字/負數）只會跳過該台交換器，不會讓整份拓樸圖
  全部畫不出來（原第一版是整批 int() 轉型，一台壞掉全部中止）。
- 埠數超過合理上限會自動限制並回警告，避免使用者手誤填超大數字產生巨型 SVG
  拖垮 PDF 轉檔（Edge headless 有 timeout）。
- 埠號超出該交換器實際埠數、設備名稱重複、Port 對應表填的設備名稱在設備清單
  找不到、linkDevice 疑似只有大小寫/空白打錯導致沒配對到既有交換器——這四種
  情況都不會讓圖壞掉或悄悄漏資料，而是回傳 warnings 清單給呼叫端顯示提醒。
- 面板/外部方塊/連線標籤的文字一律做長度保護（截斷+SVG <title> 完整文字提示），
  避免使用者填的中文自由文字把儲存格撐爆或超出畫布邊界。
"""
import re

CW, CH = 54, 40
COLGAP, ROWGAP = 6, 8
GROUPGAP = 16
SFPGAP = 24
PLATE_H, PAD = 28, 14
SPARE = "#334155"
UPLINK_COLOR = "#f59e0b"
USED_NO_PROFILE = "#2563eb"
FONT = "'Microsoft JhengHei','Noto Sans TC',system-ui,sans-serif"
MONO = "Consolas,'Courier New',monospace"

# 上限純粹是防呆（擋手誤輸入的超大數字），不是實體規格限制。
MAX_COPPER = 96
MAX_SFP = 32
PORT_LABEL_MAX = 6
TITLE_MAX = 40
EXT_LABEL_MAX = 16

_PALETTE = ["#2563eb", "#0d9488", "#7c3aed", "#db2777", "#16a34a",
            "#0891b2", "#dc2626", "#6366f1", "#ca8a04", "#059669"]


def _esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


def _truncate(s, n):
    s = str(s)
    return s if len(s) <= n else s[:max(n - 1, 1)] + "…"


def _profile_color(profile):
    if not profile:
        return None
    h = sum(ord(c) for c in profile)
    return _PALETTE[h % len(_PALETTE)]


def _port_num(raw):
    if raw is None:
        return None
    m = re.search(r"\d+", str(raw))
    return int(m.group()) if m else None


def _copper_cols(copper):
    return (max(copper, 1) + 1) // 2


def _copper_col_x(ox, c, half):
    extra = GROUPGAP if c >= half else 0
    return ox + c * (CW + COLGAP) + extra


def _geom_of(copper, sfp_n):
    cols = _copper_cols(copper)
    half = (cols + 1) // 2
    copper_w = _copper_col_x(0, cols - 1, half) + CW
    sfp_w = (sfp_n * CW + max(0, sfp_n - 1) * COLGAP) if sfp_n else CW
    body_w = PAD + max(copper_w, sfp_w) + PAD
    ports_y = PLATE_H + 14
    sfp_y = ports_y + CH * 2 + ROWGAP + SFPGAP
    body_h = sfp_y + CH + 14
    return dict(cols=cols, half=half, copper_w=copper_w, sfp_w=sfp_w,
                body_w=body_w, ports_y=ports_y, sfp_y=sfp_y, body_h=body_h)


def _port_cell_style(port):
    if not port or not port.get("label"):
        return SPARE, "#94a3b8", "#64748b"
    if port.get("uplink"):
        return UPLINK_COLOR, "#3b2600", "rgba(255,255,255,.85)"
    c = _profile_color(port.get("profile"))
    if c:
        return c, "#fff", "rgba(255,255,255,.85)"
    return USED_NO_PROFILE, "#fff", "rgba(255,255,255,.85)"


def _cell(px, py, label_no, port):
    fill, name_c, num_c = _port_cell_style(port)
    full_label = port.get("label") if port else None
    shown = _truncate(full_label, PORT_LABEL_MAX) if full_label else "—"
    fs = 12 if (shown != "—" and len(shown) > 3) else 13.5
    title_tag = f'<title>{_esc(full_label)}</title>' if full_label and full_label != shown else ''
    return (
        f'<g>{title_tag}'
        f'<rect x="{px}" y="{py}" rx="6" width="{CW}" height="{CH}" fill="{fill}" '
        f'stroke="#0f172a" stroke-width="1.4"/>'
        f'<text x="{px+5}" y="{py+12}" fill="{num_c}" font-family="{MONO}" '
        f'font-size="9.5" font-weight="700">{label_no}</text>'
        f'<text x="{px+CW/2}" y="{py+CH-9}" text-anchor="middle" fill="{name_c}" '
        f'font-family="{FONT}" font-size="{fs}" font-weight="700">{_esc(shown)}</text>'
        f'</g>'
    )


def _render_faceplate(x, y, sw):
    copper, sfp_n = sw["copper"], sw["sfp"]
    g = _geom_of(copper, sfp_n)
    half = g["half"]
    ox, oy = x + PAD, y + g["ports_y"]
    ports = sw["ports"]
    s = ["<g>"]
    s.append(f'<rect x="{x}" y="{y}" rx="12" width="{g["body_w"]}" height="{g["body_h"]}" '
             f'fill="#1f2937" stroke="#0f172a" stroke-width="2"/>')
    s.append(f'<rect x="{x+PAD}" y="{y+10}" rx="5" width="{g["body_w"]-2*PAD}" height="{PLATE_H-8}" fill="#0b1220"/>')
    s.append(f'<text x="{x+PAD+10}" y="{y+10+PLATE_H-13}" fill="#93c5fd" '
             f'font-family="{MONO}" font-size="12.5" font-weight="700">{_esc(sw["title"])}</text>')

    for c in range(g["cols"]):
        px = _copper_col_x(ox, c, half)
        p_top, p_bot = 2 * c + 1, 2 * c + 2
        if p_top <= copper:
            s.append(_cell(px, oy, p_top, ports.get(("cu", p_top))))
        if p_bot <= copper:
            s.append(_cell(px, oy + CH + ROWGAP, p_bot, ports.get(("cu", p_bot))))

    sfp_y = y + g["sfp_y"]
    sfp_x0 = ox + (g["copper_w"] - g["sfp_w"]) / 2 if copper else ox
    if sfp_n:
        s.append(f'<text x="{sfp_x0}" y="{sfp_y-8}" fill="#64748b" font-family="{MONO}" font-size="9">'
                 f'SFP {copper+1}-{copper+sfp_n}</text>')
        for i in range(sfp_n):
            px = sfp_x0 + i * (CW + COLGAP)
            port = ports.get(("sfp", i + 1))
            if port and port.get("label"):
                s.append(_cell(px, sfp_y, f"SFP{i+1}", port))
            else:
                s.append(f'<rect x="{px}" y="{sfp_y}" rx="5" width="{CW}" height="{CH}" '
                          f'fill="#0b1220" stroke="#475569" stroke-width="1.4"/>')
                s.append(f'<text x="{px+CW/2}" y="{sfp_y+CH/2+4}" text-anchor="middle" fill="#94a3b8" '
                         f'font-family="{MONO}" font-size="11" font-weight="700">SFP{i+1}</text>')
    s.append("</g>")

    def port_xy(kind, n):
        if kind == "sfp":
            cx = sfp_x0 + (n - 1) * (CW + COLGAP) + CW / 2
            return dict(cx=cx, top=sfp_y, bot=sfp_y + CH)
        c = (n - 1) // 2
        r = (n - 1) % 2
        cx = _copper_col_x(ox, c, half) + CW / 2
        top = oy + r * (CH + ROWGAP)
        return dict(cx=cx, top=top, bot=top + CH)

    return "".join(s), dict(x=x, y=y, body_w=g["body_w"], body_h=g["body_h"],
                            center_y=y + g["body_h"] / 2, port_xy=port_xy)


def _cable(ax, ay, bx, by, color, label):
    mid = (ay + by) / 2
    s = [f'<path d="M {ax} {ay} C {ax} {mid}, {bx} {mid}, {bx} {by}" fill="none" '
         f'stroke="{color}" stroke-width="3.5" stroke-linecap="round"/>']
    s.append(f'<circle cx="{ax}" cy="{ay}" r="4.5" fill="{color}"/>'
              f'<circle cx="{bx}" cy="{by}" r="4.5" fill="{color}"/>')
    if label:
        lx, ly = (ax + bx) / 2, mid
        w = max(116, 16 + len(label) * 11)
        s.append(f'<rect x="{lx-w/2}" y="{ly-13}" rx="6" width="{w}" height="24" '
                  f'fill="#fff7ed" stroke="{color}" stroke-width="1.3"/>')
        s.append(f'<text x="{lx}" y="{ly+3}" text-anchor="middle" fill="#b45309" '
                 f'font-family="{MONO}" font-size="11.5" font-weight="700">{_esc(label)}</text>')
    return "".join(s)


def build_topology_svg(data: dict) -> dict:
    """data：規劃書 data_json（含 devices／switchPorts）。回傳
    {"html": SVG+圖例 HTML 片段 或 None, "warnings": [提醒文字, ...]}。
    html 為 None 代表沒有任何「交換器」類別設備可畫（呼叫端據此略過整段，
    不畫空圖），此時 warnings 恆為空清單。"""
    warnings = []
    devices = data.get("devices") or []
    switch_ports = data.get("switchPorts") or []
    switches_raw = [d for d in devices if (d.get("category") == "交換器") and (d.get("name") or "").strip()]
    if not switches_raw:
        return {"html": None, "warnings": []}

    switches = {}
    dup_names = set()
    for d in switches_raw:
        name = d["name"].strip()
        if name in switches:
            dup_names.add(name)
            continue  # 保留第一筆，重複的名稱略過（設備名稱是拓樸圖的對應鍵）
        try:
            copper = int(d.get("portsCopper") or 24)
            sfp_n = int(d.get("portsSfp") or 0)
        except (TypeError, ValueError):
            warnings.append(f"設備「{name}」的 RJ45／SFP 埠數格式不是數字，此交換器已略過繪製（其餘交換器不受影響）")
            continue
        if copper < 0 or sfp_n < 0:
            warnings.append(f"設備「{name}」的埠數不可為負數，此交換器已略過繪製")
            continue
        if copper > MAX_COPPER:
            warnings.append(f"設備「{name}」RJ45 埠數 {copper} 超過上限 {MAX_COPPER}，圖上已自動限制為 {MAX_COPPER}")
            copper = MAX_COPPER
        if sfp_n > MAX_SFP:
            warnings.append(f"設備「{name}」SFP 埠數 {sfp_n} 超過上限 {MAX_SFP}，圖上已自動限制為 {MAX_SFP}")
            sfp_n = MAX_SFP
        model = (d.get("model") or "").strip()
        loc = (d.get("location") or "").strip()
        poe = bool(d.get("poe"))
        title = name + (f"　{model}" if model else "") + (" ⚡PoE" if poe else "") + (f"　（{loc}）" if loc else "")
        switches[name] = dict(name=name, copper=copper, sfp=sfp_n, title=_truncate(title, TITLE_MAX), ports={})
    if dup_names:
        warnings.append("設備清單有重複名稱（拓樸圖只會畫第一筆，其餘略過）：" + "、".join(sorted(dup_names)))

    unmatched_devices = set()
    dropped_ports = []
    for row in switch_ports:
        dev = (row.get("device") or "").strip()
        if not dev:
            continue
        sw = switches.get(dev)
        if not sw:
            unmatched_devices.add(dev)
            continue
        n = _port_num(row.get("portNo"))
        if n is None:
            continue
        kind = "sfp" if (row.get("portMedia") == "SFP") else "cu"
        cap = sw["sfp"] if kind == "sfp" else sw["copper"]
        if n < 1 or n > cap:
            dropped_ports.append(f'{dev} {"SFP" if kind == "sfp" else "P"}{n}')
            continue
        label = (row.get("endpoint") or "").strip()
        if not label:
            continue
        sw["ports"][(kind, n)] = dict(
            label=label, profile=(row.get("portProfile") or "").strip(),
            uplink=bool((row.get("linkDevice") or "").strip()),
        )
    if unmatched_devices:
        warnings.append(
            "「交換器 Port 對應」裡以下設備名稱，在「設備清單」找不到對應的交換器"
            "（可能是打字誤植，或該設備類別不是「交換器」）：" + "、".join(sorted(unmatched_devices))
        )
    if dropped_ports:
        warnings.append("以下埠號超出該交換器實際埠數，已略過不畫在圖上：" + "、".join(sorted(dropped_ports)))

    # 連線：linkDevice 命中另一台已建模交換器＋linkPort 可解析 → 兩端都是真實面板埠；
    # 否則視為外部/未列出上行（畫成頂端小方塊）。同一台交換器對交換器的連線若兩端
    # 都各自填了一筆 linkDevice（互相參照），dedupe 只畫一條。
    switch_names_lower = {n.lower(): n for n in switches}
    typo_warned = set()
    cables_raw = []
    external_targets = []
    for row in switch_ports:
        src_dev = (row.get("device") or "").strip()
        link_to = (row.get("linkDevice") or "").strip()
        if not link_to or src_dev not in switches:
            continue
        src_n = _port_num(row.get("portNo"))
        if src_n is None:
            continue
        src_kind = "sfp" if (row.get("portMedia") == "SFP") else "cu"
        dst_sw = switches.get(link_to)
        if dst_sw:
            dst_n = _port_num(row.get("linkPort"))
            if dst_n is None:
                continue
            dst_kind = "sfp" if "sfp" in (row.get("linkPort") or "").lower() else "cu"
            dedupe_key = tuple(sorted([(src_dev, src_kind, src_n), (link_to, dst_kind, dst_n)]))
            cables_raw.append(dict(kind="device", dedupe=dedupe_key,
                                    a_dev=src_dev, a_kind=src_kind, a_n=src_n,
                                    b_dev=link_to, b_kind=dst_kind, b_n=dst_n))
        else:
            near = switch_names_lower.get(link_to.lower())
            if near and near != link_to and link_to not in typo_warned:
                typo_warned.add(link_to)
                warnings.append(
                    f'「{src_dev}」的連線對象「{link_to}」與交換器「{near}」僅大小寫/空白不同，'
                    f'未自動配對到該交換器（已畫成外部設備方塊）——若寫錯了請修正拼寫'
                )
            if link_to not in external_targets:
                external_targets.append(link_to)
            cables_raw.append(dict(kind="external", dedupe=None,
                                    a_dev=src_dev, a_kind=src_kind, a_n=src_n,
                                    ext_label=link_to))

    seen = set()
    cables = []
    for c in cables_raw:
        if c["kind"] == "device":
            if c["dedupe"] in seen:
                continue
            seen.add(c["dedupe"])
        cables.append(c)

    # ── layout：外部上行方塊（若有）置頂，交換器由上而下堆疊 ──
    X = 40
    ext_h = 46
    ext_gap = 20
    has_ext = bool(external_targets)
    y = (40 + ext_h + 60) if has_ext else 40
    geoms = {}
    svg_switches = []
    for name, sw in switches.items():
        piece, geo = _render_faceplate(X, y, sw)
        svg_switches.append(piece)
        geoms[name] = geo
        y = geo["y"] + geo["body_h"] + 70

    ext_svg = []
    ext_anchor = {}
    ext_right_edge = X
    if has_ext:
        ex = X
        for label in external_targets:
            shown = _truncate(label, EXT_LABEL_MAX)
            w = max(160, 20 + len(shown) * 15)
            title_tag = f'<title>{_esc(label)}</title>' if shown != label else ''
            ext_svg.append(
                f'<g>{title_tag}'
                f'<rect x="{ex}" y="40" rx="10" width="{w}" height="{ext_h}" '
                f'fill="#0b1220" stroke="{UPLINK_COLOR}" stroke-width="2"/>'
                f'<text x="{ex+14}" y="{40+19}" fill="#fbbf24" font-family="{FONT}" '
                f'font-size="12.5" font-weight="900">{_esc(shown)}</text>'
                f'<text x="{ex+14}" y="{40+37}" fill="#94a3b8" font-family="{MONO}" font-size="10">外部/未列出設備</text>'
                f'</g>'
            )
            ext_anchor[label] = dict(cx=ex + w / 2, top=40, bot=40 + ext_h, center_y=40)
            ex += w + ext_gap
        ext_right_edge = ex - ext_gap

    def endpoint_of(dev, kind, n):
        geo = geoms[dev]
        return geo["port_xy"](kind, n), geo["center_y"]

    def _port_label(dev, kind, n):
        return f'{dev} {"SFP" if kind == "sfp" else "P"}{n}'

    cable_svgs = []
    for c in cables:
        a, a_cy = endpoint_of(c["a_dev"], c["a_kind"], c["a_n"])
        if c["kind"] == "device":
            b, b_cy = endpoint_of(c["b_dev"], c["b_kind"], c["b_n"])
            label = f'{_port_label(c["a_dev"], c["a_kind"], c["a_n"])} ↔ {_port_label(c["b_dev"], c["b_kind"], c["b_n"])}'
        else:
            anchor = ext_anchor[c["ext_label"]]
            b, b_cy = anchor, anchor["center_y"]
            label = f'{_port_label(c["a_dev"], c["a_kind"], c["a_n"])} → {c["ext_label"]}'
        if a_cy <= b_cy:
            ax, ay, bx, by = a["cx"], a["top"], b["cx"], b["bot"]
        else:
            ax, ay, bx, by = a["cx"], a["bot"], b["cx"], b["top"]
        cable_svgs.append(_cable(ax, ay, bx, by, UPLINK_COLOR, label))

    width_candidates = [g["body_w"] for g in geoms.values()]
    if has_ext:
        width_candidates.append(ext_right_edge - X)
    total_w = X + max(width_candidates, default=300) + 30
    total_h = y + 20

    legend = [
        '<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
        f'<i style="width:14px;height:14px;border-radius:4px;background:{UPLINK_COLOR};display:inline-block"></i>交換器間／上行連線</span>'
    ]
    profiles_used = sorted({p["profile"] for sw in switches.values() for p in sw["ports"].values() if p.get("profile")})
    for p in profiles_used:
        legend.append(
            '<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
            f'<i style="width:14px;height:14px;border-radius:4px;background:{_profile_color(p)};display:inline-block"></i>{_esc(p)}</span>'
        )
    legend.append(
        '<span style="display:inline-flex;align-items:center;gap:6px;margin-right:16px">'
        f'<i style="width:14px;height:14px;border-radius:4px;background:{SPARE};display:inline-block"></i>未使用</span>'
    )

    if not switches:
        # 全部交換器都因格式錯誤被跳過（極端情況：唯一一台就寫錯埠數）
        return {"html": None, "warnings": warnings}

    svg = (f'<svg width="{total_w}" height="{total_h}" viewBox="0 0 {total_w} {total_h}" '
           f'xmlns="http://www.w3.org/2000/svg">'
           f'{"".join(ext_svg)}{"".join(cable_svgs)}{"".join(svg_switches)}</svg>')
    legend_html = f'<div style="display:flex;flex-wrap:wrap;margin-top:10px;font-size:12px;color:#475569">{"".join(legend)}</div>'
    return {"html": svg + legend_html, "warnings": warnings}


def build_topology_text_summary_html(data: dict) -> str:
    """純文字版「埠位對照表」（比照使用者原本個案腳本 b1f_topology.py 的表格
    區塊），每台交換器一張表，逐埠列出連接對象／Port Profile／拓樸圖連線對象。
    SVG 圖只能用「看」的，這裡補一份可搜尋/可讀的文字說明——供快速拓樸圖 PDF
    匯出使用（見 network_plan_export.py::build_topology_only_html），一律列出
    1..埠數的每一個埠（含未使用的 Spare），不因為排版考量省略任何埠。"""
    devices = data.get("devices") or []
    switch_ports = data.get("switchPorts") or []
    switches = [d for d in devices if (d.get("category") == "交換器") and (d.get("name") or "").strip()]
    if not switches:
        return ""

    rows_by_device = {}
    for row in switch_ports:
        dev = (row.get("device") or "").strip()
        if dev:
            rows_by_device.setdefault(dev, []).append(row)

    blocks = []
    seen_names = set()
    for d in switches:
        name = (d.get("name") or "").strip()
        if name in seen_names:
            continue  # 與 build_topology_svg 一致：重複名稱只取第一筆
        seen_names.add(name)
        try:
            copper = min(max(int(d.get("portsCopper") or 24), 0), MAX_COPPER)
            sfp_n = min(max(int(d.get("portsSfp") or 0), 0), MAX_SFP)
        except (TypeError, ValueError):
            continue

        by_key = {}
        for r in rows_by_device.get(name, []):
            n = _port_num(r.get("portNo"))
            if n is None:
                continue
            kind = "sfp" if r.get("portMedia") == "SFP" else "cu"
            by_key[(kind, n)] = r

        def _row_html(label_no, r):
            endpoint = _esc((r.get("endpoint") or "").strip()) if r else ""
            profile = _esc((r.get("portProfile") or "").strip()) if r else ""
            link = (r.get("linkDevice") or "").strip() if r else ""
            link_port = (r.get("linkPort") or "").strip() if r else ""
            link_text = _esc(f"{link}" + (f" P{link_port}" if link_port else "")) if link else ""
            target = endpoint or "<span style=\"color:#9CA3AF\">Spare（未使用）</span>"
            return (f"<tr><td>{label_no}</td><td>{target}</td>"
                    f"<td>{profile}</td><td>{link_text}</td></tr>")

        trs = []
        for n in range(1, copper + 1):
            trs.append(_row_html(f"P{n}", by_key.get(("cu", n))))
        for n in range(1, sfp_n + 1):
            trs.append(_row_html(f"SFP{n}", by_key.get(("sfp", n))))

        model = (d.get("model") or "").strip()
        loc = (d.get("location") or "").strip()
        cap_bits = [name]
        if model:
            cap_bits.append(model)
        if loc:
            cap_bits.append(loc)
        caption = "　".join(cap_bits) + f"（使用中 {len(rows_by_device.get(name, []))} / {copper + sfp_n} 埠）"

        blocks.append(
            f'<div class="section-label">{_esc(caption)}</div>'
            '<table><thead><tr><th>埠號</th><th>連接對象／端點</th>'
            '<th>Port Profile</th><th>拓樸圖連線對象</th></tr></thead>'
            f'<tbody>{"".join(trs)}</tbody></table>'
        )
    return "".join(blocks)
