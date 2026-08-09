"""本機研究管道：抓官網真實網頁內容，交給本機 Ollama 從真實文字中「抽取」結構化資料
（不是叫 Ollama 憑記憶回答，避免 SELECTION-DB-INDEX.md §3.1 提過的編造風險）。

用途：選型資料庫要幫某品牌補型號時，先用這支腳本產生候選清單（JSON），Claude 讀取後
人工核對再寫入資料庫——跟現在用 subagent 派工研究、只把結構化摘要帶回主線程的流程一樣，
只是這一步改在本機用免費的本地模型做，不消耗雲端 token。

**已知限制（務必先讀）**：
- 只用 `requests` 抓純 HTML，**抓不到需要 JavaScript 才會渲染出內容的頁面**（很多官網的產品
  列表是前端框架動態載入的，這種情況抓到的文字會很少甚至空白——腳本會在這種情況印出警告，
  遇到警告要換成請 Claude 用 WebFetch/WebSearch 查證那個網址，不要硬信本地模型在文字很少時
  的輸出）
- 本地模型不連網，只會照給它的文字內容做「摘要/抽取」，**不會另外查證價格是否為最新**——
  輸出的每一筆都務必當作「候選資料」，最終寫入資料庫前 Claude 仍要看過、對明顯不合理的地方
  （例：售價金額跟其他型號差距離譜、規格格式怪異）再篩一次
- 適合拿來處理「網站有清楚產品列表頁、純 HTML 就能看到型號/規格」的網站；遇到需要登入、
  地區跳轉、複雜互動篩選才能看到內容的網站，這支工具幫不上忙

用法：
    python local_research_pipeline.py --brand "VIGI" --urls URL1 URL2 URL3 --out result.json
    python local_research_pipeline.py --brand "AXIS" --urls URL1 --out result.json --model qwen3.6

需要本機 Ollama 已啟動（預設 http://localhost:11434）且已 pull 對應模型。
"""
import argparse
import json
import re
import sys
from datetime import datetime

import requests
from bs4 import BeautifulSoup

OLLAMA_URL = "http://localhost:11434/api/generate"
DEFAULT_MODEL = "qwen3.6"
FETCH_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
}
MAX_TEXT_CHARS = 30000  # 避免單頁夾帶過多雜訊，多數產品列表頁遠小於此
MIN_TEXT_CHARS_WARN = 400  # 抓到的文字少於這個門檻，很可能是 JS 渲染頁面，需要提醒


def fetch_page_text(url: str) -> str:
    resp = requests.get(url, headers=FETCH_HEADERS, timeout=20)
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator="\n")
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_TEXT_CHARS]


def ask_ollama(model: str, brand: str, url: str, page_text: str) -> dict:
    prompt = f"""你是資料整理助手。以下是從網址 {url} 抓到的真實網頁文字內容（品牌：{brand}）。
請「只根據這段文字」找出裡面列出的產品型號，不要用你自己的知識補充或猜測任何文字中沒有的資訊。

對每一款產品，盡量找出：型號（model）、售價（price_note，含幣別；若文字中沒有價格就填
"洽詢報價（頁面未列價格）"）、規格（specs，一個 [["規格名","值"], ...] 的陣列，從文字中能
找到的規格都列，找不到就給空陣列）。

嚴格只回傳 JSON，格式如下，不要有其他文字說明：
{{"products": [{{"model": "...", "price_note": "...", "specs": [["...","..."]]}}]}}

若這段文字完全看不出任何產品型號（例如只有導覽選單、版權宣告等雜訊，沒有實際產品內容），
回傳 {{"products": []}}。

網頁文字內容：
---
{page_text}
---
"""
    try:
        resp = requests.post(
            OLLAMA_URL,
            json={"model": model, "prompt": prompt, "stream": False, "format": "json", "think": False},
            timeout=180,
        )
        resp.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(f"  ✗ 連不到本機 Ollama（{OLLAMA_URL}），請確認 Ollama 服務有啟動", file=sys.stderr)
        raise
    body = resp.json()
    # 部分模型（如 qwen3.6）是推理模型，即使 think:False 仍可能把內容留在 thinking 欄位
    # 而非 response，兩邊都要檢查，避免明明有輸出卻被當成空白
    raw = body.get("response") or body.get("thinking") or ""
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  ⚠ Ollama 回傳的內容不是合法 JSON，原樣保留在 raw_response 供人工檢查", file=sys.stderr)
        parsed = {"products": [], "raw_response": raw}
    return parsed


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--brand", required=True, help="品牌名稱，如 VIGI")
    ap.add_argument("--urls", required=True, nargs="+", help="要抓取的官網/經銷商產品頁網址（可多個）")
    ap.add_argument("--out", required=True, help="輸出 JSON 檔案路徑")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"本機 Ollama 模型名稱（預設 {DEFAULT_MODEL}）")
    args = ap.parse_args()

    results = []
    for url in args.urls:
        print(f"抓取 {url} ...")
        try:
            text = fetch_page_text(url)
        except Exception as e:
            print(f"  ✗ 抓取失敗：{e}", file=sys.stderr)
            results.append({"url": url, "error": str(e), "products": []})
            continue

        if len(text) < MIN_TEXT_CHARS_WARN:
            print(f"  ⚠ 只抓到 {len(text)} 字元的文字內容，這個網址很可能需要 JavaScript 才能渲染出"
                  f"產品內容，本工具抓不到——建議改請 Claude 用 WebFetch/WebSearch 查證這個網址")

        print(f"  送進 Ollama（{args.model}）萃取結構化資料...")
        extracted = ask_ollama(args.model, args.brand, url, text)
        n = len(extracted.get("products", []))
        print(f"  → 抽出 {n} 筆候選產品")
        results.append({
            "url": url,
            "fetched_text_chars": len(text),
            "low_text_warning": len(text) < MIN_TEXT_CHARS_WARN,
            **extracted,
        })

    output = {
        "brand": args.brand,
        "model": args.model,
        "generated_at": datetime.now().isoformat(),
        "note": "候選資料，未經人工/Claude 核對前不要直接寫入資料庫",
        "results": results,
    }
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)
    total = sum(len(r.get("products", [])) for r in results)
    print(f"\n完成，共抽出 {total} 筆候選產品，已寫入 {args.out}")
    print("下一步：把這個 JSON 檔案交給 Claude 核對（價格合理性、規格完整度、是否為真實型號），再決定寫入資料庫。")


if __name__ == "__main__":
    main()
