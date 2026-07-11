from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    # STT — Soniox stt-rt-v5 primary when this key is set (Vinay 2026-07-10:
    # better + cheaper, ~$0.12/hr real-time Telugu). Empty key = agent falls
    # back to Sarvam Saaras so a missing/revoked key can never block calls.
    soniox_api_key: str = ""
    sarvam_api_key: str           # Sarvam Saaras v3 — STT fallback
    openai_api_key: str
    gemini_api_key: str

    # TTS — smallest.ai Waves Lightning (replaced Sarvam Bulbul 2026-06-15,
    # Vinay). voice_id is per-clinic (branches.tts_voice) incl cloned voices;
    # language is the clinic's Branch.language code (smallest uses the same short
    # codes te/hi/ta/kn/ml/mr/bn/or). Used by the agent (livekit smallestai
    # plugin) AND voice cloning (smallest SDK). https://docs.smallest.ai/waves
    smallest_api_key: str = ""
    smallest_model: str = "lightning_v3.1"
    smallest_sample_rate: int = 24000

    # WhatsApp
    meta_access_token: str = ""
    meta_waba_id: str = ""
    meta_webhook_verify_token: str = ""
    meta_app_secret: str = ""

    # Google
    google_oauth_client_id: str = ""
    google_oauth_client_secret: str = ""
    google_application_credentials: str = "./google-service-account.json"
    google_calendar_service_email: str = ""
    # Production: base64-encoded service-account JSON (stored in Render env).
    # Dev: leave empty; google_application_credentials is used instead.
    google_sa_json_b64: str | None = None

    # Database
    database_url: str
    test_database_url: str = "postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_test"  # MUST be a separate DB from database_url; conftest enforces

    # Redis
    redis_url: str

    # Auth
    jwt_secret: str
    # 8h hard expiry — matches the documented auth contract (auth_middleware
    # docstring) and bounds the blast radius of an XSS-exfiltrated localStorage
    # token (bounce F7). Was 24h (config drift). Override via env if needed.
    jwt_expire_hours: int = 8

    # Cloudflare Turnstile (bot protection on public auth endpoints).
    # Empty = feature OFF (dev/tests); set the secret in prod to enforce.
    turnstile_secret_key: str = ""

    # Payment
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_webhook_secret: str = ""
    razorpay_plan_solo_id: str = ""
    razorpay_plan_clinic_id: str = ""
    razorpay_plan_multi_id: str = ""

    # App
    app_env: str = "development"
    base_url: str = "http://localhost:8000"
    frontend_url: str = "http://localhost:3000"
    admin_phone: str = ""
    log_level: str = "debug"
    # Conservative minute estimate applied to a call whose worker died before
    # finalizing the CallLog row (TD-027/F6). Near the 4-min call target.
    stale_call_minutes_estimate: int = 3

    # Rate limiting (spec §6.5)
    # Comma-separated list of IP addresses that bypass per-endpoint rate limits.
    # Example: RATE_LIMIT_BYPASS_IPS=127.0.0.1,10.0.0.1,testclient
    # Used in backend/middleware/rate_limit.py _EndpointRateLimiter.
    rate_limit_bypass_ips: str = ""

    # Number of TRUSTED reverse-proxy hops in front of the app (iter1 #6). In
    # prod the chain is Cloudflare -> Render, i.e. 2 hops, so the real client IP
    # is the LAST entry minus (hops-1) from the right of X-Forwarded-For. We never
    # trust XFF[0] (fully client-spoofable) nor the bare proxy socket IP. Set to 0
    # when there is NO proxy (direct connections) to use the socket peer as-is.
    trusted_proxy_hops: int = 2
    # SEC #2: origin secret proving a request actually came through OUR Cloudflare
    # edge. Set a Cloudflare Transform Rule to inject `X-Vachanam-Edge: <value>`
    # on every proxied request, and put the same value here. When set, the
    # CF-Connecting-IP / True-Client-IP headers are trusted ONLY if that secret
    # header matches — so a client hitting the Render origin directly can't forge
    # their apparent IP to evade rate limits or poison the blocklist. Empty =
    # fall back to the spoof-resistant hop logic (never blind-trust CF headers).
    cf_origin_secret: str = ""

    # Voice agent (LiveKit)
    public_url: str = "http://localhost:7860"
    # Raw flag. NEVER read this directly to decide whether to record — use the
    # recording_allowed property, which hard-disables recording in production
    # regardless of the flag (memory: no-voice-recording; the env override is
    # TESTING-ONLY and must never reach a paying clinic). DPDP consent.
    recording_enabled: bool = False
    max_call_duration_seconds: int = 0  # 0 = unlimited; non-zero wraps call at N seconds (Solo plan billing cap)

    # Telephony (Vobiz Partner API + WebSocket). These are the GLOBAL fallback
    # account; per-clinic Vobiz sub-accounts (concurrency isolation) override them
    # via Branch.vobiz_* columns when set. See backend/services/telephony.py.
    vobiz_did_number: str = ""
    vobiz_auth_id: str = ""
    vobiz_auth_token: str = ""
    vobiz_api_base: str = "https://api.vobiz.ai/api/v1"
    # Fernet key (urlsafe-base64 32 bytes) encrypting secrets at rest — per-branch
    # SIP passwords. REQUIRED in production; dev/test derive one from jwt_secret.
    field_encryption_key: str = ""
    # The Vobiz CDR sync job is the AUTHORITATIVE source of calls + minutes
    # (agent-independent). The agent's own CallLog writes are OFF by default to
    # avoid double-counting; flip on only in environments with no Vobiz CDR.
    agent_call_log_enabled: bool = False

    # LiveKit voice control plane. The agent reads its own local .env, but the
    # backend's outbound-call jobs (reminders, cascade rebook) also need these;
    # without them those jobs silently no-op (bug-bounty M15).
    livekit_url: str = ""
    livekit_api_key: str = ""
    livekit_api_secret: str = ""
    outbound_trunk_id: str = ""

    # OTP verification (signup). When no provider is configured (dev), the code
    # is logged and returned in the API response so the flow is testable.
    msg91_auth_key: str = ""          # SMS provider (MSG91) — India default
    msg91_sender_id: str = "VCHNAM"
    smtp_host: str = ""               # email OTP — raw SMTP fallback
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "hello@vachanam.in"
    # Resend (preferred email provider — HTTP API, reliable from cloud hosts).
    # When resend_api_key is set it is used over SMTP. from-address domain must be
    # verified in Resend (vachanam.in).
    resend_api_key: str = ""
    resend_from: str = "Vachanam <noreply@vachanam.in>"

    # Watchdog (#306): where change-triggered health alerts go, and the Fly
    # Machines API token that lets the watchdog RESTART a dead voice agent
    # (empty ⇒ alert-only, no auto-restart). fly_agent_app matches infra/fly.agent.toml.
    alert_email: str = "hello@vachanam.in"
    fly_api_token: str = ""
    fly_agent_app: str = "vachanam-agent"
    otp_ttl_seconds: int = 600        # 10 minutes
    # DPDP s.8(7) retention: erase a patient's PII this many days after their last
    # appointment (default 2 years, matching the privacy policy's appointments
    # retention). The anonymised booking rows survive for aggregate analytics.
    patient_retention_days: int = 730
    # Feedback-loop capture. Transcripts can hold the caller's name/age/health
    # complaint, so they are PII: captured only when enabled, phone-masked, tenant-
    # scoped, and pruned after transcript_retention_days (text only — NOT audio,
    # RULE 9). Default ON (the loop needs the corpus); set false to disable per
    # deployment. Retention defaults to 90 days — long enough to score + learn from,
    # short enough to minimise stored PII.
    transcript_capture_enabled: bool = True
    transcript_retention_days: int = 90
    otp_dev_echo: bool = True         # dev only: return code in response

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8", "extra": "ignore"}

    @property
    def otp_echo_enabled(self) -> bool:
        """OTP code may be echoed in API responses ONLY outside production.
        otp_dev_echo defaults True and a prod deploy following .env.example
        could leave it on, turning phone/email 'verification' self-attesting
        (bug-bounty M8). Production always wins, regardless of the flag."""
        return self.otp_dev_echo and self.app_env != "production"

    @property
    def recording_allowed(self) -> bool:
        """Whether call recording may happen. HARD-OFF in production regardless
        of recording_enabled (memory: no-voice-recording — the env flag is a
        TESTING-ONLY override and must never reach a paying clinic). DPDP."""
        return self.recording_enabled and self.app_env != "production"

    @property
    def voice_plane_configured(self) -> bool:
        """True when LiveKit creds are present so outbound jobs can dial."""
        import os

        return bool(
            (self.livekit_url or os.getenv("LIVEKIT_URL"))
            and (self.livekit_api_key or os.getenv("LIVEKIT_API_KEY"))
        )


settings = Settings()
