#!/bin/zsh
# Build Alma.app and a DMG on macOS.
#   ./packaging/build_mac.sh            -> dist/Alma.app + dist/Alma-<version>-mac.dmg (unsigned)
#   DEVELOPER_ID="Developer ID Application: Name (TEAMID)" NOTARY_PROFILE=alma ./packaging/build_mac.sh
#                                       -> signed + notarized + stapled. One-time: xcrun notarytool store-credentials alma
#                                          --apple-id <apple id> --team-id <TEAMID> --password <app-specific password>
#   (APPLE_ID + APPLE_TEAM_ID + APPLE_APP_PASSWORD still work instead of NOTARY_PROFILE)
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(.venv/bin/python -c "import flow; print(flow.__version__)")
echo "Alma $VERSION"
.venv/bin/python -m pytest -q
[ -f packaging/alma.icns ] || .venv/bin/python packaging/make_icon.py
rm -rf build dist
.venv/bin/pyinstaller flow.spec --noconfirm
APP="dist/Alma.app"
if [ -n "${DEVELOPER_ID:-}" ]; then
  echo "Signing with $DEVELOPER_ID"
  # inner binaries first (PyInstaller ships unsigned dylibs/.so), then the bundle itself
  find "$APP/Contents" -type f \( -name "*.dylib" -o -name "*.so" -o -perm -u+x \) -not -path "*/MacOS/Alma" -print0 | xargs -0 codesign --force --options runtime --timestamp --entitlements packaging/entitlements.plist --sign "$DEVELOPER_ID"
  codesign --force --options runtime --timestamp --entitlements packaging/entitlements.plist --sign "$DEVELOPER_ID" "$APP"
  codesign --verify --deep --strict --verbose=2 "$APP"
  spctl --assess --type execute --verbose=2 "$APP" || echo "(spctl will pass once notarized)"
fi
DMG="dist/Alma-$VERSION-mac.dmg"
rm -f "$DMG"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Alma" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
if [ -n "${DEVELOPER_ID:-}" ] && { [ -n "${NOTARY_PROFILE:-}" ] || [ -n "${APPLE_ID:-}" ]; }; then
  codesign --sign "$DEVELOPER_ID" --timestamp "$DMG"
  if [ -n "${NOTARY_PROFILE:-}" ]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$NOTARY_PROFILE" --wait
  else
    xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
  fi
  xcrun stapler staple "$DMG"
  spctl --assess --type open --context context:primary-signature --verbose=2 "$DMG"
fi
echo "Built: $DMG"
ls -la dist/
