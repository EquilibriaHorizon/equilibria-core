#!/bin/bash
# macOS Developer ID signing + notarized/stapled .pkg for XEQM core CLI binaries.
# Usage: bash .github/scripts/macos-sign-and-pkg.sh <arm64|x86_64>
# Runs after "Bundle Homebrew dylibs" (dylibbundler rewrites load paths, which invalidates any
# signature, so we MUST sign here). No-op (exit 0) if signing secrets are absent, so unsigned
# builds still succeed. Works on GitHub-hosted and self-hosted runners.
set -euo pipefail

ARCH="${1:?usage: macos-sign-and-pkg.sh <arm64|x86_64>}"
BINDIR="build-macos-${ARCH}/bin"
BINS=(xeqm-d xeqm-wallet xeqm-rpc)

if [ -z "${MACOS_CERT_APP_P12_BASE64:-}" ]; then
  echo "==> No signing secrets present — skipping code-signing/notarization (unsigned build)."
  exit 0
fi

VERSION="$(echo "${GITHUB_REF_NAME#core-v}" | tr '/' '-')"
SHORT="$(git rev-parse --short HEAD)"
PKG="XEQM-core-${VERSION}-macos-${ARCH}-${SHORT}.pkg"

WORK="${RUNNER_TEMP:-/tmp}/hf22-sign.$$"
KEYCHAIN="${WORK}/signing.keychain-db"
mkdir -p "$WORK"
cleanup() { security delete-keychain "$KEYCHAIN" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

echo "==> Creating temp keychain + importing Developer ID certs"
security create-keychain -p "$MACOS_KEYCHAIN_PASSWORD" "$KEYCHAIN"
security set-keychain-settings -lut 3600 "$KEYCHAIN"
security unlock-keychain -p "$MACOS_KEYCHAIN_PASSWORD" "$KEYCHAIN"
echo "$MACOS_CERT_APP_P12_BASE64"       | base64 -d > "$WORK/app.p12"
echo "$MACOS_CERT_INSTALLER_P12_BASE64" | base64 -d > "$WORK/installer.p12"
# Validate both decoded to real PKCS#12 (.p12 is DER; starts with byte 0x30). Clearer than "Unknown format".
for pair in "app.p12:MACOS_CERT_APP_P12_BASE64:Application" "installer.p12:MACOS_CERT_INSTALLER_P12_BASE64:Installer"; do
  fn="${pair%%:*}"; rest="${pair#*:}"; var="${rest%%:*}"; role="${rest##*:}"
  if [ "$(head -c1 "$WORK/$fn" | od -An -tx1 | tr -d " \n")" != "30" ]; then
    echo "ERROR: $var did not decode to a valid PKCS#12 (.p12 starts with DER 0x30)."
    echo "       Fix: Keychain Access -> export the \"Developer ID $role\" cert WITH its private key as"
    echo "       a .p12, then set the secret to the output of:  base64 -i that-cert.p12"
    exit 1
  fi
done
security import "$WORK/app.p12"       -k "$KEYCHAIN" -P "$MACOS_CERT_PASSWORD" -T /usr/bin/codesign
security import "$WORK/installer.p12" -k "$KEYCHAIN" -P "$MACOS_CERT_PASSWORD" -T /usr/bin/productsign
security set-key-partition-list -S apple-tool:,apple: -s -k "$MACOS_KEYCHAIN_PASSWORD" "$KEYCHAIN" >/dev/null
# put our keychain first in the search list so codesign/productsign find the identities
security list-keychains -d user -s "$KEYCHAIN" $(security list-keychains -d user | sed s/\"//g)

echo "==> Codesigning bundled dylibs then binaries (hardened runtime)"
if compgen -G "$BINDIR/libs/*.dylib" > /dev/null; then
  for dylib in "$BINDIR"/libs/*.dylib; do
    codesign --force --timestamp --options runtime --keychain "$KEYCHAIN" \
      --sign "$MACOS_SIGN_APP_IDENTITY" "$dylib"
  done
fi
for b in "${BINS[@]}"; do
  codesign --force --timestamp --options runtime --keychain "$KEYCHAIN" \
    --sign "$MACOS_SIGN_APP_IDENTITY" "$BINDIR/$b"
  codesign --verify --strict "$BINDIR/$b"
done

echo "==> Building signed .pkg (install to /usr/local/bin)"
PKGROOT="$WORK/root/usr/local/bin"
mkdir -p "$PKGROOT/libs"
for b in "${BINS[@]}"; do cp "$BINDIR/$b" "$PKGROOT/"; done
[ -d "$BINDIR/libs" ] && cp -R "$BINDIR/libs/." "$PKGROOT/libs/"
pkgbuild --root "$WORK/root" --identifier com.xeqmlabs.core --version "$VERSION" \
  --install-location / "$WORK/unsigned.pkg"
productsign --sign "$MACOS_SIGN_INSTALLER_IDENTITY" --keychain "$KEYCHAIN" \
  "$WORK/unsigned.pkg" "$PKG"

echo "==> Notarizing (App Store Connect API key) + stapling"
echo "$MACOS_NOTARY_KEY_P8_BASE64" | base64 -d > "$WORK/notary.p8"
xcrun notarytool submit "$PKG" \
  --key "$WORK/notary.p8" --key-id "$MACOS_NOTARY_KEY_ID" --issuer "$MACOS_NOTARY_ISSUER_ID" \
  --wait
xcrun stapler staple "$PKG"
xcrun stapler validate "$PKG"
shasum -a 256 "$PKG" > "$PKG.sha256"
echo "==> Done: $PKG (signed, notarized, stapled)"
