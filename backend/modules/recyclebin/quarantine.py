# -*- coding: utf-8 -*-
"""隔離目錄：進暫存區的附件『搬』進來（不是複製），還原時搬回，清除時整個資料夾刪掉。

位置：預設 `<安裝根目錄>\\資源回收筒`（與 報價單PDF 等並列、git 忽略、**不在 uploads/ 底下** ⇒ 不被雲端鏡像、不被檔案開啟路由服務）；
`system_settings.recyclebin_dir` 可由最高管理者改到樹外的絕對路徑。隔離檔含個資 ⇒ F2：永不上雲、不進每日匯出。
結構：`<根>\\<token>\\<root>\\<原相對路徑>`；token 是 uuid（不是自增 id——交易回滾後 id 會被重用，孤兒資料夾會撞上新的列）。

搬移：同磁碟 `os.replace`（原子）；跨磁碟 ⇒ 複製→比對 sha256→刪原檔。搬移在 DB 刪除**之前**做、失敗就搬回；
呼叫端的交易之後若回滾 ⇒ 暫存區沒有那一列、檔案卻在隔離區 ⇒ `reconcile_orphans()`（每日工作）把它們搬回原路徑，不會遺失。
這個檔案是模組內**唯一**直接 `os.replace/os.remove/shutil.rmtree` 的地方（直接刪檔守門 tests/platform/test_recyclebin_guards_t53.py）。
"""
import hashlib
import logging
import os
import shutil
import time

from helpers import uploads as _uploads

logger = logging.getLogger(__name__)

ROOT_UPLOADS = "uploads"
SETTING_DIR = "recyclebin_dir"
DIRNAME = "資源回收筒"
_ORPHAN_GRACE_SECONDS = 3600          # 孤兒資料夾要超過這麼久才處理（呼叫端的交易可能還沒 commit）


def default_dir() -> str:
    """預設＝uploads 的上一層（正式機＝安裝根目錄）下的「資源回收筒」。從目前的 UPLOADS_ROOT 推：測試把 UPLOADS_ROOT 換成暫存目錄時，
    隔離區自動跟著換，不會寫進真的安裝目錄。"""
    return os.path.join(os.path.dirname(os.path.realpath(_uploads.UPLOADS_ROOT)), DIRNAME)


def root_dir() -> str:
    """隔離區根目錄（絕對路徑）。設定值不合法（非絕對路徑）⇒ 用預設，不拋錯。"""
    try:
        from helpers.settings import _get_setting
        v = _get_setting(SETTING_DIR, "") or ""
    except Exception:                      # noqa: BLE001
        v = ""
    v = str(v).strip()
    return os.path.abspath(v) if v and os.path.isabs(v) else default_dir()


def _token_ok(token: str) -> bool:
    return bool(token) and len(token) == 32 and all(c in "0123456789abcdef" for c in token)


def bin_dir(token: str) -> str:
    if not _token_ok(token):
        raise ValueError("不合法的暫存區代號：%r" % (token,))
    return os.path.join(root_dir(), token)


def _within(base: str, p: str) -> bool:
    base, p = os.path.normcase(os.path.realpath(base)), os.path.normcase(os.path.realpath(p))
    return p == base or p.startswith(base + os.sep)


def _src_abs(root: str, rel: str):
    """(root, rel) ⇒ 實體絕對路徑；不合法 ⇒ None。目前只認 uploads 根（P0）。"""
    if root != ROOT_UPLOADS:
        return None
    canon = _uploads.canonical_upload_path(rel)
    if canon is None:
        return None
    return os.path.join(_uploads.UPLOADS_ROOT, *canon.split("/"))


def _sha256(p: str) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _move(src: str, dst: str) -> str:
    """搬一個檔：同磁碟 os.replace；跨磁碟複製→驗 sha→刪原。回 sha256 或 ""（同磁碟不算）。目的地的資料夾自動建。"""
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    try:
        os.replace(src, dst)
        return ""
    except OSError:
        pass
    shutil.copy2(src, dst)
    want, got = _sha256(src), _sha256(dst)
    if want != got:
        os.remove(dst)
        raise OSError("跨磁碟搬移後內容不一致：%s" % os.path.basename(src))
    os.remove(src)
    return want


