"""A very small PDF writer (no extra dependency): A4 pages with text in the standard Helvetica fonts, filled
rectangles and lines. Enough for the scheduled reports (reports.py). Text outside Windows-1252 shows as "?"."""
import zlib

A4 = (595.28, 841.89)  # points


def _esc(text):
    raw = str(text).encode("cp1252", "replace")
    return raw.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)").replace(b"\r", b"").replace(b"\n", b" ")


def _rgb(c):
    """'#rrggbb' -> 'r g b' (0..1)."""
    c = c.lstrip("#")
    return " ".join(f"{int(c[i:i + 2], 16) / 255:.3f}" for i in (0, 2, 4))


# Helvetica / Helvetica-Bold widths of the printable ASCII characters (1/1000 em), for text measuring.
_HV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
       278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722,
       667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500,
       222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584]
_HVB = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
        333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722,
        667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556,
        278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584]


def text_width(text, size, bold=False):
    w = _HVB if bold else _HV
    return sum(w[ord(ch) - 32] if 32 <= ord(ch) < 127 else 556 for ch in str(text)) * size / 1000


def wrap(text, size, width, bold=False):
    """Split text into lines no wider than width points."""
    lines = []
    for para in str(text).split("\n"):
        line = ""
        for word in para.split(" "):
            test = (line + " " + word).strip()
            if line and text_width(test, size, bold) > width:
                lines.append(line)
                line = word
            else:
                line = test
        lines.append(line)
    return lines


class Pdf:
    def __init__(self, title="Report", author=""):
        self.title, self.author = title, author
        self.pages = []
        self.ops = None
        self.add_page()

    @property
    def width(self):
        return A4[0]

    @property
    def height(self):
        return A4[1]

    def add_page(self):
        self.ops = []
        self.pages.append(self.ops)

    # Coordinates are from the TOP left (y grows downwards), which is easier for laying out a report.
    def text(self, x, y, text, size=10, bold=False, color="#1b2a35", align="left"):
        if align != "left":
            w = text_width(text, size, bold)
            x = x - w if align == "right" else x - w / 2
        self.ops.append(b"BT /%s %.1f Tf %s rg %.2f %.2f Td (%s) Tj ET" % (
            b"F2" if bold else b"F1", size, _rgb(color).encode(), x, self.height - y, _esc(text)))

    def rect(self, x, y, w, h, fill="#e8f0f7", stroke=None):
        op = b"%s rg " % _rgb(fill).encode() if fill else b""
        if stroke:
            op += b"%s RG 0.6 w " % _rgb(stroke).encode()
        op += b"%.2f %.2f %.2f %.2f re %s" % (x, self.height - y - h, w, h, b"B" if fill and stroke else b"f" if fill else b"S")
        self.ops.append(op)

    def line(self, x1, y1, x2, y2, color="#bfcfdd", width=0.6):
        self.ops.append(b"%s RG %.2f w %.2f %.2f m %.2f %.2f l S" % (_rgb(color).encode(), width, x1, self.height - y1, x2, self.height - y2))

    def output(self):
        objs = []

        def add(body):
            objs.append(body)
            return len(objs)

        f1 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>")
        f2 = add(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>")
        pages_id = len(objs) + 1 + 2 * len(self.pages)  # filled in after the page objects
        kids = []
        for ops in self.pages:
            data = zlib.compress(b"\n".join(ops))
            content = add(b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream")
            kids.append(add(b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 %.2f %.2f] /Contents %d 0 R "
                            b"/Resources << /Font << /F1 %d 0 R /F2 %d 0 R >> >> >>" % (pages_id, A4[0], A4[1], content, f1, f2)))
        add(b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % k for k in kids), len(kids)))
        info = add(b"<< /Title (%s) /Author (%s) /Producer (AI Security Command Center) >>" % (_esc(self.title), _esc(self.author)))
        root = add(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_id)
        out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
        offsets = []
        for i, body in enumerate(objs, 1):
            offsets.append(len(out))
            out += b"%d 0 obj\n" % i + body + b"\nendobj\n"
        xref = len(out)
        out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
        out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
        out += b"trailer\n<< /Size %d /Root %d 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, root, info, xref)
        return bytes(out)
