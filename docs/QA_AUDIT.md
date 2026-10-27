# QA audit

## Current preview
Application version 1.7.0; installer revision 1.7.0.9. Existing microphone preview prerelease is retained; stable release is unchanged.

Fixed and covered by regression checks: named/native-format microphone handling; microphone popup stacking and state; capture-region interaction; draft settings and dock placement; panel orientation/layout; gallery metadata and exclusive menu highlighting; annotation text metrics and cursor contrast; Keycast input presentation; processing notification lifecycle; responsive player controls; centered transparent ICO/MSIX assets.

The final Windows CI run passed compilation and all 536 automated tests, then built EXE and MSIX from the same payload. See release notes for the exact test count. Contrast coverage includes 72 tool/background combinations, including white, black, gray and saturated colors. Packaging checks verify approved icon assets, transparent taskbar variants and omission of the old processing GIF.

## Remaining manual verification
Automated tests do not replace installed Windows hardware checks. Exercise laptop/USB/Bluetooth microphones, unplug/reconnect and default-device changes; multi-monitor mixed-DPI and negative origins; touchpad wheel gestures; annotation typing/commit alignment; actual recorded Keycast and cursor appearance; installed EXE and MSIX startup/update behavior. Bluetooth hands-free quality changes remain controlled by Windows.

MSIX is a local-test package, not a production Store submission. Follow the supplied test kit instructions and use its public certificate only for this test identity. EXE and MSIX have the same application features. Do not claim Store approval or production signing.
