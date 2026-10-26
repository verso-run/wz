"""The approval page: one phone-sized page listing what waits for the owner's sign.

`wz approve serve` (owner's shell only) serves it on 127.0.0.1 by default. Reach it from a phone through your own
private network (a VPN or an SSH tunnel); never expose it to the open internet. Each card shows what will happen,
why, and the exact command or commit; Sign and Deny need the PIN. The page holds no tokens and runs nothing: a
sign writes the same write-once file `wz sign approve` writes, and `wz sign run` (or the lead) performs the act.
"""
from __future__ import annotations

import html
import secrets
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import approvals

CSS = """body{font:16px/1.4 system-ui,sans-serif;margin:0;padding:12px;max-width:640px;background:#fafafa;color:#111}
h1{font-size:20px}.card{background:#fff;border:1px solid #ddd;border-radius:10px;padding:12px;margin:12px 0}
pre{white-space:pre-wrap;word-break:break-word;background:#f3f3f3;padding:8px;border-radius:6px;font-size:13px}
input[type=password]{font-size:20px;width:9em;padding:6px}button{font-size:18px;padding:8px 16px;margin:6px 6px 0 0}
.muted{color:#666;font-size:13px}.ok{color:#05612d}.bad{color:#9b1c1c}"""


def _page(title: str, body: str) -> bytes:
    return (f"<!doctype html><html><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
            f"<title>{html.escape(title)}</title><style>{CSS}</style></head><body>{body}</body></html>").encode()


def make_handler(cfg, csrf: str):
    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, code: int, body: bytes):
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Content-Security-Policy", "default-src 'none'; style-src 'unsafe-inline'; form-action 'self'")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if urllib.parse.urlparse(self.path).path != "/":
                return self._send(404, _page("not found", "<p>not found</p>"))
            cards = []
            for r in approvals.pending(cfg):
                what = r.get("command") or f"{r['action'].get('type')} {r['action'].get('store', '')} -> {r['action'].get('sha', '')}"
                cards.append(
                    f"<div class=card><b>{html.escape(r['what'])}</b><div class=muted>{html.escape(r['id'])} · asked by "
                    f"{html.escape(r.get('by', ''))} · {html.escape(r.get('created', ''))}"
                    f"{' · ring ' + html.escape(r['ring']) if r.get('ring') else ''}</div>"
                    f"{'<pre>' + html.escape(r['why']) + '</pre>' if r.get('why') else ''}"
                    f"<div class=muted>will run</div><pre>{html.escape(what)}</pre>"
                    f"<div class=muted>digest {html.escape(r['digest'][:16])}</div>"
                    f"<form method=post action='/sign'><input type=hidden name=id value='{html.escape(r['id'])}'>"
                    f"<input type=hidden name=csrf value='{csrf}'><input type=password name=pin inputmode=numeric "
                    f"autocomplete=off placeholder=PIN><br><button name=do value=sign>Sign</button>"
                    f"<button name=do value=deny>Deny</button></form></div>")
            body = f"<h1>{html.escape(cfg.project)} — waiting for your sign</h1>" + ("".join(cards) or "<p>Nothing waits.</p>")
            self._send(200, _page("signs", body))

        def do_POST(self):
            if urllib.parse.urlparse(self.path).path != "/sign":
                return self._send(404, _page("not found", "<p>not found</p>"))
            n = int(self.headers.get("Content-Length") or 0)
            if n > 10_000:
                return self._send(413, _page("too large", "<p>too large</p>"))
            form = urllib.parse.parse_qs(self.rfile.read(n).decode(), keep_blank_values=True)
            f = {k: v[0] for k, v in form.items()}
            if not secrets.compare_digest(f.get("csrf", ""), csrf):
                return self._send(403, _page("refused", "<p class=bad>Stale page; reload and try again.</p>"))
            try:
                if f.get("do") == "deny":
                    approvals.deny(cfg, f.get("id", ""), f.get("pin", ""), via="page")
                    msg = f"<p class=ok>Denied {html.escape(f.get('id', ''))}.</p>"
                else:
                    approvals.sign(cfg, f.get("id", ""), f.get("pin", ""), via="page")
                    msg = f"<p class=ok>Signed {html.escape(f.get('id', ''))}.</p>"
                code = 200
            except approvals.SignError as e:
                msg, code = f"<p class=bad>{html.escape(str(e))}</p>", 403
            self._send(code, _page("signs", msg + "<p><a href='/'>back</a></p>"))

    return H


def server(cfg, host: str = "127.0.0.1", port: int = 8765) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), make_handler(cfg, secrets.token_urlsafe(24)))


def serve_in_thread(cfg, host: str = "127.0.0.1", port: int = 0) -> ThreadingHTTPServer:
    srv = server(cfg, host, port)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv
