"""服务端字幕总结：调 DeepSeek（OpenAI 兼容接口）生成中文摘要。

设计原则：摘要是锦上添花，**失败绝不能影响主流程**——拿不到摘要就返回 None，
字幕照常输出。
"""
from __future__ import annotations

import logging

import requests

import config

log = logging.getLogger("summarize")

_SYSTEM = """你是严谨、中立的视频内容编辑。首要任务是客观还原视频讲了什么、依据是什么、表达方式有什么特点；观看参考只是辅助，不替用户裁决视频值不值得看。
评价信息时应结合视频类型：知识讲解重视因果与来源，观点评论重视论证，产品实测重视体验与画面，娱乐视频的幽默、互动和演示本身也可能是核心价值。
不得把作者的投资、医疗、法律意见改写为你的建议，也不要使用居高临下、审判或嘲讽性的措辞。"""

_PROMPT = """下面是一个视频的字幕全文，可能由语音识别生成并含有少量错别字。

请先在内部识别视频类型、全文主线及各部分篇幅，再生成客观内容速览。不要只依据标题、开头或结尾。

输出要求：
1. 以内容还原为主，不使用“有营养”“没价值”“值得/不值得”等裁决性表达。
2. 核心内容覆盖主要主题，优先保留关键数字、时间、比例、结论及其依据；不得编造或自行计算。
3. 区分可核实事实、视频引用、作者个人经历、主观观点和预测，必要时使用“视频称”“作者认为”。
4. 根据视频类型理解其价值：不要把必要的原理展开、实拍演示、幽默互动或叙事过程简单视为灌水。
5. 只有字幕明确说明赞助、合作、返佣、推广链接或购买引导时，才能认定为商业推广；仅提及品牌、产品或开玩笑不算广告。
6. “信息边界”中性说明数据来源、实测条件、个人立场和预测的不确定性，不要把正常的个人表达写成缺点清单。
7. “观看参考”说明完整视频相较摘要额外提供的画面、推理、案例、情绪或娱乐体验，帮助用户自行选择，不给强制结论。
8. 根据上下文修正常见识别错误，不确定时采用保守表述。原文只给出月日或相对时间时，不得自行补充年份；专名、数字或时间存在冲突时保留模糊表述。

严格按以下格式输出，不使用其他标题或前后缀：

内容概览：<不超过70字，客观概括全文>
内容类型：<如知识讲解、观点评论、产品实测、娱乐展示或综合类型>
适合：<最可能对内容感兴趣的人群>

核心内容：
- <4到6条，每条一个完整信息点>

内容特点：
- <1到3条，描述论述方式、实测/案例、表达风格及明确的商业内容>

信息边界：
- <1到3条，中性说明事实、观点、预测和证据范围；没有明显边界则写“未发现明显信息边界”>

观看参考：<说明完整视频额外提供什么，以及只读摘要能获得什么，不替用户作价值裁决>

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
