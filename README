# Himmelblau Build Host

Automates **community builds** of Himmelblau and publishes distro repositories (apt/dnf/zypper) to a web root you host (e.g., Nginx).
This repo wraps a few containerized helpers (notably `apt-ftparchive`) and a Python driver that builds, signs (if configured), and (re)indexes repos.

> ⚠️ Private for now because it’s still scrappy/AI-assisted slop (even this README!). It works and it’s fast, but expect rough edges.

---

## TL;DR (Quick start)

1. **Install prerequisites**

   * Host packages: `podman`, `python3`, a web server (e.g. **nginx**), `git`
   * Rust toolchain: via [https://rustup.rs/](https://rustup.rs/)
2. **Clone & build helper containers**

   ```bash
   git clone https://github.com/himmelblau-idm/build-host
   cd build-host
   make
   ```
3. **Choose a publish directory** for repos, e.g. `/srv/repos/himmelblau`.
4. **Use a large disk for BOTH containers and the Himmelblau source tree.**
   Build artifact caching lives inside the Himmelblau checkout (e.g., `target/`); container layers are also large. Put **container storage** *and* the **Himmelblau repo** on your big disk (see “Recommended storage layout”).
5. **Clone Himmelblau** somewhere on that large disk:

   ```bash
   cd /mnt-build/src
   git clone https://github.com/himmelblau-idm/himmelblau.git
   ```
6. **Add the cron job** (edit paths/groups as needed):

   ```cron
   0 */6 * * * sg nginx -c "PATH=$PATH:/home/<you>/.cargo/bin TMPDIR=/mnt/tmp BUILDAH_TMPDIR=/mnt/tmp /usr/bin/python3 /path/to/build-host/himmelblau-auto-build.py --publish-dir=/srv/repos/himmelblau >> /var/log/himmelblau-build.log 2>&1"
   ```

   * Replace `nginx` with the group your web server uses for write access.
7. **Serve the publish directory** from your web server.

Every six hours the job rebuilds and refreshes repository metadata.

---

## What it produces

The driver writes distro-specific trees into `--publish-dir` and generates the appropriate metadata (e.g., containerized `apt-ftparchive` for Debian/Ubuntu). You can serve or rsync the directory as-is.

---

## Recommended storage layout (important)

If you have a larger, separate disk (e.g., mounted at `/mnt-build`), move **both** container storage **and** your Himmelblau checkout there so *all* heavy caches land on the big disk.

**Container storage** — `~/.config/containers/storage.conf`:

```ini
runroot = "/mnt-build/containers-run/<user>"
graphroot = "/mnt-build/containers/<user>"
```

**Himmelblau checkout + build artifacts**:

```bash
mkdir -p /mnt-build/src /mnt-build/tmp
cd /mnt-build/src
git clone https://github.com/himmelblau-idm/himmelblau.git
```

**Temp dirs for speed/space**:

```bash
export TMPDIR=/mnt-build/tmp
export BUILDAH_TMPDIR=/mnt-build/tmp
```

Why both? Container layers are large, and so are Rust build artifacts (`target/`, incremental). Keeping **containers + repo checkout** on the big disk prevents your root FS from filling and keeps builds fast.

---

## Web server setup (Nginx example)

Give your web server **read** access to `--publish-dir`, and your cron user **write** access (often by sharing a group).

```nginx
server {
  listen 80;
  server_name your.host.name;

  # Serve /srv/repos/himmelblau at /repos/himmelblau/
  location /repos/himmelblau/ {
    alias /srv/repos/himmelblau/;
    autoindex on;                    # optional, handy for browsing
    add_header Access-Control-Allow-Origin *;
  }
}
```

Ensure files created by the cron job land with the right group (via `sg <group>` in cron, ACLs, or umask).

---

## The pieces in this repo

* `himmelblau-auto-build.py` — main driver. Typical run:

  ```bash
  TMPDIR=/mnt-build/tmp BUILDAH_TMPDIR=/mnt-build/tmp \
  python3 himmelblau-auto-build.py --publish-dir=/srv/repos/himmelblau
  ```
* `Dockerfile.apt-ftparchive` — tiny container so we can run `apt-ftparchive` even on distros that don’t package it.
* `Makefile` — builds helper containers/one-time prerequisites. Re-run when helper images change.
* `crontab` — example schedule to copy/paste.
* `bin/apt-ftparchive`, `re-release.sh`, `key.sh` — supporting utilities (read script headers for details).

---

## Performance vs. space

Builds are **very fast** (often minutes per distro) because we aggressively cache:

* **Container layers**, and
* **Rust artifacts** in the Himmelblau repo (`target/`, incremental builds)

**Plan ~50 GB per active release branch**, plus ~50 GB each time you change base containers. Tracking multiple branches and tweaking containers will grow usage quickly.

**Cleanup (when needed):**

```bash
podman image prune -a
podman container prune
podman volume prune   # optional, only if you know what’s unused
```

Cleanup will slow the next build until caches repopulate.

---

## Cron details

Example (every 6 hours):

```cron
0 */6 * * * sg <web-group> -c "PATH=$PATH:/home/<you>/.cargo/bin TMPDIR=/mnt-build/tmp BUILDAH_TMPDIR=/mnt-build/tmp /usr/bin/python3 /path/to/build-host/himmelblau-auto-build.py --publish-dir=/srv/repos/himmelblau >> /var/log/himmelblau-build.log 2>&1"
```

* `sg <web-group>`: ensures files land with a group your web server can read.
* Make sure `PATH` includes `~/.cargo/bin`.
* Use big `TMPDIR`/`BUILDAH_TMPDIR` for speed.
* Log stdout/stderr and rotate the log.

> Prefer systemd timers? Mirror the env/command in a `*.service` + `*.timer`.

---

## Troubleshooting

**Permission denied writing to publish dir**

* Ensure the cron user can write. Use a shared group and `sg <group>`, or set ACLs:

  ```bash
  setfacl -Rm g:<web-group>:rwx /srv/repos/himmelblau
  setfacl -Rm d:g:<web-group>:rwx /srv/repos/himmelblau
  ```

**`apt-ftparchive` missing / wrong version**

* Re-run `make` to (re)build the helper image; the driver calls it via `podman`.

**Works manually, fails in cron**

* Cron has a minimal environment. Export `PATH`, `TMPDIR`, and `BUILDAH_TMPDIR` explicitly in the job line (see above).

**Disk fills unexpectedly**

* Move containers & the Himmelblau repo to the big disk (see “Recommended storage layout”) and prune unused images/containers.

---

## FAQ

**Can I use Apache or another web server?**
Yes—anything that serves static files is fine.

**How often should the job run?**
Every 6–12 hours is typical for community builds. Tune to your update cadence.

**Do I need GPG signing?**
Optional for community testing. If you enable it, serve the public key and ensure the build user can access the private key.

---

## Appendix: Handy one-liners

**Kick a one-off build using the big disk:**

```bash
PATH=$PATH:$HOME/.cargo/bin \
TMPDIR=/mnt-build/tmp BUILDAH_TMPDIR=/mnt-build/tmp \
python3 /path/to/build-host/himmelblau-auto-build.py \
  --publish-dir=/srv/repos/himmelblau
```

**One-time workspace setup on the big disk:**

```bash
sudo mkdir -p /mnt-build/{containers,containers-run,src,tmp}
sudo chown -R "$USER":"$USER" /mnt-build

# Update container storage (edit ~/.config/containers/storage.conf):
# runroot = "/mnt-build/containers-run/<user>"
# graphroot = "/mnt-build/containers/<user>"

cd /mnt-build/src
git clone https://github.com/himmelblau-idm/himmelblau.git
```
