"""A simulated board (the device under test). Its "flash" is a state directory; it refuses to run unflashed.

  device.py flash IMAGE --state DIR      put the image on the board
  device.py play INPUTS --state DIR      drive it with recorded or generated inputs; it writes its own records
  device.py dump --state DIR --out FILE  pull the board's records off it
"""
import argparse
import pathlib
import shutil
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ctl  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("verb", choices=["flash", "play", "dump"])
ap.add_argument("path", nargs="?")
ap.add_argument("--state", required=True)
ap.add_argument("--out")
a = ap.parse_args()
st = pathlib.Path(a.state)
st.mkdir(parents=True, exist_ok=True)
if a.verb == "flash":
    shutil.copy(a.path, st / "flashed.img")
    print("flashed", a.path)
elif a.verb == "play":
    img = (st / "flashed.img").read_bytes() if (st / "flashed.img").exists() else None
    if img is None:
        sys.exit("board is not flashed")
    fault = None
    for line in img.decode(errors="replace").splitlines()[:3]:
        if line.startswith("fault="):
            fault = int(line.split("=", 1)[1])
    (st / "records.bin").write_bytes(ctl.run(ctl.read_inputs(a.path), fault_at=fault))
    print("played", a.path)
else:
    shutil.copy(st / "records.bin", a.out)
    print("dumped", a.out)
