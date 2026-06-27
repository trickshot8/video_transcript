"""B站链接解析 + 字幕抓取（CC / AI 两级）。

字幕来源说明：
- B站官方 player/v2 接口返回 subtitle.subtitles 列表，里面区分人工(CC)字幕和 AI 字幕。
- 该接口现在基本都需要登录态(SESSDATA)才会返回非空列表。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse, parse_qs

import requests

import config
from pipeline import wbi

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

BV_RE = re.compile(r"(BV[0-9A-Za-z]{10})")
AV_RE = re.compile(r"av(\d+)", re.IGNORECASE)
# 短链域名: b23.tv（App 主用）/ bili2233.cn（备用）；只取短码字符，避免吞掉后面紧跟的中文
B23_RE = re.compile(r"https?://(?:b23\.tv|bili2233\.cn)/[A-Za-z0-9]+", re.IGNORECASE)


@dataclass
class Segment:
    start: float  # 秒
    end: float
    text: str


@dataclass
class SubtitleResult:
    segments: list[Segment]
    level: str          # "cc" 人工字幕 / "ai" AI字幕
    lan_doc: str        # 语言描述，如 "中文(中国)"


@dataclass
class VideoInfo:
    bvid: str
    cid: int
    title: str
    page_title: str
    owner: str
    duration: int       # 秒


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    if config.BILIBILI_SESSDATA:
        s.cookies.set("SESSDATA", config.BILIBILI_SESSDATA, domain=".bilibili.com")
    return s


def resolve_url(raw: str) -> tuple[str, Optional[int]]:
    """从任意分享文本中提取出 (bvid 或 avXXX, 分P号)。

    支持：
    - 完整链接 https://www.bilibili.com/video/BVxxxx?p=2
    - 短链 https://b23.tv/xxxxx （含分享文案里夹带的）
    - 纯 BV 号 / av 号
    """
    raw = raw.strip()
    page: Optional[int] = None

    # 先把分享文案里的短链拎出来并展开
    m = B23_RE.search(raw)
    if m:
        short = m.group(0).rstrip("）)】」]>，,。.")
        try:
            resp = _session().get(short, allow_redirects=True, timeout=15)
            raw = resp.url
        except requests.RequestException:
            raw = short

    # 解析分P
    try:
        qs = parse_qs(urlparse(raw).query)
        if "p" in qs:
            page = int(qs["p"][0])
    except (ValueError, TypeError):
        page = None

    bv = BV_RE.search(raw)
    if bv:
        return bv.group(1), page
    av = AV_RE.search(raw)
    if av:
        return f"av{av.group(1)}", page

    raise ValueError(f"无法从输入中识别 B 站视频 ID: {raw!r}")


def get_video_info(vid: str, page: Optional[int] = None) -> VideoInfo:
    s = _session()
    if vid.lower().startswith("av"):
        params = {"aid": vid[2:]}
    else:
        params = {"bvid": vid}
    r = s.get("https://api.bilibili.com/x/web-interface/view", params=params, timeout=15)
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        raise RuntimeError(f"取视频信息失败: code={data.get('code')} {data.get('message')}")
    d = data["data"]
    pages = d.get("pages") or []
    # 选定分P
    sel = None
    if page and pages:
        for pg in pages:
            if pg.get("page") == page:
                sel = pg
                break
    if sel is None and pages:
        sel = pages[0]
    cid = sel["cid"] if sel else d["cid"]
    page_title = sel.get("part", "") if sel else ""
    return VideoInfo(
        bvid=d["bvid"],
        cid=int(cid),
        title=d.get("title", ""),
        page_title=page_title or d.get("title", ""),
        owner=(d.get("owner") or {}).get("name", ""),
        duration=int(d.get("duration", 0)),
    )


def _is_ai(sub: dict) -> bool:
    lan = (sub.get("lan") or "").lower()
    doc = sub.get("lan_doc") or ""
    return lan.startswith("ai") or "自动" in doc or "ai" in lan


def fetch_bilibili_subtitle(info: VideoInfo) -> Optional[SubtitleResult]:
    """从 player/wbi/v2 取字幕列表，优先人工CC字幕，其次AI字幕。取不到返回 None。

    必须用 WBI 签名的 wbi/v2 接口：未签名的旧 player/v2 会被风控返回错乱字幕。
    """
    s = _session()
    params = wbi.sign({"bvid": info.bvid, "cid": info.cid}, s)
    r = s.get(
        "https://api.bilibili.com/x/player/wbi/v2",
        params=params,
        timeout=15,
    )
    r.raise_for_status()
    data = r.json()
    if data.get("code") != 0:
        return None
    subs = (((data.get("data") or {}).get("subtitle") or {}).get("subtitles")) or []
    if not subs:
        return None

    manual = [x for x in subs if not _is_ai(x)]
    ai = [x for x in subs if _is_ai(x)]
    chosen = manual[0] if manual else (ai[0] if ai else None)
    if chosen is None:
        return None
    level = "cc" if chosen in manual else "ai"

    url = chosen.get("subtitle_url") or ""
    if url.startswith("//"):
        url = "https:" + url
    if not url:
        return None

    jr = s.get(url, timeout=20)
    jr.raise_for_status()
    body = jr.json().get("body") or []
    segments = [
        Segment(start=float(b.get("from", 0)), end=float(b.get("to", 0)),
                text=(b.get("content") or "").strip())
        for b in body
        if (b.get("content") or "").strip()
    ]
    if not segments:
        return None
    return SubtitleResult(segments=segments, level=level,
                          lan_doc=chosen.get("lan_doc", ""))
