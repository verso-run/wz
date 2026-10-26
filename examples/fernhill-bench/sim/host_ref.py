"""The host reference: replays the same inputs through the same core on the computer and writes its records."""
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
import ctl  # noqa: E402

pathlib.Path(sys.argv[2]).write_bytes(ctl.run(ctl.read_inputs(sys.argv[1])))
