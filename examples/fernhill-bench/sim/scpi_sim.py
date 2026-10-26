"""A simulated bench power analyser that speaks SCPI over TCP (newline-terminated), for trying the loop without one."""
import argparse
import socketserver

READ = {"*IDN?": "WZSIM,PA-1,0001,1.0", "MEAS:VOLT?": "3.301", "MEAS:CURR?": "0.0142", "MEAS:TEMP?": "24.5"}


class H(socketserver.StreamRequestHandler):
    def handle(self):
        for line in self.rfile:
            q = line.decode().strip()
            if q.endswith("?"):
                self.wfile.write((READ.get(q, "-113,\"Undefined header\"") + "\n").encode())


ap = argparse.ArgumentParser()
ap.add_argument("--port", type=int, default=5025)
a = ap.parse_args()
socketserver.TCPServer.allow_reuse_address = True
with socketserver.TCPServer(("127.0.0.1", a.port), H) as srv:
    srv.serve_forever()
