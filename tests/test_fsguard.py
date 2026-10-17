"""fsguard.harden_dir: never chmod a directory the app does not own (vps-infra#83/#84).

`Path(DB_PATH).parent.chmod(0o700)` derives a directory from a setting and locks it. A
DB path directly under a shared directory would lock THAT directory for everyone: the
VPS's /tmp sat at 0700 for a month and broke `apt update` (vps-infra#83). These tests
pin the refusal. The "no other route to chmod 0700" AST check stays in each consuming
app, since it is about that app's code, not this package.
"""
from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from dallasan_kit import fsguard


def mode(p: Path) -> int:
    return stat.S_IMODE(os.stat(p).st_mode)


def test_hardens_a_directory_it_owns(tmp_path):
    d = tmp_path / "data"
    d.mkdir()
    d.chmod(0o755)
    fsguard.harden_dir(d)
    assert mode(d) == 0o700


def test_refuses_a_sticky_directory_and_leaves_its_mode_alone(tmp_path):
    d = tmp_path / "shared"
    d.mkdir()
    d.chmod(0o1777)
    with pytest.raises(RuntimeError, match="sticky"):
        fsguard.harden_dir(d)
    assert mode(d) == 0o1777


@pytest.mark.parametrize("shared", ["/", "/tmp", "/var/tmp", "/srv"])
def test_refuses_well_known_shared_dirs_without_touching_them(shared):
    p = Path(shared)
    if not p.exists():
        pytest.skip(f"{shared} does not exist here")
    before = os.stat(p).st_mode
    with pytest.raises(RuntimeError, match="refusing to chmod"):
        fsguard.harden_dir(p)
    assert os.stat(p).st_mode == before


def test_refuses_a_symlink_to_a_shared_dir(tmp_path):
    link = tmp_path / "data"
    link.symlink_to("/tmp")
    before = os.stat("/tmp").st_mode
    with pytest.raises(RuntimeError, match="shared system directory"):
        fsguard.harden_dir(link)
    assert os.stat("/tmp").st_mode == before


def test_refuses_a_directory_owned_by_someone_else(tmp_path, monkeypatch):
    d = tmp_path / "theirs"
    d.mkdir()
    d.chmod(0o755)
    monkeypatch.setattr(os, "geteuid", lambda: os.stat(d).st_uid + 1)
    with pytest.raises(RuntimeError, match="owned by uid"):
        fsguard.harden_dir(d)
    assert mode(d) == 0o755


def test_refuses_a_mount_point(tmp_path, monkeypatch):
    d = tmp_path / "mnt"
    d.mkdir()
    d.chmod(0o755)
    monkeypatch.setattr(os.path, "ismount", lambda p: True)
    with pytest.raises(RuntimeError, match="mount point"):
        fsguard.harden_dir(d)
    assert mode(d) == 0o755


