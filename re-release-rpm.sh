#!/usr/bin/env bash
set -euo pipefail

if ! command -v createrepo_c >/dev/null 2>&1; then
  echo "ERROR: createrepo_c not found. Install createrepo_c first." >&2
  exit 1
fi

rebuild_repo() {
  local repo_dir="$1"

  echo "Rebuilding repo metadata in: ${repo_dir}"
  pushd "${repo_dir}" >/dev/null

  # Remove old metadata
  rm -rf repodata

  # Recreate metadata from all RPMs in this dir
  createrepo_c .

  # Sign repomd.xml
  echo "Signing repodata/repomd.xml"
  gpg --batch --yes \
      --detach-sign --armor \
      repodata/repomd.xml

  # Keep ownership similar to repomd.xml (optional)
  chown --reference=repodata/repomd.xml repodata/repomd.xml.asc || true

  popd >/dev/null
}

# If you pass directories, rebuild each. Otherwise, use current dir.
if [[ "$#" -gt 0 ]]; then
  for d in "$@"; do
    rebuild_repo "$d"
  done
else
  rebuild_repo "."
fi
