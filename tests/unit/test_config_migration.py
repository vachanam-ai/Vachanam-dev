# tests/unit/test_config_migration.py
from backend.config import settings


def test_config_has_new_keys():
    assert hasattr(settings, "public_url")
    assert hasattr(settings, "recording_enabled")
    assert hasattr(settings, "max_call_duration_seconds")
    assert hasattr(settings, "vobiz_auth_id")
    assert hasattr(settings, "vobiz_auth_token")


def test_config_has_livekit_keys():
    # Reversed 2026-06-13 (bug-bounty M15): the backend's outbound-call jobs
    # (reminders, cascade rebook) need LiveKit creds too — previously they
    # lived only in the agent's local .env and the jobs silently no-opped.
    assert hasattr(settings, "livekit_url")
    assert hasattr(settings, "livekit_api_key")
    assert hasattr(settings, "livekit_api_secret")
    assert hasattr(settings, "outbound_trunk_id")


def test_config_drops_vobiz_sip_keys():
    assert not hasattr(settings, "vobiz_sip_domain")
    assert not hasattr(settings, "vobiz_sip_username")
    assert not hasattr(settings, "vobiz_sip_password")
    assert not hasattr(settings, "vobiz_trunk_id")
    assert not hasattr(settings, "vobiz_partner_auth_id")
    assert not hasattr(settings, "vobiz_partner_auth_token")


def test_recording_default_off_when_unset(monkeypatch):
    # Env var overrides .env file in pydantic-settings v2; set "false" to verify
    # the field correctly parses a falsy value and the default is False.
    # We construct a fresh Settings instance directly rather than reloading the
    # module to avoid poisoning the shared `settings` singleton that other tests
    # (e.g. test_payments_audit_org_id) depend on through their module imports.
    monkeypatch.setenv("RECORDING_ENABLED", "false")
    from backend.config import Settings
    fresh = Settings()
    assert fresh.recording_enabled is False
