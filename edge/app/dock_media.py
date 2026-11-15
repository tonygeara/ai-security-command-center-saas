"""Photos and videos from DJI Docks (DJI Cloud API, Phase 5): a small S3-compatible receiver on this PC.

The dock asks where to upload (storage_config_get); the PC answers with this receiver's address (LAN port 8769), a
bucket and keys made on this PC. The dock uploads with an ordinary S3 client (one PUT, or multipart for big videos),
then reports each file (file_upload_callback). Files land in the data folder (dock-media/files), are listed in
dock-media/index.json and appear on the Drone page; alarm launches send their first photo to Telegram.

Only what a dock needs is implemented: HEAD/GET bucket, PUT object, multipart upload (create, part, complete,
abort), GET/HEAD object. Every request must carry a valid AWS Signature V4 for our keys (header auth); for streaming
uploads (aws-chunked) the seed signature is checked and the chunk framing removed.
"""
import datetime
import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import threading
import time
import urllib.parse
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from xml.sax.saxutils import escape

PORT = 8769
BUCKET = "dock-media"
REGION = "us-east-1"
MAX_OBJECT = 8 * 1024 ** 3        # 8 GB per file
MIN_FREE = 2 * 1024 ** 3          # keep 2 GB free on the disk
KEEP_DAYS = 30
SAFE_KEY = re.compile(r"^[\w\-./ ()]{1,400}$")


# ---------- keys and the index ----------

class MediaStore:
    def __init__(self, folder):
        self.folder = folder
        self.files = os.path.join(folder, "files")
        self.parts = os.path.join(folder, "parts")
        os.makedirs(self.files, exist_ok=True)
        os.makedirs(self.parts, exist_ok=True)
        self.lock = threading.Lock()
        creds_path = os.path.join(folder, "credentials.json")
        creds = _read_json(creds_path)
        if not (creds.get("access_key") and creds.get("secret_key")):
            creds = {"access_key": "AISEC" + secrets.token_hex(8).upper(), "secret_key": secrets.token_urlsafe(30)}
            _write_json(creds_path, creds)
        self.access_key, self.secret_key = creds["access_key"], creds["secret_key"]
        self.index_path = os.path.join(folder, "index.json")
        self.items = _read_json(self.index_path).get("items") or []

    def path_for(self, key):
        p = os.path.normpath(os.path.join(self.files, key))
        if not p.startswith(os.path.normpath(self.files) + os.sep):
            raise ValueError("bad key")
        return p

    def disk_ok(self, size=0):
        try:
            return shutil.disk_usage(self.files).free - size > MIN_FREE
        except OSError:
            return True

    def add(self, item):
        """A file the dock reported: {"key", "dock", "name", "kind", "flight_id", "lat", "lon", "taken", ...}."""
        with self.lock:
            self.items = [x for x in self.items if x["key"] != item["key"]] + [{"id": uuid.uuid4().hex[:12], "added": time.time(), **item}]
            self.items = self.items[-5000:]
            _write_json(self.index_path, {"items": self.items})
            return self.items[-1]

    def get(self, mid):
        return next((x for x in self.items if x["id"] == mid), None)

    def recent(self, n=40, dock=None):
        return [x for x in reversed(self.items) if dock is None or x.get("dock") == dock][:n]

    def prune(self, days=KEEP_DAYS, now=None):
        """Delete files older than `days` (and their index rows). Returns how many went."""
        cut = (now or time.time()) - days * 86400
        with self.lock:
            old = [x for x in self.items if x.get("added", 0) < cut]
            for x in old:
                try:
                    os.remove(self.path_for(x["key"]))
                except (OSError, ValueError):
                    pass
            self.items = [x for x in self.items if x.get("added", 0) >= cut]
            _write_json(self.index_path, {"items": self.items})
        return len(old)

    def storage_config(self, host, prefix):
        """What the dock is told in answer to storage_config_get (DJI Cloud API)."""
        return {"bucket": BUCKET, "endpoint": f"http://{host}:{PORT}", "provider": "minio", "region": REGION,
                "object_key_prefix": prefix,
                "credentials": {"access_key_id": self.access_key, "access_key_secret": self.secret_key,
                                "expire": 3600, "security_token": ""}}


def media_kind(name):
    ext = os.path.splitext(str(name).lower())[1]
    return "photo" if ext in (".jpg", ".jpeg", ".png", ".dng") else "video" if ext in (".mp4", ".mov") else "file"


# ---------- AWS Signature V4 ----------

def _uri_encode(s, slash=True):
    return urllib.parse.quote(s, safe="-_.~" + ("/" if slash else ""))


