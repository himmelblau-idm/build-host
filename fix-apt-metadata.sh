#!/usr/bin/env bash
# Repair broken flat APT metadata in an existing Himmelblau publish tree.

set -euo pipefail

usage() {
  cat >&2 <<'EOF'
usage: fix-apt-metadata.sh [--dry-run] [--no-build] /path/to/publish-dir

Scans stable/*/deb/* and nightly/*/deb/*, skipping latest/ aliases.
Repairs distro directories containing .deb files when APT metadata is missing
or empty, using the repo-local containerized dpkg-scanpackages wrapper.
EOF
}

DRY_RUN=0
NO_BUILD=0
PUBLISH_DIR=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --dry-run)
      DRY_RUN=1
      ;;
    --no-build)
      NO_BUILD=1
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    -*)
      usage
      exit 2
      ;;
    *)
      if [ -n "$PUBLISH_DIR" ]; then
        usage
        exit 2
      fi
      PUBLISH_DIR=$1
      ;;
  esac
  shift
done

if [ -z "$PUBLISH_DIR" ]; then
  usage
  exit 2
fi

SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
PUBLISH_DIR=$(realpath "$PUBLISH_DIR")
DPKG_SCANPACKAGES=${DPKG_SCANPACKAGES:-"$SCRIPT_DIR/bin/dpkg-scanpackages"}
APTFTPARCHIVE=${APTFTPARCHIVE:-"$SCRIPT_DIR/bin/apt-ftparchive"}

if [ ! -x "$DPKG_SCANPACKAGES" ]; then
  echo "ERROR: dpkg-scanpackages helper is not executable: $DPKG_SCANPACKAGES" >&2
  exit 1
fi

if [ ! -x "$APTFTPARCHIVE" ]; then
  echo "ERROR: apt-ftparchive helper is not executable: $APTFTPARCHIVE" >&2
  exit 1
fi

has_debs() {
  find "$1" -maxdepth 1 -type f -name '*.deb' -print -quit | grep -q .
}

metadata_problem() {
  local repo=$1
  local f

  if [ ! -s "$repo/Packages" ]; then
    echo "Packages missing or empty"
    return 0
  fi

  for f in Packages.gz Release InRelease Release.gpg; do
    if [ ! -s "$repo/$f" ]; then
      echo "$f missing or empty"
      return 0
    fi
  done

  return 1
}

detect_archs() {
  local repo=$1
  local archs=()

  if find "$repo" -maxdepth 1 -type f -name '*_amd64.deb' -print -quit | grep -q .; then
    archs+=("amd64")
  fi
  if find "$repo" -maxdepth 1 -type f -name '*_arm64.deb' -print -quit | grep -q .; then
    archs+=("arm64")
  fi

  if [ "${#archs[@]}" -eq 0 ]; then
    archs+=("amd64")
  fi

  printf '%s\n' "${archs[*]}"
}

sign_release() {
  local repo=$1
  local sign_common=(gpg --batch --yes --pinentry-mode loopback)

  if [ -n "${GPG_HOMEDIR:-}" ]; then
    sign_common+=(--homedir "$GPG_HOMEDIR")
  fi

  if [ -n "${GPG_EXTRA:-}" ]; then
    # shellcheck disable=SC2206
    local extra=( $GPG_EXTRA )
    sign_common+=("${extra[@]}")
  fi

  rm -f "$repo/InRelease" "$repo/Release.gpg"

  if [ -n "${GPG_KEYID:-}" ]; then
    "${sign_common[@]}" --local-user "$GPG_KEYID" --clearsign \
      -o "$repo/InRelease" "$repo/Release"
    "${sign_common[@]}" --local-user "$GPG_KEYID" -abs \
      -o "$repo/Release.gpg" "$repo/Release"
  else
    "${sign_common[@]}" --clearsign -o "$repo/InRelease" "$repo/Release"
    "${sign_common[@]}" -abs -o "$repo/Release.gpg" "$repo/Release"
  fi
}

repair_repo() {
  local repo=$1
  local channel=$2
  local distro=$3
  local archs
  local tmp

  archs=$(detect_archs "$repo")

  rm -f "$repo/Packages" "$repo/Packages.gz" "$repo/Release" \
    "$repo/InRelease" "$repo/Release.gpg"

  (
    cd "$repo"
    "$DPKG_SCANPACKAGES" . /dev/null > Packages
    gzip -n -c Packages > Packages.gz
  )

  tmp=$(mktemp "$repo/.Release.XXXXXX")
  {
    printf 'Origin: Himmelblau\n'
    printf 'Label: Himmelblau\n'
    printf 'Suite: %s\n' "$channel"
    printf 'Codename: %s\n' "$distro"
    printf 'Architectures: %s\n' "$archs"
    printf 'Components: main\n'
    (
      cd "$repo"
      "$APTFTPARCHIVE" release .
    )
  } > "$tmp"
  mv "$tmp" "$repo/Release"

  sign_release "$repo"
}

broken_repos=()
broken_channels=()
broken_distros=()
broken_reasons=()

for channel in stable nightly; do
  channel_dir="$PUBLISH_DIR/$channel"
  [ -d "$channel_dir" ] || continue

  while IFS= read -r repo; do
    rel=${repo#"$PUBLISH_DIR"/}
    IFS=/ read -r found_channel label deb_dir distro extra <<< "$rel"

    if [ "$found_channel" != "$channel" ] || [ "$label" = "latest" ] ||
       [ "$deb_dir" != "deb" ] || [ -n "${extra:-}" ]; then
      continue
    fi

    if ! has_debs "$repo"; then
      continue
    fi

    if reason=$(metadata_problem "$repo"); then
      broken_repos+=("$repo")
      broken_channels+=("$channel")
      broken_distros+=("$distro")
      broken_reasons+=("$reason")
    fi
  done < <(find "$channel_dir" -mindepth 3 -maxdepth 3 -type d -path '*/deb/*' | sort)
done

if [ "${#broken_repos[@]}" -eq 0 ]; then
  echo "No broken APT metadata found under $PUBLISH_DIR."
  exit 0
fi

echo "Found ${#broken_repos[@]} repo(s) with broken APT metadata:"
for i in "${!broken_repos[@]}"; do
  printf '  %s (%s)\n' "${broken_repos[$i]}" "${broken_reasons[$i]}"
done

if [ "$DRY_RUN" -eq 1 ]; then
  exit 0
fi

if [ "$NO_BUILD" -eq 0 ]; then
  make -C "$SCRIPT_DIR"
fi

for i in "${!broken_repos[@]}"; do
  repo=${broken_repos[$i]}
  channel=${broken_channels[$i]}
  distro=${broken_distros[$i]}
  echo "Repairing $repo ..."
  repair_repo "$repo" "$channel" "$distro"
done

echo "Done."
