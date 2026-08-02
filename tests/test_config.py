import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

os.environ["MAILOPS_API_KEY"] = "mak_test123"
os.environ["CONCURRENCY"] = "3"


def test_config_defaults_and_env():
    from app.config import load_config

    cfg = load_config()
    assert cfg.mailops_api_key == "mak_test123"
    assert cfg.concurrency == 3  # 从环境变量读取
    assert cfg.code_timeout == 180  # 默认
    assert cfg.code_poll_interval == 8  # 默认
    assert cfg.proxy_mode == "none"  # 默认