def move_in(token: str, files: list) -> list:
    """把 files `[{root, rel}]` 搬進 `<根>/<token>/`。回 manifest `[{root, rel, size, sha256, state}]`；
    state＝`moved`｜`missing`（來源不存在：快照照記，還原時不搬）｜`invalid`（路徑不合法，不碰）。
    任何一個檔搬失敗 ⇒ 已搬的全部搬回去再丟 OSError（呼叫端據此中止，不刪資料列）。"""
    base = bin_dir(token)
    manifest, done = [], []
    try:
        for f in files or []:
            root, rel = str((f or {}).get("root") or ROOT_UPLOADS), str((f or {}).get("rel") or "")
            src = _src_abs(root, rel)
            ent = {"root": root, "rel": rel, "size": 0, "sha256": "", "state": "invalid"}
            if src is not None:
                if os.path.isfile(src):
                    ent["size"] = os.path.getsize(src)
                    dst = os.path.join(base, root, *rel.split("/"))
                    ent["sha256"] = _move(src, dst)
                    ent["state"] = "moved"
                    done.append((src, dst))
                else:
                    ent["state"] = "missing"
            manifest.append(ent)
    except Exception:
        stuck = []
        for src, dst in reversed(done):
            try:
                _move(dst, src)
            except OSError:
                stuck.append(dst)
                logger.exception("暫存區搬移失敗後搬回也失敗：%s", dst)
        if not stuck:                       # 全部都搬回去了才清掉資料夾；有搬不回的（防毒鎖檔…）⇒ 保留，每日工作 reconcile 會再搬回，絕不連檔案一起刪掉
            try:
                _remove_tree(base)
            except OSError:                 # 空資料夾清不掉不要蓋掉原本的錯誤（呼叫端要的是『搬進去失敗』的原因）
                logger.warning("暫存區搬移失敗後空資料夾清不掉：%s", base)
        raise
    return manifest


def _free_name(path: str) -> str:
    """目的地被占用 ⇒ 同資料夾加『(還原N)』後綴。"""
    if not os.path.exists(path):
        return path
    d, n = os.path.split(path)
    stem, ext = os.path.splitext(n)
    for i in range(1, 100):
        cand = os.path.join(d, "%s (還原%d)%s" % (stem, i, ext))
        if not os.path.exists(cand):
            return cand
    raise OSError("找不到可用的檔名：%s" % n)


def move_back(token: str, manifest: list, rename_on_conflict: bool = True) -> tuple:
    """把隔離區的檔搬回原路徑。回 `({(root, 原rel): 實際rel}, 失敗清單)`。state≠moved 的略過。
    原路徑被占用 ⇒ 加後綴（`rename_on_conflict=False` 時當失敗）。已搬回的檔在清單中失敗時**不**回頭搬走（呼叫端決定整體要不要 undo）。"""
    base = bin_dir(token)
    mapping, fails = {}, []
    for ent in manifest or []:
        if ent.get("state") != "moved":
            continue
        root, rel = ent["root"], ent["rel"]
        src = os.path.join(base, root, *rel.split("/"))
        dst = _src_abs(root, rel)
        if dst is None or not os.path.isfile(src):
            fails.append({"rel": rel, "why": "隔離區的檔不見了" if dst is not None else "原路徑不合法"})
            continue
        try:
            if os.path.exists(dst):
                if not rename_on_conflict:
                    fails.append({"rel": rel, "why": "原路徑已被占用"})
                    continue
                dst = _free_name(dst)
            _move(src, dst)
            actual = os.path.relpath(dst, _uploads.UPLOADS_ROOT).replace(os.sep, "/")
            mapping[(root, rel)] = actual
        except OSError as e:
            fails.append({"rel": rel, "why": str(e)})
    return mapping, fails


def stash_again(token: str, mapping: dict) -> list:
    """`move_back` 之後整體還原失敗 ⇒ 把剛搬回的檔再搬回隔離區（`mapping` 即 move_back 的回傳）。回失敗清單。"""
    base = bin_dir(token)
    fails = []
    for (root, rel), actual in (mapping or {}).items():
        src = _src_abs(root, actual)
        dst = os.path.join(base, root, *rel.split("/"))
        try:
            if src is not None and os.path.isfile(src):
                _move(src, dst)
        except OSError as e:
            fails.append({"rel": rel, "why": str(e)})
    return fails


