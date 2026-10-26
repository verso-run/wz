# Security policy

## Reporting a vulnerability

Please report it **privately**, not in a public issue or pull request:

1. Open <https://github.com/verso-run/wz/security/advisories/new> (the repository's **Security** tab, then **Report a vulnerability**).
2. Say what you found, the version (`wz --version`), how to reproduce it, and what you think it allows.

Only the maintainers can see the report. You will get a first answer within 7 days. We will tell you when a fix is
released and, if you want, credit you in the release notes. Please give us a reasonable time to fix it (we aim for 90 days
at most) before you publish details.

If the report form is not available to you, open a public issue that says only "I have a security report, please open a
private channel", with no details, and a maintainer will respond there.

## Supported versions

wz is early software. Only the latest release (the newest tag) and `main` get security fixes.

| Version | Supported |
|---|---|
| latest tag | yes |
| `main` | yes |
| older tags | no |

## What counts

wz runs other programs (your agent command and the checks you configure) and enforces a write guard, a job queue and a
sign step. Things we want to hear about:

- a way for an agent to write outside the paths its role owns, or to get past the guard;
- a way to forge, replay or skip a sign (the owner's approval);
- the install or uninstall scripts doing more than they say, or fetching something they do not verify;
- a secret (token, key, password) being written to a log, job record or file it should not be in.

Not in scope: what the agent command you configured does with the permissions you gave it, and problems that need
write access to your own workspace to begin with (the workspace is trusted).

## For users

- Read `install.sh` before you run it; the install prompt pins its sha256.
- Keep your agent's permission mode on the safe default unless you know why you are changing it (see the Safety section of the README).
- Never put tokens in `wz.toml`, briefs or ledgers; they are plain files and may be committed.
