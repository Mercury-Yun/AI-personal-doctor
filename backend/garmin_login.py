"""佳明首次登录脚本（在板子上交互运行，可处理短信/邮箱验证码）。

用法（项目根目录、venv 下）：
    .venv/bin/python -m backend.garmin_login

流程：读取 .env 的 GARMIN_EMAIL/GARMIN_PASSWORD（缺则提示输入）→ 登录 garmin.cn →
若需要验证码会提示输入 → 成功后把 token 保存到 GARMIN_TOKEN_DIR，之后后端服务免密复用。

说明：garmin.cn 对「账号/密码错误」返回 HTTP 401（国际版返回 200+页面报错），garth
默认在非 2xx 上直接抛异常、吞掉页面里的真实原因。这里对国内版走容错登录：即便非
2xx 也解析页面标题，区分「成功 / 需要验证码(MFA) / 账号密码错」并打印服务器原话。
"""

import getpass
import logging
import re
import sys
from datetime import date
from pathlib import Path

from .config import get_settings


def _extract_status_error(html: str) -> str:
    m = re.search(r'id="status"[^>]*>(.*?)</div>', html, re.S)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip()
    return ""


def _cn_login(email: str, password: str, token_dir: str, prompt_mfa) -> bool:
    """国内 garmin.cn 容错登录：成功则保存 token 并返回 True。"""
    from garth import sso
    from garth.http import Client

    client = Client(domain="garmin.cn")
    sso_base = "https://sso.garmin.cn/sso"
    sso_embed = sso_base + "/embed"
    embed_params = dict(id="gauth-widget", embedWidget="true", gauthHost=sso_base)
    signin_params = {
        **embed_params,
        **dict(
            gauthHost=sso_embed,
            service=sso_embed,
            source=sso_embed,
            redirectAfterAccountLoginUrl=sso_embed,
            redirectAfterAccountCreationUrl=sso_embed,
        ),
    }

    client.get("sso", "/sso/embed", params=embed_params)
    client.get("sso", "/sso/signin", params=signin_params, referrer=True)
    csrf = sso.get_csrf_token(client.last_resp.text)

    def _post(path: str, data: dict):
        # 直接用底层 session 提交，绕开 garth 的 raise_for_status，好读到 401 页面内容
        resp = client.sess.post(
            f"https://sso.garmin.cn{path}",
            params=signin_params,
            data=data,
            headers={"referer": client.last_resp.url},
            timeout=client.timeout,
        )
        client.last_resp = resp
        return resp

    resp = _post(
        "/sso/signin",
        dict(username=email, password=password, embed="true", _csrf=csrf),
    )
    title = sso.get_title(resp.text)

    if "MFA" in title:
        code = prompt_mfa()
        resp = _post(
            "/sso/verifyMFA/loginEnterMfaCode",
            {
                "mfa-code": code,
                "embed": "true",
                "_csrf": sso.get_csrf_token(resp.text),
                "fromPage": "setupEnterMfaCode",
            },
        )
        title = sso.get_title(resp.text)

    if title != "Success":
        err = _extract_status_error(resp.text) or f"(title={title}, http={resp.status_code})"
        print(f"登录被拒：{err}")
        print(
            "请确认：1) 账号是登录「佳明运动」App 用的手机号/邮箱；"
            "2) 密码正确（区分大小写）；"
            "3) 该账号已设置密码（纯短信验证码注册、从未设过密码的账号无法用密码登录）。"
        )
        return False

    oauth1, oauth2 = sso._complete_login(client)
    client.oauth1_token, client.oauth2_token = oauth1, oauth2
    Path(token_dir).mkdir(parents=True, exist_ok=True)
    client.dump(token_dir)
    print(f"登录成功，token 已保存到: {token_dir}")
    return True


def main() -> int:
    settings = get_settings()
    try:
        from garminconnect import Garmin
    except ImportError:
        print("garminconnect 未安装：请先在 venv 里执行 pip install garminconnect")
        return 1

    email = settings["garmin_email"] or input("佳明账号(邮箱/手机号): ").strip()
    password = settings["garmin_password"] or getpass.getpass("佳明密码: ")
    token_dir = settings["garmin_token_dir"]
    is_cn = settings["garmin_is_cn"]

    if not email or not password:
        print("账号或密码为空，已取消。")
        return 1

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    logging.getLogger("garth").setLevel(logging.INFO)

    print(f"登录中（is_cn={is_cn}）...")
    prompt_mfa = lambda: input("请输入佳明发来的验证码: ").strip()

    if is_cn:
        if not _cn_login(email, password, token_dir, prompt_mfa):
            return 1
    else:
        garmin = Garmin(email=email, password=password, is_cn=is_cn, prompt_mfa=prompt_mfa)
        garmin.login()
        Path(token_dir).mkdir(parents=True, exist_ok=True)
        garmin.garth.dump(token_dir)
        print(f"登录成功，token 已保存到: {token_dir}")

    # 样例校验：用保存的 token 走后端服务同款加载路径拉一条心率
    try:
        g = Garmin(is_cn=is_cn)
        g.login(token_dir)
        hr = g.get_heart_rates(date.today().isoformat()) or {}
        print("样例校验 - 今日静息心率:", hr.get("restingHeartRate"))
    except Exception as exc:  # noqa: BLE001
        print("（提示）拉取样例数据失败，但 token 已保存，可稍后由服务重试：", exc)
    return 0


if __name__ == "__main__":
    sys.exit(main())
