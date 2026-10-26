# Example: fernhill bench loop

A made-up greenhouse controller board that smooths a moisture probe and drives a watering valve, with a bench around
it. Everything physical is simulated in `sim/`, so the loop runs on any computer:

| file | stands in for |
|---|---|
| `sim/ctl.py` | the controller's core (the same code is the firmware and the host reference) |
| `sim/build.py` | the firmware build and its `size` report (`--fault N` adds a board-only bug, `--bloat` breaks the flash budget) |
| `sim/device.py` | the board: flash, play inputs, dump its own records |
| `sim/gen_inputs.py` | a signal generator: a reproducible moisture trace |
| `sim/host_ref.py` | the host reference replay |
| `sim/app_e2e.py` | the app's end-to-end run on the test phone |
| `sim/scpi_sim.py` | a SCPI power analyser on TCP |

`wz.toml` declares:
- board-a, whose pairing slot is reserved to phone-b;
- phone-b, the test phone;
- owner-phone, protected;
- the analyser;
- cell-1, hazardous;
- the flash and RAM budget and the safety limits.

`scenarios/replay.toml` is the whole loop. `briefs/01-replay-loop.md` is a brief that has an agent run it.

```sh
./run-example.sh
# second terminal, as the person at the bench:
python3 ../../bin/wz --config wz.toml hand done hand-0001 --note "leads on"
```
