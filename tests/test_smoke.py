"""Placeholder so CI is green from the first commit.

Replaced by real extractor tests on day 1.
"""


def test_package_imports():
    import src  # noqa: F401


def test_python_version_is_supported():
    import sys

    assert sys.version_info >= (3, 11)
