#!/bin/sh

REPO=${1:?usage: $0 /path/to/repo [suite] [distro]}
SUITE=${2:-stable}
CODENAME=${3:-$(basename "$REPO")}
APTFTPARCHIVE=$(realpath ./bin/apt-ftparchive)

make
rm -f "$REPO/Packages" "$REPO/Packages.gz"
pushd $REPO
dpkg-scanpackages . /dev/null > ./Packages
gzip -n -c "./Packages" > ./Packages.gz

# Detect architectures from .deb filenames present in the directory
ARCHS=""
if ls ./*_amd64.deb >/dev/null 2>&1; then
  ARCHS="amd64"
fi
if ls ./*_arm64.deb >/dev/null 2>&1; then
  ARCHS="arm64"
fi
if [ -z "$ARCHS" ]; then
  echo "WARN: no .deb files found in $REPO; defaulting Architectures to amd64" >&2
  ARCHS="amd64"
fi

rm -f "$REPO/Release"
tmp=$(mktemp)
{
  printf 'Origin: Himmelblau\n'
  printf 'Label: Himmelblau\n'
  printf 'Suite: %s\n' "$SUITE"
  printf 'Codename: %s\n' "$CODENAME"
  printf 'Architectures: %s\n' "$ARCHS"
  printf 'Components: main\n'
  $APTFTPARCHIVE release .
} > "$tmp"
mv "$tmp" "$REPO/Release"
popd

rm -f "$REPO/InRelease" "$REPO/Release.gpg"
if [ -f $REPO/Release ] ; then
  gpg --batch --yes --pinentry-mode loopback --clearsign -o $REPO/InRelease $REPO/Release
  gpg --batch --yes --pinentry-mode loopback -abs -o $REPO/Release.gpg $REPO/Release
else
  echo "$REPO/Release is missing!"
fi

echo "Done: $(ls -1 "$REPO"/{Packages,Packages.gz,Release,InRelease,Release.gpg} 2>/dev/null)"
