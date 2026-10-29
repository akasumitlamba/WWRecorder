# Sample report format

After `.	ests\windows_e2e\run_all.ps1` on Windows, open:

- `artifacts/windows_e2e/summary.md` — human QA summary
- `artifacts/windows_e2e/summary.json` — machine-readable
- `artifacts/windows_e2e/junit.xml` — JUnit
- `artifacts/windows_e2e/summary.html` — HTML mirror

Linux agent harness run (not a Windows GUI pass) produced totals like:
`passed` / `skipped` (windows_gui + windows_native + behavior_question) / `failed=0`.
