# WWRecorder local MSIX test

1. Keep the MSIX, WWRecorder-Test.cer, Install-Test.ps1 and Install-Test.cmd together.
2. Quit any running WWRecorder from its tray menu. Both editions share one instance per Windows session.
3. Double-click **Install-Test.cmd**. The first installation asks for administrator approval ONLY to trust the public test certificate. Installation then runs for the original user. No private key is included.
4. The helper now launches **WWRecorder (MSIX Test)** automatically after installation. Look for its edge dock and system-tray icon, not a large main window. You can also launch it from Start. If another WWRecorder instance is running, quit that instance first and launch the test app from Start.
5. Compare capture, microphone/system audio, screenshots, annotation/laser, playback/edit/export, hotkeys, clipboard, drag/drop, fonts and monitor placement with EXE v1.7.0.
6. Check the imported settings and output folder. Change a setting, quit and reopen; it must persist. Test the startup toggle, then sign out/in to verify it. Windows-disabled startup requires re-enabling in Windows Settings > Apps > Startup.
7. The update button opens the confirmed production MSIX Store product page. This LOCAL test package is a separate identity and cannot receive that product's Store updates or upgrade into it.

Recordings stay in the selected output folder. MSIX settings are separate after initial EXE import, under `%LOCALAPPDATA%\Packages\WWRecorder.LocalTest_*\LocalState\WWRecorder`. The source EXE config is not changed. An imported backup is stored as `config.imported-exe.json`.

Uninstall **WWRecorder (MSIX Test)** through Windows Settings > Apps when finished. Uninstall removes its private settings; it must not remove recordings or EXE settings. Do not uninstall the EXE until satisfied with testing. When returning to EXE, inspect its startup choice separately; Windows may show entries for both installed editions.

For certificate cleanup after uninstall, remove only the matching `WWRecorder Local Testing` certificate from Local Computer > Trusted People using `certlm.msc` (administrator). Do not remove unrelated certificates.

This is a self-signed local test package, not a certified Store release. Normal Microsoft Store customers will not need this certificate or script.

For this microphone preview, test built-in, USB and Bluetooth microphones in both editions. Check remembered selection, unavailable-device fallback, mute independence, pinned selection when Windows default changes, disconnect/reconnect, pause/resume, stereo voice and system-audio sync. Bluetooth hands-free mode may reduce headset playback quality.
