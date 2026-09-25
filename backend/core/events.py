# -*- coding: utf-8 -*-
"""L1 事件匯流排（CUSTOMIZATION-SPEC §6，ROADMAP P6）。

事件＝「發生了一件事」的通知：發佈方不在乎誰聽、沒有訂閱者是正常情況。
需要回傳或需要同一個交易內一起寫的，走 provider（core.registry），不走事件。

- 宣告：`declare(name, owner, version, fields)`——宣告就是契約，會進能力目錄（P1）。
- 發佈：`publish(name, payload)`——**在發佈方 commit 之後呼叫**。
- 訂閱：`subscribe(name, handler, subscriber=<模組 key>)`——模組匯入時登記；模組沒載入就沒有訂閱。
- 隔離：訂閱者丟例外不影響發佈方與其他訂閱者；失敗記 ERROR 並留在 recent_failures()。
"""
import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Tuple

_log = logging.getLogger("motrix.events")


@dataclass(frozen=True)
class EventDecl:
    name: str
    owner: str
    version: int
    fields: Tuple[str, ...]
    description: str = ""


_lock = threading.Lock()
_DECLS: Dict[str, EventDecl] = {}
_SUBS: Dict[str, List[Tuple[str, Callable]]] = {}
_FAILURES: deque = deque(maxlen=200)


def _strict() -> bool:
    # 與 core.txn.strict_db_guards 同一個旗標：測試環境 raise，產品記 ERROR 照送
    return os.environ.get("MOTRIX_STRICT_DB_GUARDS") == "1"


def declare(name: str, owner: str, version: int, fields, description: str = "") -> EventDecl:
    """宣告事件。同名重複宣告必須完全相同（兩份契約在搶同一個名字 ⇒ 直接報錯）。"""
    d = EventDecl(name, owner, int(version), tuple(fields), description)
    with _lock:
        old = _DECLS.get(name)
        if old is not None and old != d:
            raise ValueError(f"事件 {name} 已被宣告為不同的契約：{old} ≠ {d}")
        _DECLS[name] = d
    return d


def subscribe(name: str, handler: Callable[[dict], None], subscriber: str) -> None:
    """訂閱事件（事件不必已宣告：宣告方模組可能還沒載入或根本沒裝）。同一訂閱者重複登記同一函式不會重複執行。"""
    with _lock:
        subs = _SUBS.setdefault(name, [])
        if not any(s == subscriber and h is handler for s, h in subs):
            subs.append((subscriber, handler))


def declarations() -> List[EventDecl]:
    with _lock:
        return sorted(_DECLS.values(), key=lambda d: d.name)


def subscribers(name: str) -> List[str]:
    with _lock:
        return [s for s, _ in _SUBS.get(name, [])]


def recent_failures() -> List[dict]:
    with _lock:
        return list(_FAILURES)


def _contract_problem(name: str, payload: dict):
    d = _DECLS.get(name)
    if d is None:
        return f"發佈了沒有宣告的事件 {name}"
    missing = [f for f in d.fields if f not in (payload or {})]
    if missing:
        return f"事件 {name} 的 payload 缺少宣告的欄位：{missing}"
    return None


def publish(name: str, payload: dict) -> int:
    """依登記順序送給所有訂閱者；回傳成功送達的訂閱者數。訂閱者失敗不外拋。"""
    with _lock:
        problem = _contract_problem(name, payload)
        subs = list(_SUBS.get(name, []))
    if problem:
        if _strict():
            raise ValueError(problem)
        _log.error(problem)
    delivered = 0
    for subscriber, handler in subs:
        try:
            handler(dict(payload or {}))          # 給副本：訂閱者改 payload 不影響下一個訂閱者
            delivered += 1
        except Exception as e:                     # noqa: BLE001  隔離：一個訂閱者壞掉不可以拖垮其他人
            rec = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "event": name,
                   "subscriber": subscriber, "error": f"{type(e).__name__}: {e}"}
            with _lock:
                _FAILURES.append(rec)
            _log.exception("事件 %s 的訂閱者 %s 失敗", name, subscriber)
    return delivered


# ── 測試用：保存與還原（不要在測試裡自己列舉內部表，A 在 registry 踩過同一個坑）──────
def snapshot():
    with _lock:
        return (dict(_DECLS), {k: list(v) for k, v in _SUBS.items()}, list(_FAILURES))


def restore(state):
    decls, subs, fails = state
    with _lock:
        _DECLS.clear(); _DECLS.update(decls)
        _SUBS.clear(); _SUBS.update({k: list(v) for k, v in subs.items()})
        _FAILURES.clear(); _FAILURES.extend(fails)
