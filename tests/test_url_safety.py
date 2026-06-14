import pytest

from backend.app.url_safety import is_safe_http_url, validate_http_url


def test_valid_http_urls_pass():
    assert validate_http_url("https://example.com/dataset.csv") == "https://example.com/dataset.csv"
    assert validate_http_url("HTTP://example.com/data") == "http://example.com/data"


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "JavaScript:alert(1)",
        "java\nscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "file:///etc/passwd",
        "//example.com/dataset",
        "ftp://example.com/dataset",
        "mailto:test@example.com",
        "http:///missing-host",
        "https://user:pass@example.com/dataset",
    ],
)
def test_unsafe_urls_fail(url):
    assert not is_safe_http_url(url)
    with pytest.raises(ValueError):
        validate_http_url(url)


def test_empty_allowed_when_requested():
    assert validate_http_url("", allow_empty=True) == ""
