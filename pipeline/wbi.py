"""B站 WBI 签名。

新版接口（如 x/player/wbi/v2）要求对请求参数做 WBI 签名，否则会被风控
返回错乱/随机的数据（实测：未签名时 subtitle_url 会指向其它视频的字幕）。

签名流程：
1. 从 nav 接口拿 img_key / sub_key
2. 按固定置换表重排拼接出 mixin_key（取前32位）
3. 给参数加 wts 时间戳、按键排序、urlencode 后接 mixin_key 求 md5 → w_rid
"""
from __future__ import annotations

import hashlib
import time
from urllib.parse import urlencode

import requests

# 固定字节置换表
_MIXIN_KEY_ENC_TAB = [
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35, 27, 43, 5, 49,
    33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13, 37, 48, 7, 16, 24, 55, 40, 61,
    26, 17, 0, 1, 60, 51, 30, 4, 22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36,
    20, 34, 44, 52,
]

# img/sub key 每天才变，缓存 1 小时
_cache: dict[str, object] = {"mixin": None, "ts": 0.0}


def _mixin_key(orig: str) -> str:
    return "".join(orig[i] for i in _MIXIN_KEY_ENC_TAB)[:32]


def _fetch_mixin_key(session: requests.Session) -> str:
    nav = session.get(
        "https://api.bilibili.com/x/web-interface/nav", timeout=15
    ).json()
    wbi = (nav.get("data") or {}).get("wbi_img") or {}
    img = wbi["img_url"].rsplit("/", 1)[-1].split(".")[0]
    sub = wbi["sub_url"].rsplit("/", 1)[-1].split(".")[0]
    return _mixin_key(img + sub)


def _get_mixin_key(session: requests.Session) -> str:
    now = time.time()
    if not _cache["mixin"] or now - float(_cache["ts"]) > 3600:
        _cache["mixin"] = _fetch_mixin_key(session)
        _cache["ts"] = now
    return _cache["mixin"]  # type: ignore[return-value]


def sign(params: dict, session: requests.Session) -> dict:
    """返回带 wts + w_rid 签名的新参数字典。"""
    mixin = _get_mixin_key(session)
    signed = dict(params)
    signed["wts"] = int(time.time())
    signed = dict(sorted(signed.items()))
    # 过滤值里的特殊字符
    signed = {
        k: "".join(c for c in str(v) if c not in "!'()*")
        for k, v in signed.items()
    }
    query = urlencode(signed)
    signed["w_rid"] = hashlib.md5((query + mixin).encode()).hexdigest()
    return signed
