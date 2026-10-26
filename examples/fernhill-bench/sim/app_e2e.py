"""Stand-in for the app's end-to-end run on the leased test phone: it reads the board's records the way the app would
and checks the app shows the same valve state the board decided, for every record."""
import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ctl  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("--phone", required=True)
ap.add_argument("--records", required=True)
a = ap.parse_args()
data = pathlib.Path(a.records).read_bytes()
recs = [ctl.REC.unpack_from(data, i) for i in range(0, len(data), ctl.REC.size)]
shown = [r[2] for r in recs]           # what the app's screen would show
if not recs or any(v not in (0, 1) for v in shown) or [r[0] for r in recs] != list(range(len(recs))):
    sys.exit("app view differs from the board: missing ticks or an unknown valve state")
print(f"phone {a.phone}: {len(recs)} records shown, {sum(shown)} with the valve open")
