"""The made-up firmware build: writes the image and a `size` report (Berkeley format) beside it.

--fault builds an image with a device-only bug; --bloat adds a large table so the flash budget gate fails."""
import argparse
import hashlib
import pathlib

ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
ap.add_argument("--fault", type=int, default=None, help="tick from which the device's output is off by one")
ap.add_argument("--bloat", action="store_true")
a = ap.parse_args()
out = pathlib.Path(a.out)
out.mkdir(parents=True, exist_ok=True)
src = (pathlib.Path(__file__).parent / "ctl.py").read_bytes()
image = b"FERNHILL-IMG\n" + (f"fault={a.fault}\n".encode() if a.fault is not None else b"") + src
(out / "app.img").write_bytes(image)
text, data, bss = 96_000 + (500_000 if a.bloat else 0), 2_048, 18_000
(out / "size.txt").write_text(f"   text    data     bss     dec     hex filename\n"
                              f"  {text}    {data}   {bss}  {text + data + bss}  {text + data + bss:x} build/app.elf\n")
print("built", out / "app.img", hashlib.sha256(image).hexdigest()[:12])
