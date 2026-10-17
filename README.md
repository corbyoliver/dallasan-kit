# dallasan-kit

Shared safety code for the apps on the thedallasan box. It follows the same pattern as
[`thedallasan-gate`](https://github.com/corbyoliver/thedallasan-gate): one
implementation, pinned by tag, instead of a hand copy in every app.

## Why

As of 2026-10-12 the fleet had:

- **`fsguard.py` byte-identical in 10 repos.** Any change to it would have needed 10
  edits, 10 deploys, and someone to remember all 10.
- **11 SMTP senders calling `starttls()` with no context** (vps-infra#72). That
  default does not verify the certificate. Each fix was one line in a different repo.
- **The API-cap alerter in one app only** (vps-infra#55). The other model callers
  had nothing, and on 2026-08-21 eighteen requests hit the cap in silence.

Copy-paste carries the code over but not its later fixes. With the code in one
package, a fix lands everywhere when each app bumps its pin.

## Install

Pin by **tag**, never by branch:

```
dallasan-kit @ git+https://github.com/corbyoliver/dallasan-kit@v1.0.0
```

Stdlib only. `api_cap` imports `anthropic` lazily, so an app that never calls a
model doesn't need the SDK.

## Use

### `fsguard`: chmod only a directory you own

```python
from dallasan_kit.fsguard import harden_dir
harden_dir(Path(DB_PATH).parent)   # raises on /tmp, /srv, sticky, mounts, other owners
```

Keep each app's own AST test that no code chmods `0o700` except through
`harden_dir`. That test is about the app's code, so it stays in the app.

### `mail`: verified STARTTLS and a timeout

```python
from dallasan_kit import mail
mail.send(msg, host=..., port=587, username=..., password=...)   # raises on failure
mail.send_alert("subject", "body")   # uses /srv/notify.env, same keys as notify-fail.py
```

It **raises**. If a failed send should be best-effort, the caller catches the error
explicitly. A sender that swallows its own errors turns an alert that never
arrived into an alert that looks like it was never needed.

### `api_cap`: one alert per Anthropic cap outage

```python
from dallasan_kit import api_cap
with api_cap.watch("daily-digest summarize"):
    resp = client.messages.create(...)
```

`watch()` alerts on a cap hit and then re-raises the **original** exception, so
the caller's error handling doesn't change. The dedupe state is shared across
apps (`/srv/.api-cap-alert-state.json`), so the whole box sends one email per
outage. The alerter never raises, even with a broken `anthropic` install or SMTP
down.

## Migrating an app

1. Add the pin to `requirements.txt`.
2. Replace `import fsguard` with `from dallasan_kit import fsguard` and delete the
   local `fsguard.py`. Move hand-rolled SMTP calls to `mail.send`, and wrap model
   calls in `api_cap.watch`.
3. Run the app's tests, deploy (the deploy must `pip install`), then check the
   service on the box.

## Rollout status

| App | fsguard | mail | api_cap |
| --- | --- | --- | --- |
| watchlist-app | ✅ | n/a | n/a |
| everyone else | ⏳ | ⏳ | ⏳ |
