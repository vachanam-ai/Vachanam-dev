from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # AI
    sarvam_api_key: str
    openai_api_key: str
    gemini_api_key: str

    # LiveKit
    livekit_url: str
    livekit_api_key: str
    livekit_api_secret: str

    # Telephony — Vobiz SIP trunk
    vobiz_sip_domain: str = ""
    vobiz_sip_username: str = ""
    vobiz_sip_password: str = ""
    vobiz_did_number: str = ""
    vobiz_partner_auth_id: str = ""
    vobiz_partner_auth_token: str = ""

    # WhatsApp
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

    # Database
    database_url: str

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
