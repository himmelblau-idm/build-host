#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Himmelblau autobuilder/publisher (per-distro DEB/RPM repos) with bootstrap

- Repo: ~/code/himmelblau (override with --repo-dir)
- Artifacts: <repo>/packaging/ (DEBs, RPMs, optional SBOMs)
- Publishes:
    stable/<tag>/deb/<distro>/*.deb  + Packages/Release
    stable/<tag>/rpm/<distro>/*.rpm  + repodata/
    nightly/<YYYY-MM-DD>-<commit>/(deb|rpm)/<distro>/...
    .../sbom/
- Bootstrap: if stable/nightly not yet present in --publish-dir, build & publish
  the latest stable tag (reachable from stable-1.x) and a nightly from main.
- Optional APT Release signing if HBL_GPG_KEYID is set.
"""

import argparse
import datetime as dt
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from packaging import version

DEFAULT_REPO_DIR = Path.home() / "code" / "himmelblau"
DEFAULT_PUBLISH_DIR = Path("/srv/repos/himmelblau")
SUPPORTED_BRANCHES = ["stable-1.x"]
STATE_FILE = ".build_state.json"
LOCK_FILE = ".build_lock"
PACKAGING_DIR = "packaging"

STABLE_TAG_RE = re.compile(r'^\d+\.\d+\.\d+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$')

DEB_RE = re.compile(r"""(?xi)^.*(?P<ver>\d+\.\d+\.\d+)-(?P<distro>[a-z0-9.]+)_amd64\.deb$""")
RPM_RE = re.compile(r"""(?xi).*- (?P<distro>fedora\d+|rawhide|rocky\d+|leap\d(?:\.\d)?|tumbleweed|sle\d+sp\d+|sle\d{2}) \.rpm$""")

GPG_KEYID = os.environ.get("HBL_GPG_KEYID")
GPG_HOMEDIR = os.environ.get("HBL_GPG_HOMEDIR")
GPG_EXTRA = os.environ.get("HBL_GPG_EXTRA", "")

def log(msg: str):
    print(f"[{dt.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)

def run(cmd, cwd: Optional[Path] = None, check=True, capture=False, env=None):
    return subprocess.run(
        cmd, cwd=str(cwd) if cwd else None, check=check,
        stdout=subprocess.PIPE if capture else None,
        stderr=subprocess.PIPE if capture else None,
        env=env
    )

def which(name: str) -> Optional[str]:
    return shutil.which(name)

def ensure_dir(p: Path):
    p.mkdir(parents=True, exist_ok=True)

def utc_today() -> str:
    return dt.datetime.utcnow().strftime("%Y-%m-%d")

def load_state(path: Path) -> Dict:
    if path.exists():
        try:
            return json.loads(path.read_text())
        except Exception:
            path.rename(path.with_suffix(".corrupt.bak"))
    return {"built_tags": {}, "nightly": {}}

def save_state(path: Path, state: Dict):
    path.write_text(json.dumps(state, indent=2, sort_keys=True))

class FileLock:
    def __init__(self, path: Path):
        self.path = path
        self.fd = None
    def acquire(self):
        import fcntl
        self.fd = open(self.path, "w")
        fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.fd.write(str(os.getpid()))
        self.fd.flush()
    def release(self):
        if self.fd:
            import fcntl
            try:
                fcntl.flock(self.fd, fcntl.LOCK_UN)
            finally:
                self.fd.close()

# --- Git ops ---
def git_fetch_all(repo: Path):
    log("Fetching origin (branches + tags)...")
    run(["git", "fetch", "--all", "--tags", "--prune"], cwd=repo)

def git_list_tags(repo: Path) -> List[str]:
    res = run(["git", "tag", "--list"], cwd=repo, capture=True)
    return [t.strip() for t in res.stdout.decode().splitlines() if t.strip()]

def tag_on_branch(repo: Path, tag: str, branch: str) -> bool:
    try:
        run(["git", "merge-base", "--is-ancestor", tag, f"origin/{branch}"], cwd=repo)
        return True
    except subprocess.CalledProcessError:
        return False

def git_rev_parse(repo: Path, ref: str) -> str:
    res = run(["git", "rev-parse", ref], cwd=repo, capture=True)
    return res.stdout.decode().strip()

def checkout_clean(repo: Path, ref: str):
    log(f"Checking out {ref}...")
    run(["git", "checkout", "--force", ref], cwd=repo)
    run(["git", "reset", "--hard"], cwd=repo)
    run(["git", "clean", "-fdx", "-e", "target"], cwd=repo)

# --- Build & collect ---
def make_package(repo: Path, env: Optional[dict]) -> int:
    log("Running: make package")
    try:
        run(["/usr/bin/make", "package"], cwd=repo, env=env)
        return 0
    except subprocess.CalledProcessError as e:
        return e.returncode

def parse_artifact(p: Path) -> Tuple[str, Optional[str]]:
    nl = p.name.lower()
    if nl.endswith(".deb"):
        m = DEB_RE.match(nl)
        return ("deb", m.group("distro") if m else "unknown")
    if nl.endswith(".rpm"):
        m = RPM_RE.match(nl)
        return ("rpm", m.group("distro") if m else "unknown")
    if nl.endswith(".spdx") or nl.endswith(".sbom.json") or nl.endswith(".cdx.json") or nl.endswith(".spdx.json"):
        return ("sbom", None)
    return ("other", None)

def collect_from_packaging(packaging_dir: Path, built_since: float):
    deb: Dict[str, List[Path]] = {}
    rpm: Dict[str, List[Path]] = {}
    sboms: List[Path] = []
    if not packaging_dir.exists():
        return deb, rpm, sboms
    for p in packaging_dir.iterdir():
        if not p.is_file():
            continue
        try:
            if p.stat().st_mtime <= built_since:
                continue
        except FileNotFoundError:
            continue
        kind, distro = parse_artifact(p)
        if kind == "deb":
            deb.setdefault(distro or "unknown", []).append(p)
        elif kind == "rpm":
            rpm.setdefault(distro or "unknown", []).append(p)
        elif kind == "sbom":
            sboms.append(p)
    return deb, rpm, sboms

# --- Repo metadata ---
def apt_flat_repo(deb_dir: Path):
    debs = list(deb_dir.glob("*.deb"))
    if not debs:
        return
    scanner = which("dpkg-scanpackages") or which("apt-ftparchive")
    if not scanner:
        log(f"INFO: dpkg-scanpackages/apt-ftparchive not found; skipping APT metadata in {deb_dir}.")
        return
    log(f"Generating APT metadata in {deb_dir} ...")
    packages = deb_dir / "Packages"
    if "dpkg-scanpackages" in scanner:
        with open(packages, "wb") as outf:
            subprocess.run([scanner, ".", "/dev/null"], cwd=deb_dir, check=True, stdout=outf)
    else:
        with open(packages, "wb") as outf:
            subprocess.run([scanner, "packages", "."], cwd=deb_dir, check=True, stdout=outf)
    subprocess.run(["gzip", "-f", str(packages)], cwd=deb_dir, check=True)
    release = deb_dir / "Release"
    release.write_text(
        "Origin: Himmelblau\n"
        "Label: Himmelblau\n"
        "Suite: stable\n"
        f"Codename: {deb_dir.name}\n"
        "Architectures: amd64\n"
        "Components: main\n"
        f"Date: {dt.datetime.utcnow().strftime('%a, %d %b %Y %H:%M:%S +0000')}\n"
    )
    aptft = which("apt-ftparchive")
    if aptft:
        with open(release, "a") as outf:
            subprocess.run([aptft, "release", "."], cwd=deb_dir, check=True, stdout=outf)
    if GPG_KEYID and which("gpg"):
        log(f"Signing APT Release in {deb_dir} ...")
        cmd1 = ["gpg", "--batch", "--yes", "--local-user", GPG_KEYID, "--clearsign", "-o", "InRelease", "Release"]
        cmd2 = ["gpg", "--batch", "--yes", "--local-user", GPG_KEYID, "-abs", "-o", "Release.gpg", "Release"]
        if GPG_HOMEDIR:
            cmd1[1:1] = ["--homedir", GPG_HOMEDIR]
            cmd2[1:1] = ["--homedir", GPG_HOMEDIR]
        if GPG_EXTRA:
            extra = GPG_EXTRA.split()
            cmd1[1:1] = extra
            cmd2[1:1] = extra
        subprocess.run(cmd1, cwd=deb_dir, check=True)
        subprocess.run(cmd2, cwd=deb_dir, check=True)

def rpm_repo(rpm_dir: Path):
    rpms = list(rpm_dir.glob("*.rpm"))
    if not rpms:
        return
    cr = which("createrepo_c") or which("createrepo")
    if not cr:
        log(f"INFO: createrepo_c/createrepo not found; skipping RPM metadata in {rpm_dir}.")
        return
    log(f"Generating RPM repodata in {rpm_dir} ...")
    subprocess.run([cr, "."], cwd=rpm_dir, check=True)

# --- Publish ---
def publish_per_distro(publish_root: Path, channel: str, label: str,
                       deb_map: Dict[str, List[Path]],
                       rpm_map: Dict[str, List[Path]],
                       sboms: List[Path]):
    base = publish_root / channel / label
    ensure_dir(base)

    for distro, files in sorted(deb_map.items()):
        dst = base / "deb" / distro
        ensure_dir(dst)
        for f in files:
            shutil.copy2(f, dst / f.name)
        apt_flat_repo(dst)

    for distro, files in sorted(rpm_map.items()):
        dst = base / "rpm" / distro
        ensure_dir(dst)
        for f in files:
            shutil.copy2(f, dst / f.name)
        rpm_repo(dst)

    if sboms:
        sbdir = base / "sbom"
        ensure_dir(sbdir)
        for f in sboms:
            shutil.copy2(f, sbdir / f.name)

    latest = publish_root / channel / "latest"
    try:
        if latest.exists() or latest.is_symlink():
            latest.unlink()
    except FileNotFoundError:
        pass
    os.symlink(label, latest)

# --- Planning + bootstrap helpers ---
def find_latest_stable_tag(repo: Path, branch: str) -> Optional[str]:
    candidates = [t for t in git_list_tags(repo) if STABLE_TAG_RE.match(t) and tag_on_branch(repo, t, branch)]
    if not candidates:
        return None
    candidates.sort(key=version.parse, reverse=True)
    return candidates[0]

def plan_stable(repo: Path, branch: str, state: Dict) -> List[str]:
    built = set(state.get("built_tags", {}).get(branch, []))
    to_build: List[str] = []
    for t in sorted(git_list_tags(repo)):
        if not STABLE_TAG_RE.match(t):
            continue
        if t in built:
            continue
        if tag_on_branch(repo, t, branch):
            to_build.append(t)
    if to_build:
        log(f"Stable planner: {branch} -> new tags: {', '.join(to_build)}")
    else:
        log(f"Stable planner: {branch} -> no new tags.")
    return to_build

def plan_nightly(repo: Path, state: Dict, force_daily: bool) -> Tuple[bool, str, str]:
    tip = git_rev_parse(repo, "origin/main")
    last_commit = state.get("nightly", {}).get("last_commit")
    today = utc_today()
    last_date = state.get("nightly", {}).get("last_date")
    if tip != last_commit:
        log(f"Nightly planner: main changed ({tip[:12]}), will build.")
        return True, tip, today
    if force_daily and last_date != today:
        log("Nightly planner: forcing daily build.")
        return True, tip, today
    log("Nightly planner: up-to-date; skip.")
    return False, tip, today

def needs_bootstrap_stable(publish_root: Path, tag: Optional[str]) -> bool:
    if not tag:
        return False
    tag_dir = publish_root / "stable" / tag
    latest = publish_root / "stable" / "latest"
    return not tag_dir.exists() or not latest.exists()

def needs_bootstrap_nightly(publish_root: Path, label: str) -> bool:
    label_dir = publish_root / "nightly" / label
    latest = publish_root / "nightly" / "latest"
    return not label_dir.exists() or not latest.exists()

# --- Main ---
def main():
    ap = argparse.ArgumentParser(description="Himmelblau autobuilder/publisher (per-distro) with bootstrap")
    ap.add_argument("--repo-dir", type=Path, default=DEFAULT_REPO_DIR)
    ap.add_argument("--publish-dir", type=Path, default=DEFAULT_PUBLISH_DIR)
    ap.add_argument("--force-daily", action="store_true")
    ap.add_argument("--log-file", type=Path)
    args = ap.parse_args()

    if args.log_file:
        args.log_file.parent.mkdir(parents=True, exist_ok=True)
        sys.stdout = open(args.log_file, "a", buffering=1)
        sys.stderr = sys.stdout

    publish_root = args.publish_dir
    ensure_dir(publish_root)
    state_path = publish_root / STATE_FILE
    state = load_state(state_path)

    lock = FileLock(publish_root / LOCK_FILE)
    try:
        lock.acquire()
    except Exception:
        log("Another run in progress; exiting.")
        return 0

    try:
        repo = args.repo_dir
        if not repo.exists():
            log(f"ERROR: repo-dir does not exist: {repo}")
            return 2

        packaging_dir = repo / PACKAGING_DIR
        git_fetch_all(repo)

        # ===== Normal stable flow (new tags) =====
        for branch in SUPPORTED_BRANCHES:
            latest_stable = find_latest_stable_tag(repo, branch)
            if needs_bootstrap_stable(publish_root, latest_stable):
                if latest_stable:
                    log(f"Bootstrap: publishing latest stable tag {latest_stable} ...")
                    checkout_clean(repo, latest_stable)
                    env = os.environ.copy()
                    started = time.time()
                    rc = make_package(repo, env)
                    if rc != 0:
                        log(f"ERROR: Some builds failed for {latest_stable} (rc={rc})")
                    deb_map, rpm_map, sboms = collect_from_packaging(packaging_dir, built_since=started)
                    publish_per_distro(publish_root, "stable", latest_stable, deb_map, rpm_map, sboms)
                    state.setdefault("built_tags", {}).setdefault(branch, [])
                    if latest_stable not in state["built_tags"][branch]:
                        state["built_tags"][branch].append(latest_stable)
                    save_state(state_path, state)

        # ===== Normal nightly planner =====
        should, tip2, today = plan_nightly(repo, state, args.force_daily)
        if should:
            checkout_clean(repo, "origin/main")
            env = os.environ.copy()
            started = time.time()
            rc = make_package(repo, env)
            if rc != 0:
                log(f"ERROR: Some nightly builds failed (rc={rc})")
            deb_map, rpm_map, sboms = collect_from_packaging(packaging_dir, built_since=started)
            label = f"{today}-{(tip2 or 'unknown')[:12]}"
            publish_per_distro(publish_root, "nightly", label, deb_map, rpm_map, sboms)
            state.setdefault("nightly", {})["last_commit"] = tip2
            state["nightly"]["last_date"] = today
            save_state(state_path, state)

        log("Done.")
        return 0
    finally:
        lock.release()

if __name__ == "__main__":
    sys.exit(main())
