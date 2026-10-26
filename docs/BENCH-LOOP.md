# The bench loop

hardware : firmware : software : app : instrument. One scenario, one set of leases, one run directory of evidence.

## Why it is shaped this way

| Rule | The failure it prevents |
|---|---|
| A device, instrument or test phone is driven only under a lease that names the job. | Two jobs flash the same board, and each blames the other's result. |
| A lease ends when its holder's process ends or its `max_hold` passes, and nothing takes it over. | A stale lock is broken by hand mid-flash, or a forgotten one blocks the bench for days. |
| Flash and RAM are gated against limits in config, before anything is flashed. | An image that cannot fit is flashed anyway, and the failure looks like a logic bug. |
| The device's own records must match a host replay of the same inputs, byte for byte. | "Close enough" hides a real divergence between the device and the reference. |
| Instrument readings are files, with the instrument's `*IDN?`, the query and the raw reply. | A number in a report that nobody can trace to a reading. |
| The report names each field it read and the file it came from. | A summary says "passed" with nothing a reader can check. |
| A physical action is a hand-step file a person answers. Agents wait and never answer. | An agent "assumes" a cable was swapped, and the run measures the wrong setup. |
| Hazardous hardware is attended only, inside the safety limits, and a crossed limit halts the lane. | A cell charges unattended, or a run keeps going past a temperature limit. |
| An owner's own device is protected: never leased, and never named in a command. | A test install overwrites the owner's working setup. |
| A device's pairing slot is reserved to one test phone. | A second phone steals the pairing, and every run after it is on the wrong pair. |
| An agent passes the scenario at the commit before the owner runs it (`wz bench ready`). | The owner becomes the first tester. |

## Config

```toml
[resources.board-a]
kind = "device"
ids = ["FH-0001"]            # serials and USB ids; the guard matches these for protected devices
pair_only_with = "phone-b"   # this device's pairing slot belongs to phone-b only
max_hold = "2h"              # no lease lasts longer, whoever holds it

[resources.phone-b]
kind = "phone"
ids = ["TESTPHONE-B"]

[resources.owner-phone]
kind = "phone"
protected = true             # never leased; any command naming its ids is refused
ids = ["OWNERPHONE-1"]

[resources.analyser]
kind = "instrument"
scpi = "192.0.2.20:5025"     # SCPI over raw TCP

[resources.cell-1]
kind = "battery"
hazard = true                # attended only

[resources.gpu-1]
kind = "gpu"                 # remote compute is a lease too
max_hold = "6h"

[bench]
evidence_dir = "bench/runs"
[bench.budget.default]
flash = "512K"
ram = "64K"
[bench.safety]
attended_only = true
[bench.safety.limits]
volts = [3.0, 3.6]
temp_c = [0, 45]
```

## Scenarios

A scenario is a TOML file with `name`, `device`, `phone`, `instruments`, `cwd` (relative to the file), `timeout` (the
lease bound), `safe_state` (run when a limit is crossed) and an ordered `[[step]]` list:

| kind | keys | what wz checks |
|---|---|---|
| host | `run` | exit 0 |
| firmware | `run`, `size` (a command) or `size_file`, `budget` | exit 0. Flash (text + data) and RAM (data + bss) within `[bench.budget.<budget>]`. |
| flash | `run` | exit 0, on the leased device |
| drive | `run` | exit 0 (a replay tool or a signal generator script) |
| capture | `instrument`, `read = { field = "QUERY?" }`, `limits` | every reply saved. Readings within `[bench.safety.limits]` and the step's own limits. |
| records | `run`, `out` | the records file exists in the run directory |
| parity | `run` (the host replay), `device`, `host`, `record` (`line` or bytes) | equal byte for byte. Otherwise it names the first differing record and byte. |
| app | `run` | exit 0, with the leased test phone |
| hand | `text`, `resource`, `timeout` | a person answered `done`. A refused or expired step blocks the run. |

Placeholders: `{run}`, `{commit}`, `{device}`, `{phone}`, and `{device.<key>}`, `{phone.<key>}`, `{<resource>.<key>}`
for any resource field.

Inside a job, the scenario uses the job's own leases (`WZ_LEASES_HELD`) instead of waiting on its parent. Run from a
terminal, it takes the leases itself, all or none.

## Hand-steps

```sh
wz hand ask "Move the probe to bed 2" --resource board-a --timeout 30m    # the agent
wz hand wait hand-0003                                                     # the agent waits
wz hand attend --minutes 90                                                # the person, at the bench
wz hand done hand-0003 --note "moved"                                      # the person
wz hand refuse hand-0003 --note "bed 2 is wet, not today"                  # the person
```

Each step is `hands/<id>.md` (readable from a phone) plus its JSON. Asking raises an event, so the lead sees it in
`wz next`, and the watchdog lists it until it is answered or expires. A hazardous step can only be marked done while
someone is attending.

## Evidence

`bench/runs/<scenario>-NNN/` holds:
- every step's log;
- the budget JSON, each capture JSON and the parity JSON;
- `evidence.json`, the run record: commit, scenario digest, leases, steps and fields;
- `REPORT.md`, with the steps table and the fields-read table.

A role's report quotes the fields table.
