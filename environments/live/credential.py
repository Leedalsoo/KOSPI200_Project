import os
from dataclasses import dataclass
from environments.live.contracts import LiveCredentialRef

@dataclass(frozen=True)
class LiveCredentials:
    app_key: str
    app_secret: str
    account_no: str
    base_url: str

    @classmethod
    def from_environment(cls, ref: LiveCredentialRef) -> "LiveCredentials":
        values = {
            "app_key": os.getenv(ref.app_key_env, "").strip(),
            "app_secret": os.getenv(ref.app_secret_env, "").strip(),
            "account_no": os.getenv(ref.account_env, "").strip(),
            "base_url": os.getenv(ref.base_url_env, "https://openapi.koreainvestment.com:9443").strip(),
        }
        if not values["app_key"] or not values["app_secret"] or not values["account_no"]:
            raise RuntimeError("Live credentials are incomplete")
        return cls(**values)
