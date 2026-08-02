"""Playwright 注册引擎:trae.ai 国际版。"""
import asyncio
import json
import re
import time
from pathlib import Path

from playwright.async_api import async_playwright

from app.config import Config
from app.engine.base import RegisterEngine, RegistrationResult
from app.proxy import ProxyManager

SIGNUP_URL = "https://www.trae.ai/sign-up"


class BrowserEngine(RegisterEngine):
    name = "browser"

    def __init__(self, cfg: Config, proxy: ProxyManager):
        self.cfg = cfg
        self.proxy = proxy
        self._pw = None
        self._browser = None

    async def __aenter__(self):
        self._pw = await async_playwright().start()
        proxy_cfg = self.proxy.playwright_proxy()
        self._browser = await self._pw.chromium.launch(
            headless=self.cfg.headless,
            proxy=proxy_cfg,
        )
        return self

    async def __aexit__(self, *exc):
        if self._browser:
            await self._browser.close()
        if self._pw:
            await self._pw.stop()

    async def _new_context(self, email: str, request_id: str):
        """独立 context + 请求拦截记录。"""
        ctx = await self._browser.new_context()
        page = await ctx.new_page()
        log_dir = self.cfg.logs_dir / "requests"
        log_dir.mkdir(parents=True, exist_ok=True)
        log_file = log_dir / f"{request_id}.jsonl"

        async def _log(route):
            entry = {
                "ts": time.time(),
                "method": route.request.method,
                "url": route.request.url,
                "headers": dict(route.request.headers),
                "post_data": route.request.post_data,
            }
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            await route.continue_()

        await ctx.route("**/*", _log)
        return ctx, page

    async def register(self, email: str, request_id: str) -> RegistrationResult:
        password = f"Trae@{int(time.time())}x"
        ctx, page = await self._new_context(email, request_id)
        try:
            await page.goto(SIGNUP_URL, timeout=60000)
            # ① 填邮箱
            await page.get_by_placeholder("Email").fill(email)
            # ② 发送验证码(trae 的 Send Code 是 div,非 button)
            await page.locator(".send-code").click()
            # ③ 等待 MailOps 验证码 —— 由 pool 层轮询注入,此处返回等待中
            #    (验证码由外部 wait_for_code 拿到后调用 self.submit_code)
            await page.wait_for_timeout(500)
            return RegistrationResult(
                ok=True, email=email, password=password,
                credentials={"_pending": True, "_request_id": request_id},
            )
        except Exception as e:  # noqa: BLE001
            shot = self.cfg.screenshots_dir / f"{request_id}.png"
            self.cfg.screenshots_dir.mkdir(parents=True, exist_ok=True)
            await page.screenshot(path=str(shot))
            return RegistrationResult.failure(email, f"{type(e).__name__}: {e}")
        finally:
            await ctx.close()

    async def submit_code(self, request_id: str, code: str) -> RegistrationResult:
        """补充步骤:填入验证码 → 密码 → 提交。由 pool 在拿到验证码后调用。"""
        raise NotImplementedError("submit_code 在 Task 7 与 pool 集成后实现")

    async def fetch_credentials(self, email: str, password: str) -> dict:
        """登录并抓取 cookie/access_token/refresh_token。"""
        ctx, page = await self._new_context(email, f"login-{int(time.time())}")
        try:
            await page.goto("https://www.trae.ai/login", timeout=60000)
            await page.get_by_placeholder("Email").fill(email)
            await page.get_by_placeholder("Password").fill(password)
            await page.locator(".btn-submit").click()
            await page.wait_for_url("**/ide**", timeout=60000)
            cookies = await ctx.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            return {"cookie": cookie_str, "access_token": "", "refresh_token": ""}
        finally:
            await ctx.close()

    async def run_full(self, email: str, request_id: str,
                       code_provider) -> RegistrationResult:
        """完整注册流程。code_provider: async (email) -> str 验证码提供者。"""
        password = f"Trae@{int(time.time())}x"
        ctx, page = await self._new_context(email, request_id)
        try:
            await page.goto(SIGNUP_URL, timeout=60000)
            await page.get_by_placeholder("Email").fill(email)
            await page.locator(".send-code").click()

            code = await code_provider(email)
            if not code:
                return RegistrationResult.failure(email, "验证码获取失败")

            await page.get_by_placeholder("Verification code").fill(code)
            await page.get_by_placeholder("Password").fill(password)
            await page.locator(".btn-submit").click()
            await page.wait_for_url("**/ide**", timeout=60000)  # 注册成功进入 IDE

            # 凭据抓取:当前页面 cookie
            cookies = await ctx.cookies()
            cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in cookies)
            return RegistrationResult.success(
                email, password,
                credentials={"cookie": cookie_str,
                             "access_token": "", "refresh_token": ""},
            )
        except Exception as e:  # noqa: BLE001
            shot = self.cfg.screenshots_dir / f"{request_id}.png"
            self.cfg.screenshots_dir.mkdir(parents=True, exist_ok=True)
            try:
                await page.screenshot(path=str(shot))
            except Exception:
                pass
            return RegistrationResult.failure(email, f"{type(e).__name__}: {e}")
        finally:
            await ctx.close()
