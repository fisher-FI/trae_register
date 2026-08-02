"""代理管理:manual(本地指定)本期实现;clash(订阅池)二期。"""
from app.config import Config


class NoProxyConfiguredError(Exception):
    pass


class ProxyManager:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._nodes: list[str] = []

    def get_proxy(self) -> str:
        if self.cfg.proxy_mode == "manual":
            if not self.cfg.proxy_url:
                raise NoProxyConfiguredError("PROXY_URL 未配置")
            return self.cfg.proxy_url
        if self.cfg.proxy_mode == "clash":
            raise NotImplementedError("Clash 订阅代理池为二期功能")
        raise NoProxyConfiguredError("代理模式为 none")

    def next_proxy(self) -> str:
        """轮换出口:单代理时恒返回自身。"""
        return self.get_proxy()

    def playwright_proxy(self) -> dict | None:
        """返回 Playwright launch 用的 proxy 参数;直连返回 None。"""
        try:
            return {"server": self.get_proxy()}
        except (NoProxyConfiguredError, NotImplementedError):
            return None

    def proxy_for_requests(self) -> dict | None:
        """返回 requests/curl_cffi 用的 proxies 参数;直连返回 None。"""
        try:
            return {"http": self.get_proxy(), "https": self.get_proxy()}
        except (NoProxyConfiguredError, NotImplementedError):
            return None
