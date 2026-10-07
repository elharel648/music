#!/bin/zsh
# Build FLOW.app and a DMG on macOS.
#   ./packaging/build_mac.sh            -> dist/FLOW.app + dist/FLOW-<version>-mac.dmg (unsigned)
#   DEVELOPER_ID="Developer ID Application: Name (TEAMID)" APPLE_ID=.. APPLE_TEAM_ID=.. APPLE_APP_PASSWORD=.. ./packaging/build_mac.sh
#                                       -> signed + notarized (needs an Apple Developer Program membership)
set -euo pipefail
cd "$(dirname "$0")/.."
VERSION=$(.venv/bin/python -c "import flow; print(flow.__version__)")
echo "FLOW $VERSION"
.venv/bin/python -m pytest -q
[ -f packaging/flow.icns ] || .venv/bin/python packaging/make_icon.py
rm -rf build dist
.venv/bin/pyinstaller flow.spec --noconfirm
APP="dist/FLOW.app"
if [ -n "${DEVELOPER_ID:-}" ]; then
  echo "Signing with $DEVELOPER_ID"
  codesign --deep --force --options runtime --timestamp --sign "$DEVELOPER_ID" "$APP"
  codesign --verify --deep --strict "$APP"
fi
DMG="dist/FLOW-$VERSION-mac.dmg"
rm -f "$DMG"
STAGE=$(mktemp -d)
cp -R "$APP" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "FLOW" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"
if [ -n "${DEVELOPER_ID:-}" ] && [ -n "${APPLE_ID:-}" ]; then
  codesign --sign "$DEVELOPER_ID" --timestamp "$DMG"
  xcrun notarytool submit "$DMG" --apple-id "$APPLE_ID" --team-id "$APPLE_TEAM_ID" --password "$APPLE_APP_PASSWORD" --wait
  xcrun stapler staple "$DMG"
fi
echo "Built: $DMG"
ls -la dist/
