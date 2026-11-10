"""SIA DC-09 over TCP: how alarm panels report to an alarm-receiving (monitoring) centre over IP.

Messages use the Contact ID ("ADM-CID") format, unencrypted:

    <LF><crc><0LLL>"ADM-CID"<seq>R<receiver>L<line>#<account>[#<account>|<Q><EEE> <GG> <ZZZ>]_<HH:MM:SS,MM-DD-YYYY><CR>

    crc   CRC-16 (ARC) of everything from the first quote to the end of the timestamp, 4 hex digits
    0LLL  "0" and the length of that same part, 3 hex digits
    Q     1 = new event, 3 = restore;  EEE = Contact ID event code;  GG = partition;  ZZZ = zone
The receiver answers with an "ACK" (or "NAK") message.

Event codes used here: 130 burglary (verified intrusion), 139 burglary verified (some centres use it for
"confirmed by a second sensor"), 380 trouble/unconfirmed. Ask the monitoring centre which codes, account,
receiver and line numbers they want, and whether they need DC-09 encryption (not supported here).
"""
import socket
import time

CODES = {"verified": 130, "verified_alt": 139, "unconfirmed": 380}


def crc16_arc(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return crc


def body(account, event_code, zone=1, partition=1, seq=1, receiver="", line="0", restore=False, now=None):
    account = "".join(c for c in str(account) if c.isalnum())[:16] or "0000"
    ts = time.strftime("_%H:%M:%S,%m-%d-%Y", time.gmtime(time.time() if now is None else now))
    data = f"[#{account}|{3 if restore else 1}{int(event_code):03d} {int(partition):02d} {int(zone):03d}]"
    rcv = f"R{receiver}" if str(receiver).strip() else ""
    return f'"ADM-CID"{int(seq) % 10000:04d}{rcv}L{line or 0}#{account}{data}{ts}'


def frame(msg: str) -> bytes:
    raw = msg.encode("ascii")
    return b"\n" + f"{crc16_arc(raw):04X}0{len(raw):03X}".encode() + raw + b"\r"


def parse(frame_bytes: bytes):
    """(ok, message) for a received frame: checks the CRC and length."""
    s = frame_bytes.strip(b"\n\r")
    if len(s) < 8:
        return False, ""
    crc, length, msg = s[:4], s[5:8], s[8:]
    try:
        ok = int(crc, 16) == crc16_arc(msg) and int(length, 16) == len(msg) and s[4:5] == b"0"
    except ValueError:
        return False, ""
    return ok, msg.decode("ascii", "replace")


def send(host, port, account, event_code, zone=1, partition=1, seq=1, receiver="", line="0", timeout=10, now=None):
    """Send one event; returns (ok, reply text). ok only when the receiver ACKs it."""
    msg = frame(body(account, event_code, zone, partition, seq, receiver, line, now=now))
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        s.sendall(msg)
        s.settimeout(timeout)
        reply = b""
        while not reply.endswith(b"\r") and len(reply) < 1024:
            chunk = s.recv(1024)
            if not chunk:
                break
            reply += chunk
    good, text = parse(reply)
    return good and '"ACK"' in text, text or reply.decode("ascii", "replace")
