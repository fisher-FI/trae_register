"""配置加载:环境变量 + 默认值。"""
import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")


@dataclass(frozen=True)
class Config:
    mailops_api_key: str = ""
    mailops_base_url: str = "https://gptmail.passkissyou.online"
    concurrency: int = 10
    code_timeout: int = 300
    code_poll_interval: int = 8
    lease_seconds: int = 1800
    proxy_mode: str = "none"  # none | clash | manual
    proxy_url: str = ""
    clash_sub_url: str = ""
    enable_pro_trial: bool = False
    card_number: str = ""
    card_exp: str = ""
    card_cvc: str = ""
    card_billing: str = ""
    gateway_api_key: str = ""
    db_path: Path = field(default_factory=lambda: BASE_DIR / "trae.db")
    screenshots_dir: Path = field(default_factory=lambda: BASE_DIR / "screenshots")
    logs_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")
    headless: bool = True


def load_config() -> Config:
    def _bool(v: str) -> bool:
        return v.strip().lower() in ("1", "true", "yes", "on")

    return Config(
        mailops_api_key=os.getenv("MAILOPS_API_KEY", ""),
        mailops_base_url=os.getenv("MAILOPS_BASE_URL", "https://gptmail.passkissyou.online"),
        concurrency=int(os.getenv("CONCURRENCY", "10")),
        code_timeout=int(os.getenv("CODE_TIMEOUT", "180")),
        code_poll_interval=int(os.getenv("CODE_POLL_INTERVAL", "8")),
        lease_seconds=int(os.getenv("LEASE_SECONDS", "1800")),
        proxy_mode=os.getenv("PROXY_MODE", "none"),
        proxy_url=os.getenv("PROXY_URL", ""),
        clash_sub_url=os.getenv("CLASH_SUB_URL", ""),
        enable_pro_trial=_bool(os.getenv("ENABLE_PRO_TRIAL", "false")),
        card_number=os.getenv("CARD_NUMBER", ""),
        card_exp=os.getenv("CARD_EXP", ""),
        card_cvc=os.getenv("CARD_CVC", ""),
        card_billing=os.getenv("CARD_BILLING", ""),
        gateway_api_key=os.getenv("GATEWAY_API_KEY", ""),
    )
