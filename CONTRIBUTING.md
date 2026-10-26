# Contributing to wz

Thanks for looking. wz is small on purpose (Python 3.11+, standard library only), so the best changes are small too.

## Ground rules

- Be kind: see [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md).
- Security problems go through [SECURITY.md](SECURITY.md), never a public issue.
- Open an issue before a large change, so we can agree on it first. A bug fix or a documentation fix needs no discussion.

## Run the tests

```
python3 -m venv .venv && . .venv/bin/activate
pip install pytest
python -m pytest -q
```

The suite takes about 20 seconds and needs no network. CI runs it on Linux and macOS with Python 3.11 and 3.13, plus a
CLI smoke test and the simple-install test (`tests/simple-install/`).

If you change `install.sh`, run `python3 tools/seal.py` afterwards: it re-seals the sha256 that `INSTALL-PROMPT.md` and
the README prompt pin, and a test fails until you do.

## Pull request flow

1. Fork the repository and branch from `main`.
2. Make the change with a test that fails without it. Keep the standard-library-only rule: no new runtime dependency.
3. Run the tests; update the README or `docs/` if behaviour changed.
4. Open a pull request using the template. One topic per pull request; small commits with a plain first line.
5. A maintainer reviews; CI must be green before merge.

## Licence, and sign-off (no CLA)

wz is licensed under the [Apache License 2.0](LICENSE). By contributing you agree your contribution is licensed under it
too (Apache-2.0 section 5, "inbound = outbound"). There is **no CLA**. We ask for a
[Developer Certificate of Origin](https://developercertificate.org/) sign-off: add `Signed-off-by: Your Name <your-address>`
to each commit with `git commit -s`, which says you wrote the change or have the right to submit it. Use any address you
are happy to have in the public history, such as your GitHub noreply address.

## Style

- Plain, readable Python; match the surrounding code. No comments that restate the code.
- Documents are written for a reader who has not seen the project: say what a thing does before what it is called.
- Never commit secrets, personal data or machine-specific paths. CI runs a secret scan on every push and pull request.
