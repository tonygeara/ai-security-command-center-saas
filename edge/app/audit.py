"""Audit log: who flew which drone, who changed what, and what the system did by itself.

Records live in the `audit` table of the app's database (store.py); rows are only ever added. Each
record carries the hash of the one before it, so editing or deleting a row breaks the chain and
verify() shows where.

Record: {"t", "user", "source", "action", "target", "detail", "result", "prev", "hash"}
    user    who did it ("" for the system itself)
    source  "dashboard", "telegram", "system" ...
"""
import csv
import hashlib
import io
import json
import time

GENESIS = "0" * 64
SECRET_WORDS = ("password", "token", "secret", "key", "hash")
RETENTION_DAYS = 365  # older records are pruned; the chain restarts from the first one kept


def _digest(prev, record):
    body = {k: record[k] for k in ("t", "user", "source", "action", "target", "detail", "result")}
    return hashlib.sha256((prev + json.dumps(body, sort_keys=True, ensure_ascii=False)).encode("utf-8")).hexdigest()


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


def _row(r):
    try:
        detail = json.loads(r["detail"] or "{}")
    except ValueError:
        detail = {}
    return {"id": r["id"], "t": r["t"], "user": r["user"] or "", "source": r["source"] or "", "action": r["action"] or "",
            "target": r["target"] or "", "detail": detail, "result": r["result"] or "", "prev": r["prev"], "hash": r["hash"]}


def record(store, action, user="", source="dashboard", target="", detail=None, result="ok"):
    rec = {"t": round(time.time(), 3), "user": str(user or ""), "source": str(source or ""),
           "action": str(action)[:120], "target": str(target or "")[:80], "detail": redact(detail or {}),
           "result": str(result or "")[:200]}
    with store.lock:
        last = store.q("SELECT hash FROM audit ORDER BY id DESC LIMIT 1")
        rec["prev"] = last[0]["hash"] if last else (store.meta("audit_chain_start") or GENESIS)
        rec["hash"] = _digest(rec["prev"], rec)
        store.x("INSERT INTO audit(t, user, source, action, target, detail, result, prev, hash) VALUES(?,?,?,?,?,?,?,?,?)",
                (rec["t"], rec["user"], rec["source"], rec["action"], rec["target"],
                 json.dumps(rec["detail"], ensure_ascii=False), rec["result"], rec["prev"], rec["hash"]))
    return rec


def read(store, limit=500, since=0.0):
    """Newest first."""
    return [_row(r) for r in store.q("SELECT * FROM audit WHERE t >= ? ORDER BY id DESC LIMIT ?", (since, int(limit)))]


def verify(store):
    """(ok, records checked, position of the first broken record or 0)."""
    with store.lock:
        rows = store.q("SELECT * FROM audit ORDER BY id")
        prev = store.meta("audit_chain_start") or GENESIS
    for n, r in enumerate(rows, 1):
        rec = _row(r)
        if rec["prev"] != prev or _digest(prev, rec) != rec["hash"]:
            return False, n - 1, n
        prev = rec["hash"]
    return True, len(rows), 0


def prune(store, days=RETENTION_DAYS):
    """Drop records older than `days`; the first record kept becomes the new start of the chain."""
    with store.lock:
        cutoff = time.time() - days * 86400
        old = store.q("SELECT COUNT(*) AS n FROM audit WHERE t < ?", (cutoff,))[0]["n"]
        if not old:
            return 0
        last_old = store.q("SELECT hash FROM audit WHERE t < ? ORDER BY id DESC LIMIT 1", (cutoff,))[0]["hash"]
        store.x("DELETE FROM audit WHERE t < ?", (cutoff,))
        store.meta("audit_chain_start", last_old)  # the next record kept (or written) follows on from it
        return old


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
