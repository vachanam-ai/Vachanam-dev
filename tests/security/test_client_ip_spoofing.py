"""SEC #2 (2026-07-11 audit): client-IP spoofing via CF-Connecting-IP /
True-Client-IP.

The Render origin is directly reachable, so those headers are client-forgeable.
client_ip() must NOT trust them unless the Cloudflare edge secret header proves
the request came through our edge — otherwise an attacker rotates the header to
evade rate limits, or sends a victim IP to poison the blocklist.
"""
from types import SimpleNamespace
from unittest.mock import patch

from backend.middleware.rate_limit import client_ip


def _req(headers, peer="10.0.0.9"):
    return SimpleNamespace(
        headers={k.lower(): v for k, v in headers.items()},
        client=SimpleNamespace(host=peer),
    )


def test_forged_cf_header_ignored_without_secret_configured():
    """No origin secret set → CF-Connecting-IP is never blind-trusted; a forged
    value must not become the client key. With no proxy hops it resolves to the
    real socket peer."""
    import backend.config as cfg
    with patch.object(cfg.settings, "cf_origin_secret", ""), \
         patch.object(cfg.settings, "trusted_proxy_hops", 0):
        got = client_ip(_req({"CF-Connecting-IP": "1.2.3.4"}, peer="10.0.0.9"))
    assert got == "10.0.0.9", f"forged CF header trusted! got {got}"


def test_forged_cf_header_ignored_when_secret_present_but_edge_header_missing():
    """Secret configured, but the attacker (direct-to-origin) can't supply the
    matching X-Vachanam-Edge header → CF-Connecting-IP is ignored."""
    import backend.config as cfg
    with patch.object(cfg.settings, "cf_origin_secret", "s3cret-edge"), \
         patch.object(cfg.settings, "trusted_proxy_hops", 0):
        got = client_ip(_req({"CF-Connecting-IP": "1.2.3.4"}, peer="10.0.0.9"))
    assert got == "10.0.0.9", f"forged CF header trusted without edge secret! got {got}"

    # Wrong secret value is also rejected.
    with patch.object(cfg.settings, "cf_origin_secret", "s3cret-edge"), \
         patch.object(cfg.settings, "trusted_proxy_hops", 0):
        got = client_ip(_req(
            {"CF-Connecting-IP": "1.2.3.4", "X-Vachanam-Edge": "wrong"}, peer="10.0.0.9"))
    assert got == "10.0.0.9"


def test_cf_header_trusted_only_with_valid_edge_secret():
    """The real Cloudflare edge stamps the correct secret → CF-Connecting-IP is
    the authoritative client IP."""
    import backend.config as cfg
    with patch.object(cfg.settings, "cf_origin_secret", "s3cret-edge"):
        got = client_ip(_req(
            {"CF-Connecting-IP": "203.0.113.7", "X-Vachanam-Edge": "s3cret-edge"},
            peer="10.0.0.9"))
    assert got == "203.0.113.7"


def test_hop_logic_still_resolves_real_client_from_xff():
    """Spoof-resistant fallback: with hops=2, the real client is xff[-2], never
    the fully-spoofable xff[0]."""
    import backend.config as cfg
    with patch.object(cfg.settings, "cf_origin_secret", ""), \
         patch.object(cfg.settings, "trusted_proxy_hops", 2):
        got = client_ip(_req(
            {"X-Forwarded-For": "9.9.9.9, 203.0.113.7, 172.16.0.1"}, peer="172.16.0.1"))
    assert got == "203.0.113.7", f"got {got}"
    # attacker prepends a fake entry → still lands on xff[-2], not the fake
    with patch.object(cfg.settings, "cf_origin_secret", ""), \
         patch.object(cfg.settings, "trusted_proxy_hops", 2):
        got = client_ip(_req(
            {"X-Forwarded-For": "6.6.6.6, 9.9.9.9, 203.0.113.7, 172.16.0.1"},
            peer="172.16.0.1"))
    assert got == "203.0.113.7"
