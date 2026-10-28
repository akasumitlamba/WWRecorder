# WWRecorder architecture

Windows desktop screen recorder using shared PyQt6 source in app/. Capture,
audio and encoding workers signal the GUI thread. Recording ends saved,
explicitly discarded, or recoverable; never remove the only playable media copy.
Qt logical coordinates and physical capture pixels are distinct on mixed-DPI
and negative-origin desktops.

EXE and full-trust MSIX share one validated frozen payload. Only distribution,
startup and update delivery differ. Build both using scripts/build-distributions.ps1.
Native Qt components and a bounded frozen launch probe are required before packaging.

Player supports speed selection, screenshots and sectioned editing. Trim,
delete and captions retain the established timeline. Audio supports multiple
source-time mute ranges; silence is applied before retained-span audio concat
so trim/delete retiming remains aligned. Mute-only edits are unsaved changes.

Tests: double-click RUN_TESTS.cmd on Windows with Python 3.13 installed. It sets
up dependencies and runs root/E2E tests without input. Unexpected dialogs fail;
module isolation prevents Qt caches/hooks leaking across unrelated tests. HTML,
JSON, Markdown and JUnit reports go to artifacts/windows_e2e/. Windows-only
coverage is explicitly skipped on other hosts. Real audio-device listening,
installed-package and native DPI/visual acceptance are separate checks.
