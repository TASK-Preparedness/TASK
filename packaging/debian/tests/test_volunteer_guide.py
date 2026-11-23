# SPDX-License-Identifier: GPL-3.0-or-later
# SPDX-FileCopyrightText: 2026 Joshua Sturtz
"""docs/VOLUNTEER-TESTING.md must match the packages the builder makes and the commands the chroot runs."""
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
REPO = HERE.parents[1]
sys.path.insert(0, str(HERE))
import build_debs  # noqa: E402
import chroot_test  # noqa: E402

GUIDE = (REPO / "docs/VOLUNTEER-TESTING.md").read_text()
NAMES = chroot_test.VOLUNTEER_ORDER


def test_install_line_matches_builder_and_chroot_order():
    line = next(ln for ln in GUIDE.splitlines() if ln.startswith("sudo apt install ./"))
    files = line.split()[3:]
    assert files == [f"./{n}_{build_debs.PACKAGES[n][0]}_all.deb" for n in NAMES]
    assert sorted(NAMES) == sorted(build_debs.PACKAGES)


def test_check_remove_and_purge_lines_name_all_ten_packages():
    for prefix in ("sudo dpkg --verify ", "sudo apt remove ", "sudo apt purge "):
        line = next(ln for ln in GUIDE.splitlines() if ln.startswith(prefix))
        assert line[len(prefix):].split() == NAMES, prefix


def test_expected_versions_are_listed():
    for n in NAMES:
        assert re.search(rf"{re.escape(n)} {re.escape(build_debs.PACKAGES[n][0])}\b", GUIDE), n


def test_guide_keeps_the_required_labels():
    for s in ("UNVERIFIED — REQUIRES PHYSICAL HARDWARE TEST", "alpha", "No RF transmission", "No Windows support",
              "Raspberry Pi 5", "trixie", "arm64", "spare SD card"):
        assert s in GUIDE, s
    assert "autoremove" not in GUIDE and "curl" not in GUIDE and "| sh" not in GUIDE
