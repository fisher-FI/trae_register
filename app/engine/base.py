"""注册引擎抽象:统一注册流程的语义与数据结构。"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class RegistrationResult:
    ok: bool
    email: str
    password: str = ""
    reason: str = ""
    credentials: dict = field(default_factory=dict)  # cookie/access_token/refresh_token

    @classmethod
    def success(cls, email: str, password: str, credentials: dict | None = None) -> "RegistrationResult":
        return cls(ok=True, email=email, password=password,
                   credentials=credentials or {})

    @classmethod
    def failure(cls, email: str, reason: str) -> "RegistrationResult":
        return cls(ok=False, email=email, reason=reason)


class RegisterEngine(ABC):
    """实现类必须提供注册与登录凭据抓取。"""

    name: str = "base"

    @abstractmethod
    async def register(self, email: str, request_id: str) -> RegistrationResult:
        """完成注册(含可选 Pro 试用绑卡),返回结果与凭据。"""
        raise NotImplementedError

    @abstractmethod
    async def fetch_credentials(self, email: str, password: str) -> dict:
        """登录并抓取 cookie/access_token/refresh_token。"""
        raise NotImplementedError
