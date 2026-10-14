"""Turn the summary HTML into an Outlook draft (.eml) with its slide images embedded inline.

Usage: make_email.py <summary .html> [--attach <file>]...  -> <same name>.eml next to it (repeat --attach)
       make_email.py --standalone <report .html>         -> rewrites it in place with images as data: URIs
.eml:  Subject = the HTML <title>. Local <img src="relative/path.jpg">
files are attached as inline (cid:) parts, so pictures survive where copy-paste from a browser drops them.
Double-click the .eml: Outlook opens it as an editable unsent draft (X-Unsent: 1).
"""
import argparse
import base64
import html
import mimetypes
import re
import sys
from email.message import EmailMessage
from email.policy import SMTP
from email.utils import make_msgid
from pathlib import Path
from urllib.parse import unquote

IMG = re.compile(r'(<img\b[^>]*?\bsrc=")([^":]+)(")', re.I)  # relative paths only: skips http:, data:, cid:
TITLE = re.compile(r"<title>(.*?)</title>", re.I | re.S)


def local_image(html_path: Path, rel: str) -> Path:
    img = html_path.parent / unquote(rel)  # src may be URL-encoded (spaces -> %20)
    if not img.is_file():
        sys.exit(f"Image not found: {img}")
    return img


def standalone(html_path: Path) -> int:
    """Inline every local <img> as a data: URI so the single .html file can be attached/forwarded."""
    src = html_path.read_text(encoding="utf-8")
    n = 0

    def to_data(m):
        nonlocal n
        n += 1
        img = local_image(html_path, m.group(2))
        mime = mimetypes.guess_type(img.name)[0] or "image/jpeg"
        return f"{m.group(1)}data:{mime};base64,{base64.b64encode(img.read_bytes()).decode()}{m.group(3)}"

    html_path.write_text(IMG.sub(to_data, src), encoding="utf-8")
    return n


def build(html_path: Path, attach: list[Path] = ()) -> bytes:
    src = html_path.read_text(encoding="utf-8")
    cids = {}

    def to_cid(m):
        cids.setdefault(m.group(2), make_msgid())
        return f"{m.group(1)}cid:{cids[m.group(2)][1:-1]}{m.group(3)}"

    body = IMG.sub(to_cid, src)
    title = TITLE.search(src)
    msg = EmailMessage()
    msg["Subject"] = html.unescape(title.group(1).strip()) if title else html_path.stem
    msg["X-Unsent"] = "1"
    msg.set_content("This email is formatted in HTML.")
    msg.add_alternative(body, subtype="html")
    html_part = msg.get_payload()[1]
    for rel, cid in cids.items():
        img = local_image(html_path, rel)
        subtype = {"jpg": "jpeg"}.get(img.suffix[1:].lower(), img.suffix[1:].lower())
        html_part.add_related(img.read_bytes(), "image", subtype, cid=cid, filename=img.name)
    for f in attach:
        msg.add_attachment(f.read_bytes(), "text", "html", filename=f.name)
    return msg.as_bytes(policy=SMTP)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("html")
    ap.add_argument("--attach", action="append", default=[], help="file to attach; repeatable")
    ap.add_argument("--standalone", action="store_true", help="inline images into the .html instead of making an .eml")
    args = ap.parse_args()
    src = Path(args.html.strip().strip('"')).expanduser().resolve()
    if args.standalone:
        n = standalone(src)
        print(f"Standalone report: {src}  ({n} images inlined, {src.stat().st_size / 1e6:.1f} MB)")
        return
    attach = [Path(a.strip().strip('"')).expanduser().resolve() for a in args.attach]
    out = src.with_suffix(".eml")
    out.write_bytes(build(src, attach))
    print(f"Email draft: {out}  ({out.stat().st_size / 1e6:.1f} MB){'  + attached ' + ', '.join(a.name for a in attach) if attach else ''}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        import tempfile

        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            (d / "f x").mkdir()
            (d / "f x" / "a.jpg").write_bytes(b"\xff\xd8fake")
            (d / "s.html").write_text('<title>สรุป &amp; Budget</title><img src="f%20x/a.jpg"><img src="f%20x/a.jpg">'
                                      '<img src="https://x/y.png">', encoding="utf-8")
            raw = build(d / "s.html", attach=[d / "s.html", d / "f x" / "a.jpg"])
            assert standalone(d / "s.html") == 2
            inlined = (d / "s.html").read_text(encoding="utf-8")
            assert inlined.count("data:image/jpeg;base64,") == 2 and "https://x/y.png" in inlined
            assert standalone(d / "s.html") == 0  # idempotent: data: URIs are skipped
        assert b"X-Unsent: 1" in raw
        assert b'filename="s.html"' in raw and b'filename="a.jpg"' in raw and b"multipart/mixed" in raw
        assert raw.count(b"Content-ID:") == 1  # same image used twice -> attached once
        assert b"https://x/y.png" in raw and b"f%20x/a.jpg" not in raw.split(b"Content-ID")[0]
        print("selftest ok")
    else:
        main()
