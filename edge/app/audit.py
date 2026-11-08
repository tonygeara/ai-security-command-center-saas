"""Audit log: who flew which drone, who changed what, and what the system did by itself.

One JSON record per line (audit_log.jsonl), never rewritten. Each record carries the hash of the one
before it, so editing or deleting a line breaks the chain and verify() shows where.

Record: {"t", "user", "source", "action", "target", "detail", "result", "prev", "hash"}
    user    who did it ("" for the system itself)
    source  "dashboard", "telegram", "auto", "scheduler", "safety" ...
"""
import csv
import hashlib
import io
import json
import os
import threading
import time

GENESIS = "0" * 64
SECRET_WORDS = ("password", "token", "secret", "key", "hash")
_lock = threading.Lock()
_last = {}  # path -> hash of the last record (so each write doesn't re-read the file)


def _digest(prev, record):
    body = {k: record[k] for k in ("t", "user", "source", "action", "target", "detail", "result")}
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


def _tail_hash(path):
    if path in _last:
        return _last[path]
    prev = GENESIS
    try:
        with open(path, "rb") as f:
            f.seek(0, os.SEEK_END)
            size = f.tell()
            f.seek(max(0, size - 65536))
            lines = [x for x in f.read().splitlines() if x.strip()]
        if lines:
            prev = json.loads(lines[-1].decode("utf-8")).get("hash") or GENESIS
    except (OSError, ValueError):
        pass
    _last[path] = prev
    return prev


def redact(value, depth=0):
    """A short, safe copy of request data: secrets removed, long values cut."""
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        return {str(k)[:40]: ("•••" if any(w in str(k).lower() for w in SECRET_WORDS) else redact(v, depth + 1))
                for k, v in list(value.items())[:20]}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value[:10]] + (["…"] if len(value) > 10 else [])
    if isinstance(value, str):
        return value[:120]
    return value


def record(path, action, user="", source="dashboard", target="", detail=None, result="ok"):
    rec = {"t": round(time.time(), 3), "user": str(user or ""), "source": str(source or ""),
           "action": str(action)[:120], "target": str(target or "")[:80], "detail": redact(detail or {}),
           "result": str(result or "")[:200]}
    with _lock:
        prev = _tail_hash(path)
        rec["prev"] = prev
        rec["hash"] = _digest(prev, rec)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        _last[path] = rec["hash"]
    return rec


def read(path, limit=500, since=0.0):
    """Newest first."""
    rows = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                if r.get("t", 0) >= since:
                    rows.append(r)
    except OSError:
        return []
    return rows[::-1][:limit]


def verify(path):
    """(ok, records checked, line number of the first broken record or 0)."""
    prev, n = GENESIS, 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            for n, line in enumerate(f, 1):
                try:
                    r = json.loads(line)
                except ValueError:
                    return False, n - 1, n
                if r.get("prev") != prev or _digest(prev, r) != r.get("hash"):
                    return False, n - 1, n
                prev = r["hash"]
    except OSError:
        return True, 0, 0
    return True, n, 0


def _cell(v):
    v = str(v)
    return "'" + v if v[:1] in ("=", "+", "-", "@") else v  # spreadsheets must not run it as a formula


def to_csv(rows):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["time", "user", "source", "action", "target", "result", "detail"])
    for r in rows:
        w.writerow([time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r["t"]))] + [_cell(v) for v in (
            r["user"], r["source"], r["action"], r["target"], r["result"], json.dumps(r.get("detail") or {}, ensure_ascii=False))])
    return out.getvalue()
