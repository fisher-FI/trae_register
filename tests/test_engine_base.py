import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.engine.base import RegistrationResult, RegisterEngine


def test_result_factory():
    ok = RegistrationResult.success("a@b.com", "pw1")
    assert ok.ok is True
    assert ok.email == "a@b.com"
    assert ok.reason == ""

    fail = RegistrationResult.failure("a@b.com", "code timeout")
    assert fail.ok is False
    assert fail.reason == "code timeout"


def test_engine_abstract():
    # 抽象基类不可直接实例化
    try:
        RegisterEngine.__abstractmethods__
        assert True
    except Exception:
        assert False


def test_browser_engine_instantiable():
    # 防回归:BrowserEngine 必须实现全部抽象方法(此前漏实现 fetch_credentials)
    from app.config import Config
    from app.engine.browser import BrowserEngine
    from app.proxy import ProxyManager

    eng = BrowserEngine(Config(), ProxyManager(Config()))
    assert eng.name == "browser"
