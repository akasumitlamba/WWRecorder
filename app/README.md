# Shared Windows application

These are the current Windows 1.7.0 application sources and runtime assets.
**Every file here serves BOTH EXE and MSIX.** There are no separate editions
of the recorder/editor/UI. `distribution.py` and `startup_integration.py`
handle the permitted Windows distribution differences.

From the repository root, run `python app/main.py` or `Run-WWRecorder.cmd`.
Keep `icon.ico`, `ffmpeg.exe`, and `icons/` beside the Python modules so the
existing source asset resolvers continue to work. Frozen packaging preserves
the same internal resource destinations as before.

See [the folder guide](../docs/FOLDER_GUIDE.md) and
[distribution contract](../docs/DISTRIBUTION.md).
