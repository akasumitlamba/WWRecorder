# Distribution contract

Ship one application as Inno Setup EXE and full-trust MSIX. All capture, audio, annotation, editing, playback, keyboard and settings features share code, defaults and controls. Only installation, update, startup registration, identity and package-private storage may differ; keep these differences in distribution/startup integration modules.

Build on Windows with Python dependencies, PyInstaller, FFmpeg, Inno Setup and Windows SDK tools installed. Place the trusted FFmpeg executable at the location required by the shared spec. Run:

```powershell
./scripts/build-distributions.ps1 -Format Both
```

Both installers must derive from the same sanitized PyInstaller payload. Definitions live under `packaging/exe`, `packaging/msix` and `packaging/shared`. Outputs live under `artifacts/windows/<version>/<channel>/<edition>`. Preserve historical artifacts. Current app version is 1.7.0 and local-test package revision is 1.7.0.10.

The EXE uses the official GitHub release feed. MSIX must not query that feed or offer an EXE updater; its update path belongs to its distribution channel. Local-test identity and certificates are not production Microsoft Store identities. Never infer a Store identity from an existing EXE listing. Do not commit private signing keys or machine-specific build configuration.

Public assets use WWRecorder_Setup_<revision>.exe and WWRecorder_<revision>_x64.msix names. Internal local-test channel and MSIX signing remain explicit in installation instructions.
