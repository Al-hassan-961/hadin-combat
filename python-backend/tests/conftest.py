# ---------------------------------------------------------------------------
# HADIN-COMBAT – tests/conftest.py
# Copyright (c) 2026 Al-hassan Shehade & Dina Balcheh
# All rights reserved.
# ---------------------------------------------------------------------------
"""Pytest configuration: installs the cv2 shim so tests run without OpenCV."""

from _cv2shim import install

install()
