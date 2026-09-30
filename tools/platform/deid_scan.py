# -*- coding: utf-8 -*-
"""去識別化 S1：掃描器（L0 工具；SALE-PACKAGE-DEID.md §2.2 (b)(c)）。

只用標準庫；**輸出不含任何明文**：命中一律報「路徑:行號:類別:值代碼」，值代碼＝HMAC 前 4 bytes（8 hex）。

## 兩層偵測
1. **雜湊層**（要金鑰＋清單 `deid_hashlist.py export` 產生）：本公司正式機資料庫裡的識別值（公司名、統編、電話、email、客戶、供應商、人員、地址、帳號）。
   - 數字型（統編、電話、帳號）：文字正規化後取出**連續數字串**，對清單出現過的每種長度滑動取窗、逐窗比對。
   - 文字型（名稱、地址、姓名、email）：清單另存每個值「前 3 個正規化字元」的 HMAC（`anchors`，截 4 bytes）＋該 anchor 對應的長度；
     掃描時每個位置先算 3 字 anchor，命中才對登記過的長度算完整雜湊。
   - 長度下限：數字型 ≥ 8、文字型 ≥ 3（正規化後）；更短的（兩字簡稱）改由人工補充檔的「關鍵字＋鄰接字」規則（export 時展開成完整字串再雜湊）。
2. **樣式層**（不需金鑰）：非 example／.test 的 email、檢查碼正確的統編、台灣電話、私有 IP、開發環境路徑、門牌地址
   ⇒ 不在「虛構登記」（deid_fiction.json）也不在「誤判登記」（deid_allow.json）⇒ 命中即擋。

## 文字視角（每個檔掃）
原文；JSON 檔再逐一掃**解析後的字串值**（`\\uXXXX` 還原）；HTML 另靠正規化裡的 `html.unescape`；PNG 的 tEXt／iTXt／zTXt 文字段。
（JPEG EXIF 尚未涵蓋——見文件 §10.5。）

## 誤判登記 `deid_allow.json`（進 repo）
`[{"path", "value_id", "count", "reason", "expires"}]`：`value_id` 是 HMAC 代碼（沒有金鑰無法還原）；次數要一致（多了少了都紅）；
**kind 為 company／taxid／phone／email／person 的值不准登記**（驗證時直接紅）；過期 ⇒ 紅。

用法（也可 import）：
  python tools/platform/deid_scan.py <包目錄> --hashlist <清單.json> --key <金鑰檔> [--allow tools/platform/deid_allow.json] [--fiction tools/platform/deid_fiction.json]
"""
import argparse
import hashlib
import hmac
import html
import json
import re
import struct
import sys
import unicodedata
import zlib
from collections import defaultdict
from datetime import date
from pathlib import Path

NUMERIC_KINDS = ("taxid", "phone", "account")
#: 不准登記進誤判登記檔的類別（本公司自己的資料）
NO_ALLOW_KINDS = ("company", "taxid", "phone", "email", "person")
MIN_DIGITS, MIN_TEXT = 8, 3
KEYCHECK = b"motrix-deid-keycheck"
CANARY = "MOTRIX-CANARY-6F3A9C1E-DEID"          # 金絲雀：export 一律加進清單、掃描器要能掃到（管線沒壞的證明）
TEXT_SUFFIXES = {".py", ".html", ".htm", ".js", ".css", ".json", ".ps1", ".bat", ".cmd", ".txt", ".ini", ".cfg", ".md", ".csv",
                 ".xml", ".yml", ".yaml", ".sql", ".sh", ".toml", ".svg", ".tsv", ".env", ".lock"}
IMAGE_SUFFIXES = {".png"}
SEP_RE = re.compile(r"[\s\-_.,:;|/\\()（）、，。｜]+")
DIGIT_RUN_RE = re.compile(r"\d+")


# ── 金鑰與正規化 ────────────────────────────────────────────────────────────────

