# -*- coding: utf-8 -*-
"""報價單／估價單品項下方「備註」的排版選項（2026-11-17，使用者要求每個品項各自選）。

品項資料多一個欄位 `notesLayout`：
- `'wrap'`（預設）：照使用者打的換行顯示（原本的行為）；
- `'inline'`（一行到底）：忽略換行，各行用全形空白接成一段，橫向排到滿行才自然折行。
沒有這個鍵＝`'wrap'`——舊單輸出逐位元不變。不認得的值一律當預設（顯示端）、存檔時清掉（伺服器端，見 clean_items）。
最後一頁的「備註事項」不屬於這裡，永遠照換行顯示（使用者已確認）。

純函式、不依賴任何模組（L1 helper），pdf_gen 與 quotations.py 共用同一份定義。
"""
WRAP = 'wrap'
INLINE = 'inline'
LAYOUTS = (WRAP, INLINE)
JOINER = '　'          # 全形空白：行與行之間的分隔


def layout_of(item) -> str:
    """這個品項的備註排版；沒有鍵、型別不對、不認得的值一律是 'wrap'。"""
    return INLINE if isinstance(item, dict) and item.get('notesLayout') == INLINE else WRAP


def flatten_inline(text: str) -> str:
    """一行到底：每行去頭尾空白、丟掉空行，用全形空白接起來。"""
    return JOINER.join(ln.strip() for ln in str(text or '').splitlines() if ln.strip())


def clean_items(data) -> None:
    """存檔時（新增／更新報價單）清掉不認得的 notesLayout：值不是 wrap／inline ⇒ 整個鍵刪掉（＝預設）。
    只動有這個鍵的品項；舊單沒有這個鍵，原樣不動。"""
    items = data.get('items') if isinstance(data, dict) else None
    if not isinstance(items, list):
        return
    for it in items:
        if isinstance(it, dict) and 'notesLayout' in it and it['notesLayout'] not in LAYOUTS:
            del it['notesLayout']
