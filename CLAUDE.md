# dallasan-kit

Shared safety code imported by the apps on the thedallasan box. **A bug here
breaks every consumer at once.** That is the accepted price of fixing things in
one place, so treat changes as production changes to all of them.

## Rules

- **Stdlib only.** No runtime dependencies. `anthropic` is imported lazily inside
  `api_cap`, so a consumer that never calls a model never needs it.
- **Pin by tag.** Consumers use `@vX.Y.Z`. Never change what a published tag
  points at. A behaviour change is a new tag, and a breaking one is a major bump.
- **`mail.send` raises; `api_cap.alert_if_api_cap_hit` never does.** Both are
  deliberate. The sender must not hide a failed alert. The alerter runs inside
  `except` blocks, where an exception would replace the error being handled.
  `watch()` must always re-raise the original exception.
- **`fsguard.harden_dir` raises rather than skipping.** Don't add a "best effort"
  mode. A silently un-hardened directory looks like success.
- Every guard has a test that fails without it (mutation-checked 2026-10-12:
  bare `starttls()`, no timeout, `watch()` not alerting, alerter try removed).
  Keep it that way when you add one.

## Tests

`pip install -e ".[dev]" && python -m pytest -q`. CI runs 3.10, 3.12 and 3.14.

## Filing work

GitHub issues, never TODO files.

## Finishing work: Claude merges

Branch → implement → verify → merge to `main` → push → delete the branch.
Re-run the tests on `main` after the merge, before the push. Do not open a PR
unless asked.