def key_id(key: bytes) -> str:
    return hmac.new(key, KEYCHECK, hashlib.sha256).hexdigest()[:16]


def normalize(s: str) -> str:
    """NFKC（全形→半形）、casefold、`+886`→`0`、去掉空白與分隔符。"""
    s = unicodedata.normalize("NFKC", html.unescape(s or "")).casefold().replace("+886", "0")
    return SEP_RE.sub("", s)


def hmac_id(key: bytes, kind: str, value: str) -> str:
    """完整值代碼（16 bytes＝32 hex）。value 會先正規化。"""
    return hmac.new(key, ("%s|%s" % (kind, normalize(value))).encode("utf-8"), hashlib.sha256).digest()[:16].hex()


def _hmac_norm(key: bytes, kind: str, norm: str) -> str:
    return hmac.new(key, ("%s|%s" % (kind, norm)).encode("utf-8"), hashlib.sha256).digest()[:16].hex()


def anchor_id(key: bytes, norm3: str) -> str:
    """3 字 anchor（已正規化）的代碼（4 bytes＝8 hex）。"""
    return hmac.new(key, ("anchor|" + norm3).encode("utf-8"), hashlib.sha256).digest()[:4].hex()


def load_key(path) -> bytes:
    k = Path(path).read_bytes()
    if len(k) != 32:
        raise SystemExit("金鑰檔必須是 32 bytes")
    return k


# ── 清單 ────────────────────────────────────────────────────────────────────────

class HashList:
    def __init__(self, data: dict, key: bytes):
        if data.get("v") != 1:
            raise ValueError("清單格式版本不符")
        if data.get("key_id") != key_id(key):
            raise ValueError("金鑰與清單不符（key_id 不同）：手上的金鑰不是產生這份清單的那一把")
        self.data = data
        self.key = key
        self.kind_of = {h: k for h, k in (data.get("hashes") or {}).items()}          # 32 hex → kind
        self.anchors = {a: list(ls) for a, ls in (data.get("anchors") or {}).items()}  # 8 hex → [長度]
        self.num_lengths = defaultdict(set)
        for kind, ls in (data.get("lengths") or {}).items():
            if kind in NUMERIC_KINDS:
                self.num_lengths[kind].update(ls)
        self.text_kinds = sorted({k for k in self.kind_of.values() if k not in NUMERIC_KINDS})
        self.numeric_kinds = sorted({k for k in self.kind_of.values() if k in NUMERIC_KINDS})

    @property
    def created(self):
        return self.data.get("created")


def load_hashlist(path, key: bytes) -> HashList:
    return HashList(json.loads(Path(path).read_text(encoding="utf-8")), key)


def check_freshness(hl: HashList, today=None, max_days=30, warn_days=7):
    """⇒ (問題或 None, 提示或 None)。清單超過 max_days ⇒ 拒絕；到期前 warn_days 起提示。"""
    try:
        created = date.fromisoformat(str(hl.created)[:10])
    except ValueError:
        return "清單缺 created，無法判斷新舊", None
    age = ((today or date.today()) - created).days
    if age > max_days:
        return "清單已過期（建立於 %s，超過 %d 天）：請到正式機重跑 export" % (created, max_days), None
    if age >= max_days - warn_days:
        return None, "清單將於 %s 到期（還有 %d 天）" % (created.fromordinal(created.toordinal() + max_days), max_days - age)
    return None, None


# ── 文字視角 ────────────────────────────────────────────────────────────────────

def read_text_any(path: Path) -> str:
    raw = path.read_bytes()
    for enc in ("utf-8-sig", "cp950", "utf-16"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, UnicodeError):
            continue
    return raw.decode("latin-1")


