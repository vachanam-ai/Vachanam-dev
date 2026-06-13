from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    sarvam_api_key: str
    openai_api_key: str
    gemini_api_key: str

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
    jwt_expire_hours: int = 24

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

    # Rate limiting (spec §6.5)
    # Comma-separated list of IP addresses that bypass per-endpoint rate limits.
    # Example: RATE_LIMIT_BYPASS_IPS=127.0.0.1,10.0.0.1,testclient
    # Used in backend/middleware/rate_limit.py _EndpointRateLimiter.
    rate_limit_bypass_ips: str = ""

    # Voice agent (Pipecat)
    public_url: str = "http://localhost:7860"
    recording_enabled: bool = False
    max_call_duration_seconds: int = 0  # 0 = unlimited; non-zero wraps call at N seconds (Solo plan billing cap)

    # Telephony (Vobiz Partner API + WebSocket)
    vobiz_did_number: str = ""
    vobiz_auth_id: str = ""
    vobiz_auth_token: str = ""

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
    smtp_host: str = ""               # email OTP
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "hello@vachanam.in"
    otp_ttl_seconds: int = 600        # 10 minutes
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
    def voice_plane_configured(self) -> bool:
        """True when LiveKit creds are present so outbound jobs can dial."""
        import os

        return bool(
            (self.livekit_url or os.getenv("LIVEKIT_URL"))
            and (self.livekit_api_key or os.getenv("LIVEKIT_API_KEY"))
        )


settings = Settings()
