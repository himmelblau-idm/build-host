"""Regression tests for apt_flat_repo() resilience against corrupt .deb files.

These require dpkg-deb, dpkg-scanpackages (dpkg-dev) and apt-ftparchive
(apt-utils) on PATH, so they only run on a Debian/Ubuntu host or container.
Tests are skipped when those tools are unavailable.
"""
import shutil
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not (shutil.which("dpkg-deb") and shutil.which("dpkg-scanpackages")),
    reason="requires dpkg-deb and dpkg-scanpackages",
)


def _make_deb(dirpath: Path, name: str, version: str = "1.0",
              arch: str = "amd64") -> Path:
    root = dirpath / f"build-{name}"
    (root / "DEBIAN").mkdir(parents=True)
    (root / "DEBIAN" / "control").write_text(
        f"Package: {name}\nVersion: {version}\nArchitecture: {arch}\n"
        f"Maintainer: test <test@example.com>\nDescription: test {name}\n"
    )
    out = dirpath / f"{name}_{version}_{arch}.deb"
    subprocess.run(["dpkg-deb", "--build", "-Znone", str(root), str(out)],
                   check=True, stdout=subprocess.DEVNULL)
    shutil.rmtree(root)
    return out


def _corrupt_deb(dirpath: Path, name: str = "bad-pkg") -> Path:
    bad = dirpath / f"{name}_1.0_amd64.deb"
    bad.write_bytes(b"!<arch>\nnot a valid deb archive")
    return bad


def test_corrupt_deb_does_not_break_index(hab, tmp_path):
    _make_deb(tmp_path, "good-one")
    _make_deb(tmp_path, "good-two")
    _corrupt_deb(tmp_path)

    hab.apt_flat_repo(tmp_path, "nightly")

    packages = (tmp_path / "Packages").read_text()
    assert "Package: good-one" in packages
    assert "Package: good-two" in packages
    assert "bad-pkg" not in packages
    assert (tmp_path / "Packages.gz").exists()
    assert (tmp_path / "Release").stat().st_size > 0


def test_existing_metadata_preserved_when_index_would_be_empty(hab, tmp_path):
    seed = _make_deb(tmp_path, "seed")
    hab.apt_flat_repo(tmp_path, "nightly")
    old_packages = (tmp_path / "Packages").read_text()
    old_release = (tmp_path / "Release").read_text()

    # Drop the only good package and leave a corrupt one: a fresh scan is empty.
    seed.unlink()
    _corrupt_deb(tmp_path)
    hab.apt_flat_repo(tmp_path, "nightly")

    assert (tmp_path / "Packages").read_text() == old_packages
    assert (tmp_path / "Release").read_text() == old_release


def test_clean_directory_indexes_all_packages(hab, tmp_path):
    _make_deb(tmp_path, "alpha")
    _make_deb(tmp_path, "beta")

    hab.apt_flat_repo(tmp_path, "nightly")

    packages = (tmp_path / "Packages").read_text()
    assert "Package: alpha" in packages
    assert "Package: beta" in packages
