"""Unit tests for SSRF Guard in packages.ingestion.ssrf_guard."""

import pytest

from packages.ingestion.ssrf_guard import SSRFBlockedError, validate_url_safe


def test_reject_non_http_schemes():
    for bad_url in [
        "file:///etc/passwd",
        "ftp://ftp.example.com/file",
        "gopher://example.com",
        "javascript:alert(1)",
    ]:
        with pytest.raises(SSRFBlockedError) as exc_info:
            validate_url_safe(bad_url)
        assert "scheme" in str(exc_info.value).lower()


def test_reject_cloud_metadata_imds(monkeypatch):
    # AWS/GCP metadata service IP 169.254.169.254
    with pytest.raises(SSRFBlockedError) as exc_info:
        validate_url_safe("http://169.254.169.254/latest/meta-data/")
    assert "blocked" in str(exc_info.value).lower()


def test_reject_localhost_and_loopback():
    for loopback in [
        "http://127.0.0.1:8000/api",
        "http://localhost:5432",
        "http://[::1]:8080",
    ]:
        with pytest.raises(SSRFBlockedError) as exc_info:
            validate_url_safe(loopback)
        assert "blocked" in str(exc_info.value).lower()


def test_reject_private_rfc1918_ips():
    for private_url in [
        "http://10.0.0.1/admin",
        "http://172.16.0.5/secrets",
        "http://192.168.1.1/router",
    ]:
        with pytest.raises(SSRFBlockedError) as exc_info:
            validate_url_safe(private_url)
        assert "blocked" in str(exc_info.value).lower()


def test_reject_dns_rebinding_to_private(monkeypatch):
    import socket

    # Simulate a domain that resolves to a private IP (DNS rebinding attack)
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("192.168.0.100", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    with pytest.raises(SSRFBlockedError) as exc_info:
        validate_url_safe("https://attacker-rebound-domain.com/data")
    assert "blocked" in str(exc_info.value).lower()


def test_accept_public_domain(monkeypatch):
    import socket

    # Simulate a domain resolving to a public IP
    def mock_getaddrinfo(host, port, *args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", port))]

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo)

    validated = validate_url_safe("https://example.com/research-paper.html")
    assert validated == "https://example.com/research-paper.html"


def test_accept_direct_public_ip():
    url = "http://93.184.216.34:8080/report.html"
    assert validate_url_safe(url) == url


def test_reject_ipv4_mapped_ipv6_loopback():
    with pytest.raises(SSRFBlockedError):
        validate_url_safe("http://[::ffff:127.0.0.1]/admin")


def test_dns_resolution_failure(monkeypatch):
    import socket

    def mock_getaddrinfo_fail(*args, **kwargs):
        raise socket.gaierror("Name or service not known")

    monkeypatch.setattr(socket, "getaddrinfo", mock_getaddrinfo_fail)
    with pytest.raises(SSRFBlockedError) as exc:
        validate_url_safe("https://nonexistent-domain-xyz.com")
    assert "dns resolution failed" in str(exc.value).lower()


def test_dns_returns_empty_ip_list(monkeypatch):
    import socket

    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [])
    with pytest.raises(SSRFBlockedError) as exc:
        validate_url_safe("https://empty-dns-response.com")
    assert "no ip addresses resolved" in str(exc.value).lower()


