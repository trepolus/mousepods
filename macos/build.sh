#!/usr/bin/env bash
# SPDX-License-Identifier: Apache-2.0
# Build the macOS motion helper as macos/build/MousePodsMotion.app.
#
# macOS only grants head-tracking access to an app bundle with NSMotionUsageDescription, and it attributes
# a bare binary started from a terminal to the terminal app, so the helper must ship as a .app.
#
# Signing: ad-hoc by default. Every ad-hoc build has a new signature, and macOS may then forget the
# Motion & Fitness permission. To keep it across rebuilds, sign with a stable identity, for example a
# self-signed code-signing certificate from Keychain Access:
#   MOUSEPODS_SIGN_IDENTITY="MousePods Dev" macos/build.sh
set -euo pipefail

here="$(cd "$(dirname "$0")" && pwd)"
app="$here/build/MousePodsMotion.app"
identity="${MOUSEPODS_SIGN_IDENTITY:--}"

cd "$here"
swift test
swift build -c release --product mousepods-motion

rm -rf "$app"
mkdir -p "$app/Contents/MacOS"
install -m 755 .build/release/mousepods-motion "$app/Contents/MacOS/mousepods-motion"
cp app/Info.plist "$app/Contents/Info.plist"
codesign --force --sign "$identity" "$app"
codesign --verify "$app"
echo "Built $app (signed with: $identity)"