def signature_v4(secret, method, raw_path, query, headers, signed, payload_hash, amz_date, scope):
    canonical_query = "&".join(f"{_uri_encode(k, False)}={_uri_encode(v, False)}"
                               for k, v in sorted(urllib.parse.parse_qsl(query, keep_blank_values=True)))
    canonical_headers = "".join(f"{h}:{' '.join(str(headers.get(h, '')).split())}\n" for h in signed)
    canonical = "\n".join([method, raw_path or "/", canonical_query, canonical_headers, ";".join(signed), payload_hash])
    to_sign = "\n".join(["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(canonical.encode()).hexdigest()])
    date, region, service, _ = scope.split("/")
    k = hmac.new(("AWS4" + secret).encode(), date.encode(), hashlib.sha256).digest()
    for part in (region, service, "aws4_request"):
        k = hmac.new(k, part.encode(), hashlib.sha256).digest()
    return hmac.new(k, to_sign.encode(), hashlib.sha256).hexdigest()


def sign_headers(access_key, secret, method, url, body=b"", now=None):
    """Headers for a signed S3 request (used by the simulated dock and the tests)."""
    u = urllib.parse.urlsplit(url)
    t = now or datetime.datetime.now(datetime.timezone.utc)
    amz_date, date = t.strftime("%Y%m%dT%H%M%SZ"), t.strftime("%Y%m%d")
    payload = hashlib.sha256(body).hexdigest()
    headers = {"host": u.netloc, "x-amz-content-sha256": payload, "x-amz-date": amz_date}
    signed = sorted(headers)
    scope = f"{date}/{REGION}/s3/aws4_request"
    sig = signature_v4(secret, method, u.path, u.query, headers, signed, payload, amz_date, scope)
    return {**headers, "Authorization": f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, SignedHeaders={';'.join(signed)}, Signature={sig}"}


_AUTH = re.compile(r"AWS4-HMAC-SHA256\s+Credential=([^/]+)/([^,]+),\s*SignedHeaders=([^,]+),\s*Signature=([0-9a-f]+)")


def check_signature(store, method, raw_path, query, headers):
    """'' when the request is signed with our keys, else why not."""
    m = _AUTH.match(headers.get("authorization", ""))
    if not m:
        return "missing signature"
    access, scope, signed, sig = m.group(1), m.group(2), m.group(3).split(";"), m.group(4)
    if not hmac.compare_digest(access, store.access_key):
        return "unknown access key"
    amz_date = headers.get("x-amz-date", "")
    try:
        when = datetime.datetime.strptime(amz_date, "%Y%m%dT%H%M%SZ").replace(tzinfo=datetime.timezone.utc)
    except ValueError:
        return "bad date"
    if abs((datetime.datetime.now(datetime.timezone.utc) - when).total_seconds()) > 900:
        return "clock skew"
    want = signature_v4(store.secret_key, method, raw_path, query, headers, signed,
                        headers.get("x-amz-content-sha256", "UNSIGNED-PAYLOAD"), amz_date, scope)
    return "" if hmac.compare_digest(want, sig) else "signature does not match"


def _dechunk(data):
    """aws-chunked body: '<hex size>;chunk-signature=...\\r\\n<data>\\r\\n' ... '0;...\\r\\n\\r\\n' -> data."""
    out, i = bytearray(), 0
    while i < len(data):
        j = data.index(b"\r\n", i)
        size = int(data[i:j].split(b";")[0], 16)
        if size == 0:
            break
        out += data[j + 2:j + 2 + size]
        i = j + 2 + size + 2
    return bytes(out)


# ---------- the receiver ----------

def _xml(tag, inner):
    return f'<?xml version="1.0" encoding="UTF-8"?><{tag} xmlns="http://s3.amazonaws.com/doc/2006-03-01/">{inner}</{tag}>'.encode()


def start_server(store, on_object=None, port=PORT, bind="0.0.0.0"):
    """Run the receiver; on_object(key, size) is called when a file is complete."""

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass

        def _reply(self, code, body=b"", ctype="application/xml", extra=None):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            for k, v in (extra or {}).items():
                self.send_header(k, v)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(body)

        def _error(self, code, s3code, msg):
            self.close_connection = True  # an unread body may follow: never read it as the next request
            self._reply(code, _xml("Error", f"<Code>{s3code}</Code><Message>{escape(msg)}</Message>"), extra={"Connection": "close"})

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_OBJECT:
                raise ValueError("too big")
            data = self.rfile.read(n) if n else b""
            sha = self.headers.get("x-amz-content-sha256", "")
            if sha.startswith("STREAMING-") or "aws-chunked" in (self.headers.get("Content-Encoding") or ""):
                return _dechunk(data)
            if sha and sha not in ("UNSIGNED-PAYLOAD",) and hashlib.sha256(data).hexdigest() != sha:
                raise ValueError("payload hash")
            return data

        def _route(self):
            u = urllib.parse.urlsplit(self.path)
            hdrs = {k.lower(): v for k, v in self.headers.items()}
            why = check_signature(store, self.command, u.path, u.query, hdrs)
            if why:
                self._error(403, "SignatureDoesNotMatch" if "signature" in why else "AccessDenied", why)
                return None
            parts = urllib.parse.unquote(u.path).lstrip("/").split("/", 1)
            if parts[0] != BUCKET:
                self._error(404, "NoSuchBucket", "unknown bucket")
                return None
            key = parts[1] if len(parts) > 1 else ""
            if key and (not SAFE_KEY.match(key) or ".." in key.split("/")):
                self._error(400, "InvalidArgument", "bad key")
                return None
            return key, dict(urllib.parse.parse_qsl(u.query, keep_blank_values=True))

        def do_HEAD(self):  # noqa: N802
            self.do_GET()

        def do_GET(self):  # noqa: N802
            r = self._route()
            if r is None:
                return
            key, q = r
            if not key:  # bucket: exists / location
                return self._reply(200, _xml("LocationConstraint", "") if "location" in q else b"")
            try:
                with open(store.path_for(key), "rb") as f:
                    data = f.read()
            except (OSError, ValueError):
                return self._error(404, "NoSuchKey", "not found")
            self._reply(200, data, "application/octet-stream", {"ETag": f'"{hashlib.md5(data).hexdigest()}"'})

        def do_PUT(self):  # noqa: N802
            r = self._route()
            if r is None:
                return
            key, q = r
            if not key:
                return self._reply(200)  # create bucket: it always exists
            if not store.disk_ok(int(self.headers.get("Content-Length") or 0)):
                return self._error(507, "InsufficientStorage", "the PC's disk is nearly full")
            try:
                data = self._body()
            except ValueError as e:
                return self._error(400, "BadDigest" if "hash" in str(e) else "EntityTooLarge", str(e))
            etag = f'"{hashlib.md5(data).hexdigest()}"'
            if "uploadId" in q and "partNumber" in q:
                d = os.path.join(store.parts, re.sub(r"[^\w-]", "", q["uploadId"]))
                if not os.path.isdir(d):
                    return self._error(404, "NoSuchUpload", "unknown upload")
                with open(os.path.join(d, f"{int(q['partNumber']):05d}"), "wb") as f:
                    f.write(data)
                return self._reply(200, extra={"ETag": etag})
            path = store.path_for(key)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path + ".part", "wb") as f:
                f.write(data)
            os.replace(path + ".part", path)
            self._reply(200, extra={"ETag": etag})
            if on_object:
                on_object(key, len(data))

        def do_POST(self):  # noqa: N802
            r = self._route()
            if r is None:
                return
            key, q = r
            if "uploads" in q:  # start a multipart upload
                uid = uuid.uuid4().hex
                os.makedirs(os.path.join(store.parts, uid))
                with open(os.path.join(store.parts, uid, "key"), "w", encoding="utf-8") as f:
                    f.write(key)
                return self._reply(200, _xml("InitiateMultipartUploadResult",
                                             f"<Bucket>{BUCKET}</Bucket><Key>{escape(key)}</Key><UploadId>{uid}</UploadId>"))
            if "uploadId" in q:  # complete it: parts in the order listed
                self._body()
                d = os.path.join(store.parts, re.sub(r"[^\w-]", "", q["uploadId"]))
                if not os.path.isdir(d):
                    return self._error(404, "NoSuchUpload", "unknown upload")
                path = store.path_for(key)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                md5s, size = [], 0
                with open(path + ".part", "wb") as out:
                    for name in sorted(n for n in os.listdir(d) if n.isdigit()):
                        with open(os.path.join(d, name), "rb") as f:
                            chunk = f.read()
                        md5s.append(hashlib.md5(chunk).digest())
                        size += len(chunk)
                        out.write(chunk)
                os.replace(path + ".part", path)
                shutil.rmtree(d, ignore_errors=True)
                etag = f'"{hashlib.md5(b"".join(md5s)).hexdigest()}-{len(md5s)}"'
                self._reply(200, _xml("CompleteMultipartUploadResult",
                                      f"<Bucket>{BUCKET}</Bucket><Key>{escape(key)}</Key><ETag>{escape(etag)}</ETag>"))
                if on_object:
                    on_object(key, size)
                return None
            self._error(400, "InvalidRequest", "not supported")

        def do_DELETE(self):  # noqa: N802
            r = self._route()
            if r is None:
                return
            key, q = r
            if "uploadId" in q:
                shutil.rmtree(os.path.join(store.parts, re.sub(r"[^\w-]", "", q["uploadId"])), ignore_errors=True)
            elif key:
                try:
                    os.remove(store.path_for(key))
                except (OSError, ValueError):
                    pass
            self._reply(204)

    server = ThreadingHTTPServer((bind, port), Handler)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, name="dock-media", daemon=True).start()
    return server


def _read_json(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=1)
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.2)
