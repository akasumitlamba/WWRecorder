# QA audit

## Current preview
Application version 1.7.0; installer revision 1.7.0.10. Existing microphone preview prerelease is retained; stable release is unchanged.

Fixed and covered by regression checks: named/native-format microphone handling; microphone popup stacking and state; capture-region interaction; draft settings and dock placement; panel orientation/layout; gallery metadata and exclusive menu highlighting; annotation text metrics and cursor contrast; Keycast input presentation; processing notification lifecycle; responsive player controls; centered transparent ICO/MSIX assets.

The final Windows CI run passed compilation and all 558 automated tests, then built EXE and MSIX from the same payload. See release notes for the exact test count. Contrast coverage includes 72 tool/background combinations, including white, black, gray and saturated colors. Packaging checks verify approved icon assets, transparent taskbar variants and omission of the old processing GIF.

## Remaining manual verification
Automated tests do not replace installed Windows hardware checks. Exercise laptop/USB/Bluetooth microphones, unplug/reconnect and default-device changes; multi-monitor mixed-DPI and negative origins; touchpad wheel gestures; annotation typing/commit alignment; actual recorded Keycast and cursor appearance; installed EXE and MSIX startup/update behavior. Bluetooth hands-free quality changes remain controlled by Windows.

MSIX is a local-test package, not a production Store submission. Follow the supplied test kit instructions and use its public certificate only for this test identity. EXE and MSIX have the same application features. Do not claim Store approval or production signing.

## Panel motion and placement follow-up

Fixed horizontal Settings action order, inconsistent Undo/Redo artwork, simultaneous dock/panel movement, dock position drift after panel operations and drag/drop, and oversized horizontal gallery cards. Regression cases cover all four edges, negative-origin coordinates, stable home-screen ownership, interrupted/repeated transitions, stale panel signals, screenshot restoration, drop centring, metadata bounds and increased grid capacity.

Verification: 558 Windows automated tests passed in 37.02 seconds and both installers built successfully. All 383 portable checks passed when run in isolated test-file processes; 66 panel/settings checks passed at 150% scaling, and the 22 new cases passed against the public export. A combined Linux offscreen run still encounters Qt teardown instability; it is not claimed as a passing run. Installed Windows visual and multi-monitor drag acceptance remain manual checks.

The installation helper accepts normal and legacy MSIX filenames, requires exactly one package, and still verifies its certificate/signature and expected manifest identity. Four PowerShell tests execute the actual discovery block for normal, legacy, missing and ambiguous packages. The installer application payload is unchanged; the installation kit carries the updated external helper.

Final source verification passed **562 Windows tests in 38.83 seconds**, including all four actual PowerShell helper-discovery cases. Application/shared-payload source is identical to the successful dual-installer build; the kit embeds the updated verified external helper.
