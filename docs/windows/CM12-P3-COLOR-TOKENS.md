# CM12 P3：案件頁色碼 → 語意 token 對照表（2026-09-24，hichan-8d → hichan-a3）

來源：`frontend/pages/case-management.html`＋`frontend/js/case-management.js` 寫死的色碼，共 **104 種、767 處**（`#fff` 與 `#ffffff` 視為同一種；rgba 依用途歸類）。
token 定義在 `frontend/css/style.css` 最後一段「語意色彩 token」（**只新增**，既有規則沒有改動），每個 token 的註解列出它收了哪些原色碼。

## 套用時要注意

1. **深色模式目前是整頁 filter 反轉**：`style.css`「DARK MODE」區塊對 `body > *` 做 `invert(1) hue-rotate(180deg)`。`:root[data-theme="dark"]` 這組 token 值，是給「**不**經過反轉」的頁面用的。P3 若讓案件頁改讀 token，**必須同時把案件頁移出那道反轉**，否則深色值會被再反轉一次、變回淺色。反過來，若不移出反轉，就不要讓案件頁吃深色組（留淺色值，交給反轉處理）。
2. **合併了的顏色會改變外觀**：
   - `#dc2626` 收進 `--tone-danger-fg`（`#b91c1c`），因為 `#dc2626` 對站內主底色只有 4.39:1，不到 AA。
   - 同一族的幾個深淺（例如琥珀文字 `#92400e／#b45309／#a16207／#854d0e`）收成一個值。
   - 套用後要看一次畫面；需要保留層次的地方可以再開 `-strong` 變體，不要回頭寫死色碼。
3. `--ink-muted`（`#9ca3af`）對白底只有約 2.5:1，只可以用在 placeholder、停用狀態這類非必要文字。
4. 已有同義 token 的沿用既有的：`#a60d26` → `--accent-hover`、`#767676` → `--text-dim`、`#f5f4f0` → 收進 `--surface-sunken`（等於 `--white`）。
5. `style.css` 被引用時帶的是 `?v=20260805g`。第一次讓案件頁用到新 token 時，要一併 bump 這個版本，否則瀏覽器會拿到舊的快取、找不到 token。

## 字級

`backend/tests/test_cm12_p3_prep_2026_09_24.py` 的字級守門題：案件頁（HTML 的 `<style>`＋行內 style）`font-size` 小於 11px 的現況是 **114 處**（10px 87、9px 15、10.5px 6、9.5px 5、8.5px 1），以 xfail(strict) 釘住。P3 套完之後那題會自動轉綠、strict 讓它變紅，屆時把 xfail 拿掉。另有一題棘輪：處數不可以再增加。

## 對照表（依 token 排序）

