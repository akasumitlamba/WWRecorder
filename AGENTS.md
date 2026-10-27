# Contributor guide

Read docs/AI_CONTEXT.md, docs/QA_AUDIT.md, docs/project.md and docs/DISTRIBUTION.md before editing. Preserve unrelated work and inspect git status/diff. Keep widgets on the GUI thread, workers bounded, media recoverable, and negative monitor coordinates supported. Maintain identical application features in EXE and MSIX. Update architecture and audit docs when behavior changes.

Run focused regression tests and at least:

```sh
cd app
python -m py_compile main.py recorder.py ui_elements.py dock_widget.py video_editor.py annotation_tool.py updater.py
```

Build both Windows installers with scripts/build-distributions.ps1. Never commit credentials, private signing material, personal paths or capture media.
