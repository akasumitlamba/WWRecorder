# Test maintainer guide

Preserve existing functional coverage. Add real widget/state/media assertions
for new behavior rather than only checking source text. GUI widgets remain on
the GUI thread. Keep outputs in isolated temporary folders and preserve user media.
Use explicit responses for expected dialogs; unexpected dialogs fail unattended.
Use one QApplication per child process. Tests run sequentially, isolated by module.
Tag feature markers and Windows-only native/desktop checks appropriately. Never
claim a Linux/offscreen result establishes native Windows fidelity. Run the
root RUN_TESTS.cmd or Python run_all.py wrapper and review generated reports.
