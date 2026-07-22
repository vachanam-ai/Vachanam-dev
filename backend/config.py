from pydantic import field_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    # STT — Soniox stt-rt-v5 primary when this key is set (Vinay 2026-07-10:
    # better + cheaper, ~$0.12/hr real-time Telugu). Empty key = agent falls
    # back to Sarvam Saaras so a missing/revoked key can never block calls.
    soniox_api_key: str = ""
    # #406: Soniox regional WS endpoint. Keys are REGION-SCOPED — pair a JP key
    # with wss://stt-rt.jp.soniox.com/transcribe-websocket (4ms from Fly bom vs
    # 230ms to the US default; big slice of transcription_delay).
    soniox_ws_url: str = "wss://stt-rt.soniox.com/transcribe-websocket"
    sarvam_api_key: str           # Sarvam Saaras v3 — STT fallback
    # #442: Soniox v5 semantic endpoint latency profile. Level 1 is the
    # conservative production canary; 0 restores Soniox's default behavior.
    # Tune one control at a time on real Telugu calls (0..3).
    soniox_endpoint_latency_level: int = 1
    # Hard tail ceiling only -- not the median-latency control. Keep the API
    # default until isolated call evidence justifies lowering it.
    soniox_max_endpoint_delay_ms: int = 2000
    # Leave unset for the server default. Sensitivity is deliberately separate
    # from the latency level so an experiment cannot silently combine knobs.
    soniox_endpoint_sensitivity: float | None = None
    # 0 disables client finalization. A value >=200 enables a cancellable
    # finalize after that much continuing VAD silence. Soniox recommends about
    # 200ms; values 1..199 are rejected to prevent the inaccurate immediate-
    # finalize behavior reverted in #399.
    soniox_manual_finalize_delay_ms: int = 200
    # F5 (plan Task 6.3): successful booking/reschedule/cancel speaks a fixed
    # native-script confirmation directly (no second LLM pass). Kill switch —
    # set false to restore the LLM-spoken confirmation (plan rollout rule:
    # every new behavioural path stays env-revertible until its 24h soak).
    voice_deterministic_confirm: bool = True
    # auto = Soniox when keyed, otherwise Sarvam; sarvam gives operations a
    # reversible provider A/B without deleting/rotating the Soniox credential.
    stt_provider: str = 'auto'
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

    # WhatsApp (Meta Cloud API — spec 2026-07-13). meta_phone_number_id is the
    # WABA test number for dev; per-clinic numbers live on Branch.wa_phone_number_id.
    meta_access_token: str = ""
    meta_phone_number_id: str = ""
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
    # Vachanam's own GSTIN, printed on payment invoices once GST registration is
    # done. Empty ⇒ invoices go out as payment RECEIPTS ("GST registration in
    # progress") — set the env var the day the GSTIN arrives (#342).
    vachanam_gstin: str = ""
    # Support desk: notifications to the team go TO support_email; support emails
    # to clinics are sent FROM support_from (support@vachanam.in — a Zoho alias,
    # domain verified in Resend). Kept separate from resend_from/alert_email so
    # support mail is branded + isolated from the watchdog channel.
    support_email: str = "support@vachanam.in"
    support_from: str = "Vachanam Support <support@vachanam.in>"
    # SLA overdue-ticket escalation emails. OFF by default (Vinay 2026-07-12 —
    # too noisy during early testing). The hourly sweep still runs + logs; set
    # true to also email support_email a digest of overdue+unanswered tickets.
    support_sla_email: bool = False

    # Chaos harness (resilience.py): when true, armed chaos injection (latency /
    # forced failure per dependency) is APPLIED so a drill can watch the circuit
    # breakers + metrics react to a slow/down dependency. HARD-OFF by default —
    # a prod deploy following .env.example can never fault-inject into live calls.
    chaos_enabled: bool = False

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

    @field_validator('soniox_endpoint_latency_level')
    @classmethod
    def _valid_soniox_latency_level(cls, value: int) -> int:
        if not 0 <= value <= 3:
            raise ValueError('must be between 0 and 3')
        return value

    @field_validator('soniox_max_endpoint_delay_ms')
    @classmethod
    def _valid_soniox_endpoint_cap(cls, value: int) -> int:
        if not 500 <= value <= 3000:
            raise ValueError('must be between 500 and 3000 milliseconds')
        return value

    @field_validator('soniox_endpoint_sensitivity')
    @classmethod
    def _valid_soniox_sensitivity(cls, value: float | None) -> float | None:
        if value is not None and not -1.0 <= value <= 1.0:
            raise ValueError('must be between -1.0 and 1.0')
        return value

    @field_validator('soniox_manual_finalize_delay_ms')
    @classmethod
    def _valid_soniox_finalize_delay(cls, value: int) -> int:
        if value != 0 and not 200 <= value <= 3000:
            raise ValueError('must be 0 (disabled) or between 200 and 3000 milliseconds')
        return value

    @field_validator('stt_provider')
    @classmethod
    def _valid_stt_provider(cls, value: str) -> str:
        normalized = value.strip().lower()
        if normalized not in {'auto', 'soniox', 'sarvam'}:
            raise ValueError('must be auto, soniox, or sarvam')
        return normalized

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