| 色碼 | 出現次數 | token |
|---|---:|---|
| `#9ca3af` | 8 | `--ink-muted` |
| `#6b7280` | 8 | `--ink-secondary` |
| `#57534e` | 1 | `--ink-secondary` |
| `#64748b` | 1 | `--ink-secondary` |
| `#374151` | 5 | `--ink-strong` |
| `#000000` | 2 | `--ink-strong` |
| `#1a1d21` | 1 | `--ink-strong` |
| `#e5e7eb` | 21 | `--line` |
| `#e7e5e4` | 1 | `--line` |
| `#eeeeee` | 1 | `--line` |
| `#e5e3de` | 1 | `--line` |
| `#e5e3dd` | 1 | `--line` |
| `#d5d5d5` | 4 | `--line-strong` |
| `#d1d5db` | 2 | `--line-strong` |
| `#d9d7d2` | 1 | `--line-strong` |
| `#d1cfc9` | 1 | `--line-strong` |
| `#c9c7c1` | 1 | `--line-strong` |
| `rgba(0,0,0,.45)` | 12 | `--overlay-backdrop` |
| `rgba(0,0,0,.08)` | 4 | `--shadow-hairline` |
| `rgba(0,0,0,.04)` | 1 | `--shadow-hairline` |
| `rgba(0,0,0,.12)` | 1 | `--shadow-hairline` |
| `rgba(0,0,0,.10)` | 1 | `--shadow-hairline` |
| `rgba(0,0,0,.22)` | 13 | `--shadow-popover` |
| `rgba(0,0,0,.18)` | 2 | `--shadow-popover` |
| `#ffffff` | 148 | `--surface` |
| `#fafaf9` | 21 | `--surface-muted` |
| `#f9fafb` | 4 | `--surface-muted` |
| `#f5f5f4` | 2 | `--surface-muted` |
| `#fcfcfb` | 2 | `--surface-muted` |
| `#fafaf8` | 1 | `--surface-muted` |
| `#f7f6f3` | 1 | `--surface-muted` |
| `#f3f4f6` | 16 | `--surface-neutral` |
| `#f0eee9` | 18 | `--surface-sunken` |
| `#f0efeb` | 11 | `--surface-sunken` |
| `#f5f4f0` | 10 | `--surface-sunken` |
| `#eeecea` | 4 | `--surface-sunken` |
| `#767676` | 1 | `--text-dim` |
| `rgba(200,16,46,.10)` | 1 | `--tone-accent-bg` |
| `#a60d26` | 1 | `--tone-accent-bg` |
| `#fef2f2` | 15 | `--tone-danger-bg` |
| `#fff1f2` | 1 | `--tone-danger-bg` |
| `#fee2e2` | 7 | `--tone-danger-bg-strong` |
| `#fecaca` | 11 | `--tone-danger-border` |
| `#fca5a5` | 6 | `--tone-danger-border` |
| `#dc2626` | 34 | `--tone-danger-fg` |
| `#b91c1c` | 21 | `--tone-danger-fg` |
| `#eef2ff` | 6 | `--tone-info-bg` |
| `#dbeafe` | 5 | `--tone-info-bg` |
| `#e0f2fe` | 2 | `--tone-info-bg` |
| `rgba(37,99,235,.10)` | 1 | `--tone-info-bg` |
| `#e0eeff` | 1 | `--tone-info-bg` |
| `rgba(37,99,235,.08)` | 1 | `--tone-info-bg` |
| `#e0e7ff` | 1 | `--tone-info-bg` |
| `#eef6ff` | 1 | `--tone-info-bg` |
| `#93c5fd` | 8 | `--tone-info-border` |
| `#bfdbfe` | 6 | `--tone-info-border` |
| `#c7d2fe` | 4 | `--tone-info-border` |
| `#818cf8` | 1 | `--tone-info-border` |
| `#4338ca` | 4 | `--tone-info-fg` |
| `#2563eb` | 2 | `--tone-info-fg` |
| `#0891b2` | 2 | `--tone-info-fg` |
| `#0369a1` | 2 | `--tone-info-fg` |
| `#1d4ed8` | 1 | `--tone-info-fg` |
| `#fff7ed` | 1 | `--tone-orange-bg` |
| `#fdba74` | 1 | `--tone-orange-border` |
| `#c2410c` | 2 | `--tone-orange-fg` |
| `#ea580c` | 1 | `--tone-orange-fg` |
| `#db2777` | 2 | `--tone-pink-fg` |
| `#f0fdf4` | 12 | `--tone-success-bg` |
| `#ecfdf5` | 3 | `--tone-success-bg` |
| `#dcfce7` | 15 | `--tone-success-bg-strong` |
| `#d1fae5` | 2 | `--tone-success-bg-strong` |
| `#86efac` | 9 | `--tone-success-border` |
| `#bbf7d0` | 3 | `--tone-success-border` |
| `#a7f3d0` | 2 | `--tone-success-border` |
| `#6ee7b7` | 1 | `--tone-success-border` |
| `#15803d` | 35 | `--tone-success-fg` |
| `#065f46` | 5 | `--tone-success-fg` |
| `#047857` | 3 | `--tone-success-fg` |
| `#059669` | 9 | `--tone-success-solid` |
| `#16a34a` | 4 | `--tone-success-solid` |
| `#4ade80` | 2 | `--tone-success-solid` |
| `#22c55e` | 1 | `--tone-success-solid` |
| `#f5f3ff` | 11 | `--tone-violet-bg` |
| `#ede9fe` | 5 | `--tone-violet-bg` |
| `#f3e8ff` | 2 | `--tone-violet-bg` |
| `#c4b5fd` | 9 | `--tone-violet-border` |
| `#ddd6fe` | 2 | `--tone-violet-border` |
| `#6d28d9` | 14 | `--tone-violet-fg` |
| `#7c3aed` | 12 | `--tone-violet-fg` |
| `#9333ea` | 2 | `--tone-violet-fg` |
| `#8b5cf6` | 1 | `--tone-violet-fg` |
| `#7e22ce` | 1 | `--tone-violet-fg` |
| `#fffbeb` | 10 | `--tone-warning-bg` |
| `#fef9c3` | 5 | `--tone-warning-bg` |
| `#fef3c7` | 14 | `--tone-warning-bg-strong` |
| `#fde68a` | 18 | `--tone-warning-border` |
| `#fcd34d` | 5 | `--tone-warning-border` |
| `#fef08a` | 1 | `--tone-warning-border` |
| `#92400e` | 37 | `--tone-warning-fg` |
| `#b45309` | 20 | `--tone-warning-fg` |
| `#854d0e` | 1 | `--tone-warning-fg` |
| `#a16207` | 1 | `--tone-warning-fg` |
| `#d97706` | 5 | `--tone-warning-solid` |
