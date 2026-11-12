#!/usr/bin/env bash
set -euo pipefail

APP_PATH="${1:-dist/StreamCap.app}"
DMG_PATH="${2:-dist/StreamCap-macos.dmg}"
VOLUME_NAME="${3:-StreamCap}"
BACKGROUND_IMAGE="${4:-assets/images/dmg.jpg}"
WINDOW_WIDTH=830
WINDOW_HEIGHT=540
WINDOW_LEFT=440
WINDOW_TOP=60
WINDOW_RIGHT=$((WINDOW_LEFT + WINDOW_WIDTH))
WINDOW_BOTTOM=$((WINDOW_TOP + WINDOW_HEIGHT))
APP_ICON_X=230
APP_ICON_Y=250
APPLICATIONS_ICON_X=600
APPLICATIONS_ICON_Y=250
ICON_SIZE=96

if [ ! -d "$APP_PATH" ]; then
  echo "App bundle not found: $APP_PATH" >&2
  exit 1
fi

if [ ! -f "$BACKGROUND_IMAGE" ]; then
  echo "DMG background image not found: $BACKGROUND_IMAGE" >&2
  exit 1
fi

WORK_DIR="$(mktemp -d)"
MOUNT_DIR=""
RW_DMG="$WORK_DIR/$VOLUME_NAME-rw.dmg"
DEVICE=""

log() {
  echo "==> $*"
}

cleanup() {
  if [ -n "$DEVICE" ]; then
    hdiutil detach "$DEVICE" -quiet || true
  fi
  rm -rf "$WORK_DIR"
}
trap cleanup EXIT

APP_SIZE_MB="$(du -sm "$APP_PATH" | awk '{print $1}')"
DMG_SIZE_MB="$((APP_SIZE_MB + 200))"

log "Creating writable DMG image (${DMG_SIZE_MB} MB)"
hdiutil create "$RW_DMG" \
  -volname "$VOLUME_NAME" \
  -size "${DMG_SIZE_MB}m" \
  -fs HFS+

log "Mounting writable DMG"
ATTACH_OUTPUT="$(hdiutil attach "$RW_DMG" -readwrite -noverify -noautoopen)"
echo "$ATTACH_OUTPUT"
DEVICE="$(echo "$ATTACH_OUTPUT" | awk '/Apple_HFS/ {print $1; exit}')"
if [ -z "$DEVICE" ]; then
  echo "Could not determine mounted DMG device." >&2
  exit 1
fi
MOUNT_DIR="$(echo "$ATTACH_OUTPUT" | awk '/Apple_HFS/ {print $3; exit}')"
if [ -z "$MOUNT_DIR" ] || [ ! -d "$MOUNT_DIR" ]; then
  echo "Could not determine mounted DMG path." >&2
  exit 1
fi

log "Copying app bundle and installer assets"
cp -R "$APP_PATH" "$MOUNT_DIR/"
ln -s /Applications "$MOUNT_DIR/Applications"
mkdir -p "$MOUNT_DIR/.background"
cp "$BACKGROUND_IMAGE" "$MOUNT_DIR/.background/background.jpg"
chmod -Rf u+rw "$MOUNT_DIR/$(basename "$APP_PATH")" "$MOUNT_DIR/.background"

log "Configuring Finder window layout"
osascript <<APPLESCRIPT
set backgroundImage to POSIX file "$MOUNT_DIR/.background/background.jpg" as alias

tell application "Finder"
  tell disk "$VOLUME_NAME"
    open
    set current view of container window to icon view
    set toolbar visible of container window to false
    set statusbar visible of container window to false
    set pathbar visible of container window to false
    set the bounds of container window to {$WINDOW_LEFT, $WINDOW_TOP, $WINDOW_RIGHT, $WINDOW_BOTTOM}
    set viewOptions to the icon view options of container window
    set arrangement of viewOptions to not arranged
    set icon size of viewOptions to $ICON_SIZE
    set background picture of viewOptions to backgroundImage
    set position of item "StreamCap.app" of container window to {$APP_ICON_X, $APP_ICON_Y}
    set position of item "Applications" of container window to {$APPLICATIONS_ICON_X, $APPLICATIONS_ICON_Y}
    update without registering applications
    delay 3
    close
  end tell
end tell
APPLESCRIPT

sync
if [ ! -f "$MOUNT_DIR/.DS_Store" ]; then
  echo "Finder layout was not saved: .DS_Store was not created." >&2
  exit 1
fi

log "Detaching writable DMG"
hdiutil detach "$DEVICE" -quiet
DEVICE=""

log "Converting writable DMG to compressed image"
mkdir -p "$(dirname "$DMG_PATH")"
hdiutil convert "$RW_DMG" \
  -format UDZO \
  -imagekey zlib-level=9 \
  -o "$DMG_PATH" \
  -ov

echo "Created DMG: $DMG_PATH"
