#!/bin/sh
# Run the whole bench loop on the simulated board. Answer the hand-step from a second terminal when it asks:
#   wz --config examples/fernhill-bench/wz.toml hand done hand-0001 --note "leads on"
set -e
cd "$(dirname "$0")"
python3 sim/scpi_sim.py --port 5025 &
SIM=$!
trap 'kill $SIM' EXIT
WZ="python3 ../../bin/wz --config wz.toml"
$WZ bench run scenarios/replay.toml