def _remove_tree(path: str) -> None:
    """刪除一個隔離資料夾並**驗證它真的不見了**；刪不掉（檔案被占用）⇒ 丟 OSError（呼叫端不可以把這一筆標成已清除）。"""
    if not os.path.isdir(path):
        return
    if not _within(root_dir(), path) or os.path.normcase(os.path.realpath(path)) == os.path.normcase(os.path.realpath(root_dir())):
        raise ValueError("拒絕刪除隔離區以外的路徑：%s" % path)

    def _writable_retry(func, p, _exc):          # 唯讀檔：改權限再試一次
        try:
            os.chmod(p, 0o700)
            func(p)
        except OSError:
            pass
    shutil.rmtree(path, onerror=_writable_retry)       # TODO: Python 3.12+ 的 `onexc` 取代 `onerror`（onerror 已標記為棄用）；升到 3.12 再改
    if os.path.exists(path):
        raise OSError("隔離資料夾刪不掉（檔案可能被其他程式占用）：%s" % os.path.basename(path))


def remove(token: str) -> None:
    """永久刪除這一筆的隔離檔（整個資料夾）。刪不乾淨 ⇒ OSError。"""
    _remove_tree(bin_dir(token))


def location_problem(d: str) -> str:
    """隔離目錄設定值（非空）的位置規則；合格回 ""，否則回原因。
    必須是本機磁碟的絕對路徑；不可以是網路路徑（UNC）、磁碟機根目錄、系統目錄，也不可以等於／在／包含安裝根目錄
    （預設位置 `<uploads 的上一層>\資源回收筒` 是唯一在樹內的位置，用『留空』選它）。"""
    d = str(d or "").strip()
    if not os.path.isabs(d):
        return "隔離目錄必須是絕對路徑"
    if d.startswith("\\\\") or d.startswith("//"):
        return "隔離目錄不可以是網路路徑（UNC）"
    real = os.path.normcase(os.path.realpath(d))
    drive, tail = os.path.splitdrive(real)
    if tail.strip("\\/") == "":
        return "隔離目錄不可以是磁碟機根目錄"
    install = os.path.normcase(os.path.realpath(_install_root()))
    if real == install or real.startswith(install + os.sep):
        return "隔離目錄不可以在安裝目錄裡面（要放樹內請留空＝預設位置）"
    if install.startswith(real + os.sep):
        return "隔離目錄不可以包含安裝目錄"
    cloud = _cloud_problem(real)
    if cloud:
        return cloud
    for env in ("SystemRoot", "windir", "ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "ProgramData"):
        v = os.environ.get(env)
        if v:
            sysd = os.path.normcase(os.path.realpath(v))
            if real == sysd or real.startswith(sysd + os.sep):
                return "隔離目錄不可以在系統目錄（%s）底下" % os.path.basename(v)
    for unix in ("/etc", "/usr", "/bin", "/sbin", "/lib", "/boot", "/proc", "/sys", "/dev", "/var/lib"):
        if real == unix or real.startswith(unix + "/"):
            return "隔離目錄不可以在系統目錄底下"
    return ""


#: 路徑裡出現這些資料夾名稱 ⇒ 多半是雲端同步／共用資料夾（隔離檔含個資，F3 永不上雲）。不分大小寫。
_CLOUD_SEGMENTS = {"我的雲端硬碟", "共用雲端硬碟", "my drive", "shared drives", "google drive", "googledrive", "drive", "onedrive", "dropbox", "icloud", "iclouddrive",
                   "box", "box sync", "public", "公用", "sync", "mega", "pcloud drive"}


def _cloud_problem(real: str) -> str:
    """雲端鏡像／同步資料夾不可當隔離目錄：已設定的雲端存檔根目錄、個資資料夾、更新交付資料夾，以及路徑裡有常見雲端同步資料夾名稱（Google 雲端硬碟、OneDrive、Dropbox、Public…）。"""
    try:
        from helpers import storage_locations as SL
        for kind in SL.KINDS:
            try:
                root = SL.path(kind) or ""
            except Exception:                      # noqa: BLE001 — 讀不到設定不當成通過，下面的名稱規則還會擋
                root = ""
            if root:
                r = os.path.normcase(os.path.realpath(root))
                if real == r or real.startswith(r + os.sep) or r.startswith(real + os.sep):
                    return "隔離目錄不可以在（或包含）雲端存檔／個資／交付資料夾：%s" % SL.LABELS.get(kind, kind)
    except Exception:                              # noqa: BLE001
        pass
    for seg in os.path.normcase(real).replace("/", os.sep).split(os.sep):
        seg = seg.strip()
        if seg in _CLOUD_SEGMENTS or seg.startswith("onedrive") or seg.startswith("google drive"):
            return "隔離目錄不可以放在雲端同步資料夾底下（%s）——隔離檔含個資，永不上雲" % seg
    return ""


def _install_root() -> str:
    from core import paths
    return paths.INSTALL_ROOT


def used_bytes() -> tuple:
    """(總位元組, 檔案數)。隔離區不存在 ⇒ (0, 0)。"""
    total = n = 0
    base = root_dir()
    for d, _dirs, names in os.walk(base):
        for nm in names:
            try:
                total += os.path.getsize(os.path.join(d, nm))
                n += 1
            except OSError:
                pass
    return total, n


def free_bytes() -> int:
    base = root_dir()
    probe = base
    while probe and not os.path.exists(probe):
        nxt = os.path.dirname(probe)
        if nxt == probe:
            break
        probe = nxt
    try:
        return shutil.disk_usage(probe).free
    except OSError:
        return -1


def orphan_tokens(known: set) -> list:
    """隔離區裡有資料夾、但資料庫沒有對應列（交易回滾或當機留下）、且超過寬限時間的 token。"""
    base = root_dir()
    out = []
    if not os.path.isdir(base):
        return out
    now = time.time()
    for name in os.listdir(base):
        p = os.path.join(base, name)
        if _token_ok(name) and name not in known and os.path.isdir(p) and now - os.path.getmtime(p) > _ORPHAN_GRACE_SECONDS:
            out.append(name)
    return out


def existing_tokens(tokens) -> list:
    """給定的 token 裡，隔離區實際還有資料夾的那些。"""
    return [t for t in tokens if _token_ok(t) and os.path.isdir(bin_dir(t))]


def _collision_free(dst: str, token: str) -> str:
    """原路徑被占用時的替代檔名：`名稱.rb-<token前6碼>.副檔名`（仍重複就加序號）。"""
    stem, ext = os.path.splitext(dst)
    cand = "%s.rb-%s%s" % (stem, token[:6], ext)
    k = 1
    while os.path.exists(cand):
        k += 1
        cand = "%s.rb-%s-%d%s" % (stem, token[:6], k, ext)
    return cand


def restore_orphan(token: str) -> int:
    """孤兒資料夾 ⇒ 檔案搬回原路徑後移除資料夾。原路徑被占用（同名檔又被上傳了）⇒ 不覆蓋，改搬到不衝突的檔名並記 log
    （不再把資料夾永遠留在隔離區）。回搬回幾個檔。"""
    base = bin_dir(token)
    n = 0
    left = False
    for d, _dirs, names in os.walk(os.path.join(base, ROOT_UPLOADS)):
        for nm in names:
            src = os.path.join(d, nm)
            rel = os.path.relpath(src, os.path.join(base, ROOT_UPLOADS)).replace(os.sep, "/")
            dst = _src_abs(ROOT_UPLOADS, rel)
            if dst is not None:
                final = dst if not os.path.exists(dst) else _collision_free(dst, token)
                try:
                    _move(src, final)
                    n += 1
                    if final != dst:
                        logger.warning("孤兒隔離檔 %s 的原路徑已被占用，改存為 %s", dst, final)
                    continue
                except OSError:
                    logger.exception("孤兒隔離檔搬回失敗：%s", src)
            left = True
    if not left:
        _remove_tree(base)
    return n
