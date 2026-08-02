# SPDX-FileCopyrightText: 2023-present David C Wang <dcwangmit01@gmail.com>
#
# SPDX-License-Identifier: MIT
"""Tests for --filename-format template validation."""

import pytest

from amazon_invoice_downloader.cli import (
    DEFAULT_FILENAME_FORMAT,
    validate_filename_format,
)


def test_default_format_is_valid():
    assert validate_filename_format(DEFAULT_FILENAME_FORMAT) == DEFAULT_FILENAME_FORMAT


def test_valid_format_renders_expected_filename():
    fmt = validate_filename_format("{date}_Amazon_{orderid}_{total}")
    rendered = fmt.format(date="20241224", total="12.34", orderid="123-4567890-1234567")
    assert rendered == "20241224_Amazon_123-4567890-1234567_12.34"


def test_surrounding_whitespace_is_stripped():
    assert validate_filename_format("  {date}_{orderid}  ") == "{date}_{orderid}"


def test_empty_format_is_rejected():
    with pytest.raises(ValueError, match="empty"):
        validate_filename_format("   ")


def test_unknown_placeholder_is_rejected_and_named():
    with pytest.raises(ValueError) as excinfo:
        validate_filename_format("{date}_{order_id}")
    message = str(excinfo.value)
    assert "order_id" in message
    assert "orderid" in message


def test_positional_placeholder_is_rejected():
    with pytest.raises(ValueError, match="positional"):
        validate_filename_format("{}_{date}")


def test_numbered_placeholder_is_rejected():
    with pytest.raises(ValueError, match="positional"):
        validate_filename_format("{0}_{date}")


def test_format_without_placeholders_is_rejected():
    with pytest.raises(ValueError, match="at least one placeholder"):
        validate_filename_format("invoice")


def test_malformed_braces_are_rejected():
    with pytest.raises(ValueError, match="not a valid template"):
        validate_filename_format("{date")


@pytest.mark.parametrize("fmt", ["a/b_{date}", "a\\b_{date}", "../{date}_{orderid}"])
def test_path_separators_are_rejected(fmt):
    with pytest.raises(ValueError, match="path separator"):
        validate_filename_format(fmt)


@pytest.mark.parametrize("fmt", ["{date}:{total}", "{date}?{orderid}", '{date}"{orderid}', "{date}*{orderid}"])
def test_reserved_characters_are_rejected(fmt):
    with pytest.raises(ValueError, match="cannot be used in a filename"):
        validate_filename_format(fmt)


def test_missing_orderid_warns_but_is_accepted(capsys):
    assert validate_filename_format("{date}_{total}") == "{date}_{total}"
    assert "orderid" in capsys.readouterr().err


def test_format_with_orderid_does_not_warn(capsys):
    validate_filename_format(DEFAULT_FILENAME_FORMAT)
    assert capsys.readouterr().err == ""
