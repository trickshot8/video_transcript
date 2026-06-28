"""服务端字幕总结：调 DeepSeek（OpenAI 兼容接口）生成中文摘要。

设计原则：摘要是锦上添花，**失败绝不能影响主流程**——拿不到摘要就返回 None，
字幕照常输出。
"""
from __future__ import annotations

import logging

import requests

import config

log = logging.getLogger("summarize")

_SYSTEM = """你是严谨的视频内容筛选编辑，帮助用户快速判断一个视频有没有信息价值、是否值得花时间观看。
评价应基于信息密度、具体证据、推理价值、独特经验、重复灌水和商业推广，而不是你是否赞同作者观点。
不得把作者的投资、医疗、法律意见改写为你的建议；高风险或规避监管内容只中性概括其争议和风险。"""

_PROMPT = """下面是一个视频的字幕全文，可能由语音识别生成并含有少量错别字。

请先在内部识别全文主线及其篇幅，再判断观看价值。不要只依据标题、开头或结尾。

观看建议只能选择以下一项：
- 值得完整看：信息密度高，有重要证据、推理过程或独特经验，仅看摘要会损失明显价值。
- 按需跳看：部分内容有价值，但存在较多重复、闲聊、广告，或只有特定章节值得看。
- 摘要足够：核心信息可被少量要点完整覆盖，原视频主要是重复、泛泛观点、情绪表达或推广。

输出要求：
1. 一句话直接说明推荐等级及原因，不迎合标题，不因视频较长而自动降低评价。必须具体指出有价值的内容和主要时间成本，禁止只写“信息有限”“内容较多”“广告较多”等空泛判断。
2. 核心收获覆盖所有主要主题，优先保留关键数字、时间、比例、结论及其依据，不得编造或自行计算。
3. 区分可核实事实、作者个人经历、作者观点和预测，必要时使用“视频称”“作者认为”。
4. 注意事项指出证据不足、明显偏见、过时风险、商业推广、重复灌水或高风险观点；不要复述具体规避方法。
5. 根据上下文修正常见识别错误，不确定时采用保守表述。

严格按以下格式输出，不使用其他标题或前后缀：

观看建议：<值得完整看 / 按需跳看 / 摘要足够>
一句话判断：<不超过60字，概括推荐理由>
重点看：<最有价值、最难被摘要替代的具体主题；若摘要已覆盖全部价值则写“摘要已覆盖核心信息”>
可跳过：<重复、闲聊、广告、证据薄弱或偏题的具体内容；没有则写“无明显可跳过内容”>
适合：<最可能从视频中获益的人；不适合任何特定人群则写“一般观众”>

核心收获：
- <3到5条，每条一个完整信息点>

注意事项：
- <1到3条，帮助用户判断可信度和时间成本>

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
                "temperature": 0.1,
                "max_tokens": 800,
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
