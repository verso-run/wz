# Example: fernhill

A made-up project used throughout the docs: a greenhouse controller with a web dashboard (software), controller
firmware (firmware), a bench with a power supply and a board (hardware), and grant letters and supplier invoices
(admin).

`answers.json` is what the setup interview produces. Turn it into a workspace without the interview:

```sh
mkdir -p ~/tmp/fernhill && cd ~/tmp/fernhill
git init -q -b main ../fernhill-app && git -C ../fernhill-app commit -q --allow-empty -m init
wz init --answers /path/to/wz/examples/fernhill/answers.json --dir ctl
cd ctl && wz status
wz install timers --dry-run --root /tmp/wz-dry-home
```
