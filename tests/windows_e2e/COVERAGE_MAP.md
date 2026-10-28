# Functional coverage

Root regressions and suites cover capture/audio, selection geometry, transport,
Keycast, annotation, player/editor, settings, startup, updates and packaging.
Editor section/mute coverage includes actual controls, dirty-state guards, range
bounds, preview mute and decoded exports with trim/deletion.
The runner writes per-case results and feature-tag summaries. Windows-only
coverage is labelled and skipped elsewhere. Device listening, installed-package
acceptance and native DPI/animation review remain separate verification.
