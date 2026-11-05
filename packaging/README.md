# Windows packaging

| Folder | Purpose | Used by |
| --- | --- | --- |
| `shared/` | PyInstaller specification and Windows executable version metadata | EXE and MSIX |
| `exe/` | Inno Setup installer definition; existing upgrade identity retained | EXE |
| `msix/` | Store/local-test identities, staging, certificate installation helpers | MSIX |

Build from the repository root with `./scripts/build-distributions.ps1 -Format Both`.
This builds one sanitized payload and packages it in both formats. Do not
create an EXE-only or MSIX-only copy of the application source.

Store identity: `msix/store-identity.json`. Local test identity:
`msix/test-identity.json`. A Store submission package and a self-signed test
package have different identities and installation instructions.
