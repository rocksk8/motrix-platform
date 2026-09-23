# -*- coding: utf-8 -*-
"""例外訊息的去處（`EM3`）：畫面只給代碼，例外全文進 log。

`docs/windows/SPEC-EM3.md §1`：`except Exception` 抓到的內容**沒有一個
是我們決定要說的**（資料表名／欄位名／暫存檔路徑／SQL 片段／函式庫版本），
直接塞進 `HTTPException(detail=...)` 就是把這些字送上使用者畫面。

🔴 拿掉 `{e}` 不是修法——診斷能力會一起消失。要動的是「例外內容的去處」：
```python
except Exception as e:
    tid = trace_id()
    logger.exception("xxx failed trace=%s", tid)   # 全文進 log，同一個 tid
    raise HTTPException(500, f"XXX 失敗（代碼 {tid}）")  # 畫面只有代碼
```
⚠️ 順序不可以顛倒——先組訊息再 log 的話，log 失敗時使用者拿到一個查不到
的代碼，那比沒有代碼更糟。
"""
import secrets


def trace_id() -> str:
    """給使用者看的錯誤代碼。**不可猜、不可枚舉**。

    ❌ 流水號（ERR-001）——可猜，還會洩漏「系統出過幾次錯」
    ❌ 時間戳——可猜，且兩個同時發生的錯會撞
    ✅ 隨機 8 碼 hex（`secrets`，不是 `random`——`random` 可預測）
    """
    return secrets.token_hex(4)
