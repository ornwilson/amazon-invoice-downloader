# SPDX-FileCopyrightText: 2023-present David C Wang <dcwangmit01@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Tests for safe_click()'s DEBUG_MODE dependency."""

from unittest.mock import Mock

import pytest

from amazon_invoice_downloader.cli import safe_click


def test_safe_click_reraises_without_debug_mode_set():
    # safe_click() is only ever exercised via amazon_invoice_downloader(),
    # which sets the module-level DEBUG_MODE before any click happens. A
    # direct call to safe_click() - e.g. from a test, or a future caller of
    # run() that skips the CLI entry point - must not depend on that having
    # run first.
    page = Mock()
    page.query_selector.return_value.click.side_effect = RuntimeError("boom")

    with pytest.raises(RuntimeError, match="boom"):
        safe_click(page, "query_selector", 'a:has-text("Hello, sign in")')
