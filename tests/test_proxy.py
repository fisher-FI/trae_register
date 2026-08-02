import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import Config
from app.proxy import ProxyManager, NoProxyConfiguredError


def test_manual_proxy():
    cfg = Config(proxy_mode="manual", proxy_url="http://127.0.0.1:7890")
    pm = ProxyManager(cfg)
    assert pm.get_proxy() == "http://127.0.0.1:7890"
    assert pm.playwright_proxy() == {"server": "http://127.0.0.1:7890"}


def test_none_mode_raises():
    pm = ProxyManager(Config(proxy_mode="none"))
    try:
        pm.get_proxy()
        assert False, "should raise"
    except NoProxyConfiguredError:
        pass


def test_round_robin_manual():
    cfg = Config(proxy_mode="manual", proxy_url="http://127.0.0.1:7890")
    pm = ProxyManager(cfg)
    assert pm.next_proxy() == "http://127.0.0.1:7890"
    assert pm.next_proxy() == "http://127.0.0.1:7890"  # 单代理循环


def test_clash_mode_pending():
    # Clash 订阅解析为二期占位:当前配置了 clash 但未实现,直接抛出未实现
    cfg = Config(proxy_mode="clash", clash_sub_url="https://sub.example.com/x")
    pm = ProxyManager(cfg)
    try:
        pm.get_proxy()
        assert False, "should raise NotImplementedError"
    except NotImplementedError:
        pass
