"""服务端字幕总结：调 DeepSeek（OpenAI 兼容接口）生成中文摘要。

设计原则：摘要是锦上添花，**失败绝不能影响主流程**——拿不到摘要就返回 None，
字幕照常输出。
"""
from __future__ import annotations

import logging

import requests

import config

log = logging.getLogger("summarize")

_SYSTEM = "你是中文视频字幕摘要助手。输出简洁、信息密度高，不要寒暄或多余前后缀。"

_PROMPT = """下面是一个视频的字幕全文（可能由语音识别生成，有少量错别字，请据上下文理解）。
请输出中文摘要，格式严格如下：

一句话总结：<不超过40字>

要点：
- <要点1>
- <要点2>
- <3到6条，每条一行，简洁>

视频标题：{title}

字幕全文：
{text}"""


def summarize(title: str, text: str) -> str | None:
    """返回摘要文本；未配置 key 或调用失败时返回 None（不抛异常）。"""
    if not config.SUMMARY_ENABLED:
        return None
    if not config.DEEPSEEK_API_KEY:
        log.warning("未配置 DEEPSEEK_API_KEY，跳过摘要")
        return None
    if not text.strip():
        return None

    try:
        resp = requests.post(
            f"{config.SUMMARY_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": config.SUMMARY_MODEL,
                "messages": [
                    {"role": "system", "content": _SYSTEM},
                    {"role": "user", "content": _PROMPT.format(title=title, text=text)},
                ],
                "temperature": 0.3,
                "stream": False,
            },
            timeout=60,
        )
        resp.raise_for_status()
        data = resp.json()
        content = (data["choices"][0]["message"]["content"] or "").strip()
        return content or None
    except Exception as e:  # noqa: BLE001  摘要失败不影响主流程
        log.warning("摘要生成失败: %s", e)
        return None
