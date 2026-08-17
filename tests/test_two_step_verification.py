# SPDX-FileCopyrightText: 2023-present David C Wang <dcwangmit01@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Tests for 2FA-page detection surviving mid-navigation errors."""

from unittest.mock import Mock

from playwright.sync_api import Error

from amazon_invoice_downloader.cli import is_two_step_verification_page


def test_returns_true_when_title_matches():
    page = Mock()
    page.query_selector.return_value = Mock()  # any truthy element handle
    assert is_two_step_verification_page(page) is True


def test_returns_false_when_title_does_not_match():
    page = Mock()
    page.query_selector.return_value = None
    assert is_two_step_verification_page(page) is False


def test_destroyed_execution_context_is_treated_as_still_on_2fa_page():
    # Reproduces the crash: Amazon navigates/reloads while we're querying the
    # title, tearing down the frame's execution context mid-call.
    page = Mock()
    page.query_selector.side_effect = Error("Execution context was destroyed, most likely because of a navigation")
    assert is_two_step_verification_page(page) is True


def test_polling_survives_a_transient_navigation_then_detects_completion():
    page = Mock()
    page.query_selector.side_effect = [
        Mock(),  # initial check: 2FA page present
        Error("Execution context was destroyed, most likely because of a navigation"),
        None,  # user finished 2FA, page navigated to the post-login page
    ]

    assert is_two_step_verification_page(page) is True  # initial check
    assert is_two_step_verification_page(page) is True  # mid-navigation
    assert is_two_step_verification_page(page) is False  # 2FA completed
