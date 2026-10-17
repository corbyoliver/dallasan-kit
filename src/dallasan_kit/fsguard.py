"""chmod a directory this app owns, and refuse to touch one it does not.

`Path(DB_PATH).parent.chmod(0o700)` derives a directory from a setting and then
locks it down. If that setting ever points straight into a directory the app did
not create (`/tmp/x.db` in a test, a measurement script, an operator's one-off),
the "app's" directory is /tmp itself. On 2026-08-30..09-29 the VPS's /tmp sat at
0700 root, so apt's `_apt` user could not create its temp keyring and `apt update`
failed for a month with "Could not execute 'gpgv'" (vps-infra#83, #84). Nothing
here can prove it was this call, but nothing here can rule it out either, and the
same call exists in about ten sibling apps.

It RAISES instead of skipping: a silently un-hardened database directory is the
house bug (the failure looks like success), and the fix for the caller is to put
the database in a directory of its own.

Stdlib only, no imports from this package, so it can be used from anywhere
without an import cycle.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

# Directories nobody may chmod on behalf of one app. Compared after realpath(),
# so macOS's /tmp -> /private/tmp is covered too.
SHARED_DIRS = frozenset(
    {"/", "/tmp", "/var/tmp", "/srv", "/private/tmp", "/private/var/tmp", "/private/var"}
)


def harden_dir(d: Path) -> None:
    """chmod 0700 `d`, but only when it is plausibly this app's own.

    Refuses (RuntimeError, nothing changed) when `d` is any of:
      - a well-known shared directory (`/tmp`, `/var/tmp`, `/srv`, `/`);
      - sticky (`S_ISVTX`), the mark of a shared, world-writable directory;
      - a mount point;
      - owned by someone other than the running user.
    """
    d = Path(d)
    real = os.path.realpath(d)
    st = os.stat(real)
    why = None
    if real in SHARED_DIRS:
        why = "it is a shared system directory"
    elif st.st_mode & stat.S_ISVTX:
        why = "it is sticky (a shared, world-writable directory)"
    elif os.path.ismount(real):
        why = "it is a mount point"
    elif st.st_uid != os.geteuid():
        why = f"it is owned by uid {st.st_uid}, not the running user ({os.geteuid()})"
    if why:
        raise RuntimeError(
            f"refusing to chmod 0700 {real}: {why}. The database/data path must live "
            f"in a directory of its own that this app created; chmod'ing a shared "
            f"directory breaks every other user of it (see vps-infra#83)."
        )
    d.chmod(0o700)
