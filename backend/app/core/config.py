from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LIVE_ORDER_ACK_PHRASE = "I_UNDERSTAND_REAL_ORDERS"

class Settings(BaseSettings):
    app_env: str = "dev"
    kotak_consumer_key: str = ""
    kotak_mobile_number: str = ""
    kotak_ucc: str = ""
    kotak_mpin: str = ""
    app_api_token: str = ""
    live_order_submission_enabled: bool = False
    live_order_ack: str = ""
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @model_validator(mode="after")
    def validate_production_safety(self):
        if self.app_env.lower() in {"prod", "production"}:
            if len(self.app_api_token) < 32:
                raise ValueError("APP_API_TOKEN must be at least 32 characters in production")
        return self

    @property
    def live_orders_unlocked(self) -> bool:
        return self.live_order_submission_enabled and self.live_order_ack == LIVE_ORDER_ACK_PHRASE

settings = Settings()