def _json_strings(obj):
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _json_strings(k)
            yield from _json_strings(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _json_strings(v)


def _png_text(raw: bytes):
    if raw[:8] != b"\x89PNG\r\n\x1a\n":
        return
    i = 8
    while i + 8 <= len(raw):
        ln, typ = struct.unpack(">I4s", raw[i:i + 8])
        data = raw[i + 8:i + 8 + ln]
        try:
            if typ == b"tEXt":
                raw_txt = data.replace(b"\x00", b" ")
                yield raw_txt.decode("latin-1")               # 規格是 Latin-1
                yield raw_txt.decode("utf-8", "replace")      # 實務上常有人直接塞 UTF-8
            elif typ == b"zTXt":
                k, _, rest = data.partition(b"\x00")
                yield k.decode("latin-1") + " " + zlib.decompress(rest[1:]).decode("utf-8", "replace")
            elif typ == b"iTXt":
                k, _, rest = data.partition(b"\x00")
                comp, rest = rest[0], rest[2:]
                _lang, _, rest = rest.partition(b"\x00")
                _tk, _, txt = rest.partition(b"\x00")
                yield k.decode("latin-1") + " " + (zlib.decompress(txt) if comp else txt).decode("utf-8", "replace")
        except Exception:                                           # noqa: BLE001 — 壞的 chunk 不擋掃描
            pass
        i += 12 + ln


def iter_text_views(path: Path):
    """⇒ 產生 (行號, 文字)。行號對原文；JSON 解析後的字串值以行號 0 代表「解析後」。"""
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        for t in _png_text(path.read_bytes()):
            yield 0, t
        return
    if suffix not in TEXT_SUFFIXES and path.name not in (".env", ".gitattributes", ".gitignore"):
        return
    text = read_text_any(path)
    for n, line in enumerate(text.split("\n"), start=1):
        yield n, line
    if suffix == ".json":
        try:
            for s in _json_strings(json.loads(text)):
                yield 0, s
        except ValueError:
            pass


# ── 樣式層 ──────────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@([A-Za-z0-9\-]+(?:\.[A-Za-z0-9\-]+)+)")
IP_RE = re.compile(r"(?<![\d.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?![\d.])")
DEVPATH_RE = re.compile(r"[A-Za-z]:[\\/](?:Users|開發|MOTRIX|Desktop)[\\/][^\s\"'<>|]*|/(?:home|Users)/[a-z0-9_.-]+/", re.I)
TAX_RE = re.compile(r"(?<!\d)\d{8}(?!\d)")
PHONE_RE = re.compile(r"(?<!\d)(?:\+886[\s-]?|0)(?:9\d{2}[\s-]?\d{3}[\s-]?\d{3}|[2-8][\s-]?\d{3,4}[\s-]?\d{4})(?!\d)")
ADDR_RE = re.compile(r"[一-鿿]{1,4}[縣市][一-鿿]{1,4}[區鄉鎮市][一-鿿0-9]{1,12}[路街道][一-鿿0-9段巷弄]{0,10}\d{1,4}號")
PLACEHOLDER_DOMAINS = ("example.com", "example.org", "example.net", "example.invalid", "example.test", "localhost")
#: W4 出貨稽核（2026-09-30）補的三類——原本只有雜湊層（要金鑰＋清單）才抓得到，而簡稱、單據號、密碼不會逐字等於資料庫裡的值：
#: 單據編號（MQ-202608-009）＝真實案件的指紋；公司全名樣式（不需清單）；密碼陳述與「密碼」集合常數。
DOCNO_RE = re.compile(r"(?<![A-Za-z0-9])[A-Z]{2,3}-20\d{4}-\d{3,4}(?!\d)")
COMPANY_RE = re.compile(r"([一-鿿]{2,10})(股份有限公司|有限公司|企業社|工程行|實業社)")
#: 「公司」前面不是名稱的泛稱（文件裡談「股份有限公司」這個類型，不是某一家）
COMPANY_GENERIC_PREFIX = {"股份", "本", "貴", "該", "各", "某", "甲", "乙", "丙", "一般", "私人", "有限", "本公司", "貴公司", "他"}
CRED_RE = re.compile(r"(?i)(?:密碼|password|passwd|pwd)[\"'`]?\s*[:：=＝]\s*[\"'`]?([A-Za-z0-9!@#^&_+=~\-]{4,})(?![.\w(])")   # 值只收 ASCII 且後面不接「.」「(」——擋 `password: this.form.pw` 這類程式碼
#: 只在這些副檔名看「密碼陳述」（程式碼裡 `password = request.password` 是變數，不是值）
CRED_SUFFIXES = {".md", ".txt", ".json", ".html", ".htm", ".ps1", ".bat", ".cmd", ".ini", ".cfg", ".csv", ".yml", ".yaml", ".env", ".toml"}
SECRET_NAME_RE = re.compile(r"^\s*_?[A-Z][A-Z0-9_]*(?:PASSWORD|PASSWD|SECRET|CREDENTIAL)[A-Z0-9_]*\s*(?::[^=]+)?=\s*[\(\[{]")
STRING_LIT_RE = re.compile(r"[\"']([^\"'\\]{4,})[\"']")


def tw_tax_id_valid(s: str) -> bool:
    """台灣統一編號檢查碼（含第 7 碼為 7 的特例）。"""
    if not re.fullmatch(r"\d{8}", s):
        return False
    w = (1, 2, 1, 2, 1, 2, 4, 1)
    tot = 0
    for d, k in zip(s, w):
        p = int(d) * k
        tot += p // 10 + p % 10
    return tot % 5 == 0 or (s[6] == "7" and (tot + 1) % 5 == 0)


def pattern_hits(line: str):
    """⇒ [(kind, 值)]（值只用來算代碼，不輸出）。"""
    out = []
    for m in EMAIL_RE.finditer(line):
        dom = m.group(1).lower()
        if not (dom in PLACEHOLDER_DOMAINS or dom.endswith((".test", ".invalid", ".example", ".localhost"))):
            out.append(("email", m.group(0)))
    for m in IP_RE.finditer(line):
        out.append(("private_ip", m.group(1)))
    for m in DEVPATH_RE.finditer(line):
        out.append(("dev_path", m.group(0)))
    for m in TAX_RE.finditer(line):
        if tw_tax_id_valid(m.group(0)):
            out.append(("taxid_pattern", m.group(0)))
    for m in PHONE_RE.finditer(line):
        out.append(("phone_pattern", m.group(0)))
    for m in ADDR_RE.finditer(line):
        out.append(("address_pattern", m.group(0)))
    for m in DOCNO_RE.finditer(line):
        out.append(("docno_pattern", m.group(0)))
    for m in COMPANY_RE.finditer(line):
        name = m.group(1)[:-2] if m.group(1).endswith("股份") else m.group(1)      # 「…股份有限公司」的「股份」屬於類型
        if len(name) >= 2 and name not in COMPANY_GENERIC_PREFIX and not re.search(r"[為是的在或]", name):      # 帶連接詞＝一句話，不是名稱
            out.append(("company_pattern", m.group(0)))
    return out


def credential_hits(path: Path, line: str, in_secret_block: bool):
    """需要檔案層級脈絡的兩類：⇒ ([(kind, 值)], 是否仍在「密碼集合常數」裡)。
    ① 文件／設定檔的「密碼：xxx」陳述；② .py 裡 `*_PASSWORD*／*_SECRET*／*_CREDENTIAL* = ( … )` 集合常數內的每個字串字面值。"""
    out, suffix = [], path.suffix.lower()
    if suffix in CRED_SUFFIXES:
        for m in CRED_RE.finditer(line):
            v = m.group(1)
            if not re.fullmatch(r"[x*•·]+|changeme|your[-_]?password", v, re.I):
                out.append(("credential_pattern", v))
    if suffix == ".py":
        starts = bool(SECRET_NAME_RE.match(line))
        if starts:
            in_secret_block = True
        if in_secret_block:
            for m in STRING_LIT_RE.finditer(line):
                out.append(("secret_literal", m.group(1)))
            opened = len(re.findall(r"[\(\[{]", line))
            closed = len(re.findall(r"[\)\]}]", line))
            if starts:
                in_secret_block = opened > closed
            elif closed > opened or re.match(r"^\s*[\)\]}]", line):
                in_secret_block = False
    return out, in_secret_block


# ── 雜湊層比對 ──────────────────────────────────────────────────────────────────

def hashlist_hits(hl: HashList, text: str):
    """⇒ [(kind, 完整值代碼)]。"""
    key, out = hl.key, []
    norm = normalize(text)
    if not norm:
        return out
    for run in DIGIT_RUN_RE.finditer(norm):
        digits = run.group(0)
        for kind in hl.numeric_kinds:
            for ln in hl.num_lengths.get(kind, ()):
                if len(digits) < ln:
                    continue
                for i in range(len(digits) - ln + 1):
                    h = _hmac_norm(key, kind, digits[i:i + ln])
                    if hl.kind_of.get(h) == kind:
                        out.append((kind, h))
    for i in range(len(norm) - MIN_TEXT + 1):
        lens = hl.anchors.get(anchor_id(key, norm[i:i + MIN_TEXT]))
        if not lens:
            continue
        for ln in lens:
            if i + ln > len(norm):
                continue
            cand = norm[i:i + ln]
            for kind in hl.text_kinds:
                h = _hmac_norm(key, kind, cand)
                if hl.kind_of.get(h) == kind:
                    out.append((kind, h))
    return out


# ── 登記檔 ──────────────────────────────────────────────────────────────────────

def load_json_list(path):
    if not path or not Path(path).exists():
        return []
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    return d if isinstance(d, list) else []


def fiction_ids(fiction_entries, key=None):
    """虛構登記：值代碼（樣式層用明文值的 sha256 前 8 hex；雜湊層用 hmac 代碼）集合。"""
    return {str(e.get("value_id")) for e in fiction_entries if e.get("value_id")}


def value_code(kind: str, value: str, key=None) -> str:
    """報表用的值代碼（不含明文）。有金鑰用 HMAC；沒有（樣式層）用 sha256 前 8 hex。"""
    n = normalize(value)
    if key:
        return hmac.new(key, ("code|%s|%s" % (kind, n)).encode("utf-8"), hashlib.sha256).hexdigest()[:8]
    return hashlib.sha256(("%s|%s" % (kind, n)).encode("utf-8")).hexdigest()[:8]


def allow_problems(allow_entries, today=None):
    """誤判登記本身的驗證：不准登記本公司類別、欄位齊全、未過期。"""
    probs = []
    for e in allow_entries:
        for f in ("path", "value_id", "count", "reason", "expires"):
            if f not in e:
                probs.append("誤判登記缺欄位 %s：%r" % (f, e))
        if e.get("kind") in NO_ALLOW_KINDS:
            probs.append("誤判登記不得放行本公司類別 %s：%s／%s" % (e.get("kind"), e.get("path"), e.get("value_id")))
        try:
            if date.fromisoformat(str(e.get("expires"))) < (today or date.today()):
                probs.append("誤判登記已過期：%s／%s（%s）" % (e.get("path"), e.get("value_id"), e.get("expires")))
        except ValueError:
            probs.append("誤判登記的 expires 格式不對：%r" % (e.get("expires"),))
    return probs


# ── 掃描 ────────────────────────────────────────────────────────────────────────

class Hit:
    __slots__ = ("path", "line", "kind", "value_id", "layer")

    def __init__(self, path, line, kind, value_id, layer):
        self.path, self.line, self.kind, self.value_id, self.layer = path, line, kind, value_id, layer

    def as_tuple(self):
        return (self.path, self.line, self.kind, self.value_id)

    def __repr__(self):
        return "%s:%s:%s:%s" % self.as_tuple()


def scan(root, hashlist=None, fiction=None, allow=None, skip_dirs=(".git", "__pycache__", "node_modules")):
    """掃一個目錄樹 ⇒ [Hit]（已扣掉虛構登記與符合次數的誤判登記；誤判登記本身有問題 ⇒ 由呼叫端用 allow_problems 另報）。"""
    root = Path(root)
    fiction_set = fiction_ids(fiction or [])
    hits = []
    for path in sorted(p for p in root.rglob("*") if p.is_file()):
        rel = path.relative_to(root)
        if any(part in skip_dirs for part in rel.parts):
            continue
        seen, raw_codes = set(), set()
        in_secret = False
        for line, text in iter_text_views(path):
            found = []
            if hashlist is not None:
                for kind, h in hashlist_hits(hashlist, text):
                    found.append((kind, h[:8], "hash"))
            for kind, val in pattern_hits(text):
                found.append((kind, value_code(kind, val), "pattern"))
            cred, in_secret_next = credential_hits(path, text, in_secret if line > 0 else False)
            if line > 0:
                in_secret = in_secret_next
            for kind, val in cred:
                found.append((kind, value_code(kind, val), "pattern"))
            for kind, code, layer in found:
                if code in fiction_set:
                    continue
                if line == 0 and (kind, code) in raw_codes:
                    continue                    # 解析後視角（JSON 字串值、PNG 文字段）看到的同一個值，原文那一行已經報過
                k = (line, kind, code)
                if k in seen:
                    continue
                seen.add(k)
                if line > 0:
                    raw_codes.add((kind, code))
                hits.append(Hit(rel.as_posix(), line, kind, code, layer))
    return apply_allow(hits, allow or [])


def apply_allow(hits, allow_entries):
    """扣掉誤判登記：(path, value_id) 的命中次數必須等於登記的 count（多了少了都不扣，讓它照紅）。"""
    by = defaultdict(list)
    for h in hits:
        by[(h.path, h.value_id)].append(h)
    drop = set()
    for e in allow_entries:
        k = (e.get("path"), e.get("value_id"))
        if k in by and len(by[k]) == e.get("count"):
            drop.add(k)
    return [h for h in hits if (h.path, h.value_id) not in drop]


def canary_check(hl: HashList):
    """正對照：金絲雀字串必須被雜湊層掃到（清單、金鑰、掃描器三者接得起來）；清單沒有金絲雀 ⇒ 問題。"""
    hits = hashlist_hits(hl, "prefix %s suffix" % CANARY)
    if not any(kind == "canary" for kind, _h in hits):
        return "金絲雀沒有被掃到：清單缺金絲雀，或金鑰／掃描器壞了——其他「沒有命中」都不可信"
    return None


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("package")
    ap.add_argument("--hashlist")
    ap.add_argument("--key")
    ap.add_argument("--allow")
    ap.add_argument("--fiction")
    a = ap.parse_args(argv)
    hl = None
    if a.hashlist:
        if not a.key:
            print("DEID_SCAN_FAIL 有清單就要給 --key")
            return 2
        try:
            hl = load_hashlist(a.hashlist, load_key(a.key))
        except (ValueError, OSError) as e:
            print("DEID_SCAN_FAIL %s" % e)
            return 2
        prob, note = check_freshness(hl)
        if note:
            print("DEID_SCAN_NOTE %s" % note)
        if prob:
            print("DEID_SCAN_FAIL %s" % prob)
            return 2
        c = canary_check(hl)
        if c:
            print("DEID_SCAN_FAIL %s" % c)
            return 2
    allow = load_json_list(a.allow)
    probs = allow_problems(allow)
    for p in probs:
        print("DEID_SCAN_FAIL %s" % p)
    hits = scan(a.package, hl, load_json_list(a.fiction), allow)
    for h in hits:
        print("DEID_HIT %r（%s）" % (h, h.layer))
    print("DEID_SCAN_%s 命中 %d 筆" % ("OK" if not hits and not probs else "FAIL", len(hits)))
    return 0 if not hits and not probs else 1


if __name__ == "__main__":
    sys.exit(main())
