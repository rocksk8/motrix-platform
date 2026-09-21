---
name: block-python-dq-backtick
enabled: true
event: bash
action: block
conditions:
  - field: command
    operator: regex_match
    pattern: '(?:python3?|py)(?:\.exe)?\b[^\n;&|]*?\s-c\s+"'
  - field: command
    operator: contains
    pattern: '`'
---

🚫 **擋下：`python -c "..."` 用雙引號包住，而命令裡有反引號**

shell 會把反引號當成**命令替換先執行掉**。被吃掉的字在產出的檔案裡變成一個空白，
句子少一個詞、通篇看起來還是正常的，而且**結束碼是 0、沒有任何錯誤訊息**。

這個坑在 2026-09-14／09-20／09-21 各踩過兩次，共六次。
每一次都「知道」這條規則，但當下在做別的事，沒有停下來評估。
所以改成擋住，不靠記得。

**怎麼做才對：**

1. **內容要進檔案 → 用 Write 工具**，不要經過 shell。
   不要先判斷「這段有沒有反引號」——中文技術內容幾乎必然含
   `` `檔名.py` ``、`` `函式()` ``、`` `--flag` ``，判斷本身就是失敗點。
2. 需要腳本邏輯（搜尋／替換／插入）→ **內容先用 Write 寫成一個檔，腳本從那個檔讀**。
3. 真的要用 heredoc → **一律加引號**：`<<'EOF' ... EOF`
4. 需要帶 shell 變數進去 → heredoc 保持加引號，變數走環境變數或 `sys.argv`。

**寫完後 probe 一下產物裡該有的字串在不在，不要只看結束碼。**
