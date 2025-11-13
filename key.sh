# Usage: ./key.sh /path/to/repo
REPO_DIR=${1:?usage: $0 /mnt-build/repos/himmelblau}

# 1) Generate a dedicated build-signing key (RSA 4096) with no passphrase.
cat > ~/hbl-genkey.cfg <<'EOF'
%echo Generating Himmelblau build-signing key
Key-Type: RSA
Key-Length: 4096
Key-Usage: sign
Name-Real: Himmelblau Build (2025)
Name-Email: build@himmelblau-idm.org
Expire-Date: 2y
%no-protection
%commit
%echo done
EOF

gpg --batch --gen-key ~/hbl-genkey.cfg

# 2) Capture the fingerprint (used below as KEYID).
KEYID="$(gpg --list-keys --with-colons 'Himmelblau Build (2025)' | awk -F: '/^fpr/{print $10; exit}')"
echo "KEYID=$KEYID"

# 3) Publish the public key so users can trust your repos:
install -d -m 755 "$REPO_DIR"
gpg --armor --export "$KEYID" > "$REPO_DIR/himmelblau.asc"
chmod 644 "$REPO_DIR/himmelblau.asc"
