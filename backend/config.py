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

    # Telephony
    vobiz_api_key: str = ""
    vobiz_api_secret: str = ""
    vobiz_webhook_secret: str = ""
    vobiz_partner_auth_id: str = ""
    vobiz_partner_auth_token: str = ""
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""

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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
