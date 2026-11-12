"""SSRF (Server-Side Request Forgery) guard for URL ingestion.

Validates that user-supplied URLs point to public routable internet hosts,
preventing access to internal services, loopback interfaces, cloud instance
metadata services (IMDS: 169.254.169.254), and private intranet networks.
"""

import ipaddress
import socket
from urllib.parse import urlparse

# IPv4 and IPv6 non-routable / private / link-local / metadata network ranges
BLOCKED_NETWORKS: list[ipaddress.IPv4Network | ipaddress.IPv6Network] = [
    # IPv4 Private & Reserved (RFC 1918, RFC 3927, RFC 5735)
    ipaddress.ip_network("0.0.0.0/8"),          # Current network (only valid as source address)
    ipaddress.ip_network("10.0.0.0/8"),         # RFC 1918 Private
    ipaddress.ip_network("100.64.0.0/10"),      # Shared Address Space (CGNAT)
    ipaddress.ip_network("127.0.0.0/8"),        # Loopback
    ipaddress.ip_network("169.254.0.0/16"),     # Link-Local / Cloud Instance Metadata Service (IMDS)
    ipaddress.ip_network("172.16.0.0/12"),      # RFC 1918 Private
    ipaddress.ip_network("192.0.0.0/24"),       # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),       # TEST-NET-1
    ipaddress.ip_network("192.168.0.0/16"),     # RFC 1918 Private
    ipaddress.ip_network("198.18.0.0/15"),      # Network benchmark tests
    ipaddress.ip_network("198.51.100.0/24"),    # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),     # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),        # Multicast
    ipaddress.ip_network("240.0.0.0/4"),        # Reserved for future use
    ipaddress.ip_network("255.255.255.255/32"), # Broadcast

    # IPv6 Private & Reserved
    ipaddress.ip_network("::/128"),             # Unspecified
    ipaddress.ip_network("::1/128"),            # Loopback
    ipaddress.ip_network("::ffff:0:0/96"),      # IPv4-mapped IPv6
    ipaddress.ip_network("100::/64"),           # Discard prefix
    ipaddress.ip_network("64:ff9b::/96"),       # IPv4/IPv6 translation
    ipaddress.ip_network("fc00::/7"),           # Unique Local Address (ULA)
    ipaddress.ip_network("fe80::/10"),          # Link-Local Unicast
    ipaddress.ip_network("ff00::/8"),           # Multicast
]

ALLOWED_SCHEMES = frozenset({"http", "https"})


class SSRFBlockedError(Exception):
    """Raised when a URL is blocked due to SSRF risk."""


def is_ip_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Check if an IP address belongs to any blocked private/metadata ranges."""
    # Convert IPv4-mapped IPv6 addresses (e.g. ::ffff:127.0.0.1) to IPv4
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return any(ip.version == net.version and ip in net for net in BLOCKED_NETWORKS)


def validate_url_safe(url: str) -> str:
    """Validate that the given URL does not target loopback, private IPs, or cloud IMDS.

    Returns:
        The validated url string.
    Raises:
        SSRFBlockedError: if URL scheme is not http/https, hostname is missing,
                          or resolves to any private/metadata IP address.
    """
    if not url or not isinstance(url, str):
        raise SSRFBlockedError("URL must be a non-empty string.")

    parsed = urlparse(url.strip())

    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        raise SSRFBlockedError(
            f"URL scheme '{parsed.scheme}' is not allowed. Only http and https are permitted."
        )

    hostname = parsed.hostname
    if not hostname:
        raise SSRFBlockedError("URL must contain a valid hostname.")

    # Try parsing hostname directly as IP address
    cleaned_host = hostname.strip("[]")
    try:
        ip = ipaddress.ip_address(cleaned_host)
        if is_ip_blocked(ip):
            raise SSRFBlockedError(
                f"Destination IP address {ip} is in a blocked network range (private/internal/metadata)."
            )
        return url
    except ValueError:
        # Not a raw IP literal, proceed to DNS resolution
        pass

    # Resolve hostname to all associated IPs to prevent DNS rebinding attacks
    port = parsed.port or (443 if parsed.scheme.lower() == "https" else 80)
    try:
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SSRFBlockedError(f"DNS resolution failed for hostname '{hostname}': {exc}") from exc

    resolved_ips: set[str] = set()
    for entry in addr_info:
        sockaddr = entry[4]
        ip_str = sockaddr[0]
        resolved_ips.add(ip_str)
        try:
            ip = ipaddress.ip_address(ip_str)
            if is_ip_blocked(ip):
                raise SSRFBlockedError(
                    f"Hostname '{hostname}' resolved to blocked IP address {ip}."
                )
        except ValueError:
            continue

    if not resolved_ips:
        raise SSRFBlockedError(f"No IP addresses resolved for hostname '{hostname}'.")

    return url
