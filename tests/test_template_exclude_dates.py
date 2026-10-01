import pytest

from minsar.utils.template_exclude_dates import (
    merge_exclude_date_csv,
    normalize_exclude_dates_arg,
    patch_template_text,
)


def test_normalize_exclude_dates_arg():
    assert normalize_exclude_dates_arg("20260619") == "20260619"
    assert normalize_exclude_dates_arg("20260619, 20260207") == "20260207,20260619"
    assert normalize_exclude_dates_arg("auto") == ""


def test_normalize_invalid_date():
    with pytest.raises(ValueError, match="Invalid exclude date"):
        normalize_exclude_dates_arg("2026-06-19")


def test_patch_template_adds_keys():
    content = "topsStack.subswath = 1 2 3\n"
    out = patch_template_text(content, "20260619", merge=False)
    assert "topsStack.excludeDates = 20260619" in out
    assert "minsar.excludeDates = 20260619" in out


def test_patch_template_merge():
    content = "topsStack.excludeDates = 20260207\nminsar.excludeDates = 20260207\n"
    out = patch_template_text(content, "20260619", merge=True)
    assert "topsStack.excludeDates = 20260207,20260619" in out
    assert "minsar.excludeDates = 20260207,20260619" in out


def test_merge_exclude_date_csv():
    assert merge_exclude_date_csv("20260207", "20260619,20260207") == "20260207,20260619"
