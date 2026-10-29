# Distribution contract

Ship one application as Inno Setup EXE and full-trust MSIX. All capture, audio, annotation, editing, playback, keyboard and settings features share code, defaults and controls. Only installation, update, startup registration, identity and package-private storage may differ; keep these differences in distribution/startup integration modules.

Build on Windows with Python dependencies, PyInstaller, FFmpeg, Inno Setup and Windows SDK tools installed. Use requirements-windows.lock and scripts/prepare_media_runtime.py to prepare the pinned encoder; do not use an arbitrary PATH encoder. Run:

```powershell
./scripts/build-distributions.ps1 -Format Both
```

Both installers must derive from the same sanitized PyInstaller payload. Definitions live under `packaging/exe`, `packaging/msix` and `packaging/shared`. Outputs live under `artifacts/windows/<version>/<channel>/<edition>`. Preserve historical artifacts. Current app version is 1.7.1 and package version is 1.7.1.0.

The EXE uses the official GitHub release feed. MSIX must not query that feed or offer an EXE updater; its update path belongs to its distribution channel. Local-test identity and certificates are not production Microsoft Store identities. Never infer a Store identity from an existing EXE listing. Do not commit private signing keys or machine-specific build configuration.

Public assets use WWRecorder_Setup_<revision>.exe and WWRecorder_<revision>_x64.msix names. Internal local-test channel and MSIX signing remain explicit in installation instructions.

The application uses the per-session `Local\WWRecorder_mutex` name. MSIX must never query the EXE release feed or use an EXE version to claim a Store update.
Microsoft Store is its update authority. Both editions still share all capture
and editing behavior.

Production Store submission uses packaging/msix/store-identity.json, version
1.7.1.0 (reserved fourth segment zero). The same payload is staged independently
from the local-test channel. Microsoft signs Store distribution; no test
certificate is included in the production upload. EXE remains unsigned.
The release includes the production-identity unsigned MSIX explicitly labeled
as a Store submission package, not a direct sideload installer.
