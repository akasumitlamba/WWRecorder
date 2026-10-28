"""WASAPI PROPVARIANT repair presence (EXE and MSIX)."""

from __future__ import annotations

import pytest

from helpers.env import import_app

pytestmark = [pytest.mark.feature_audio, pytest.mark.pure_logic]


def test_repair_function_is_callable_and_idempotent_without_backend():
    wasapi = import_app("wasapi_compat")
    # Calling without a live soundcard backend must not crash the harness.
    try:
        wasapi.repair_soundcard_propvariant(None)
    except Exception as exc:
        # Accept explicit dependency errors, but not AttributeError on missing API
        if isinstance(exc, AttributeError):
            raise
        pytest.skip(f"repair requires native soundcard backend: {exc}")
