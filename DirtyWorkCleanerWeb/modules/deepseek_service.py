import os
import json
from openai import OpenAI


class DeepSeekConfigError(Exception):
    pass


def get_deepseek_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekConfigError("未检测到环境变量 DEEPSEEK_API_KEY。请先在终端中设置 API Key。")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def build_audit_prompt(result_row: dict, log_row: dict) -> str:
    return f"""
你是审计底稿复核助手。请根据以下结构化核查结果，输出三部分内容：
1. 【风险原因】
2. 【审计含义】
3. 【建议后续动作】

要求：
- 使用中文
- 语言简洁、专业、像审计助理在写复核意见
- 不要照抄原字段，直接提炼结论
- 如果核查状态是“已到位”，也要说明为什么可继续流程
- 如果核查状态是“需人工复核”，重点说明人工复核点

核查结果：
凭证号：{result_row.get("凭证号", "")}
费用类型：{result_row.get("费用类型", "")}
凭证金额：{result_row.get("凭证金额", "")}
附件/估计金额：{result_row.get("附件/估计金额", "")}
判断方式：{result_row.get("判断方式", "")}
是否需要附件：{result_row.get("是否需要附件", "")}
判断来源：{result_row.get("判断来源", "")}
模块1是否人工复核：{result_row.get("模块1是否人工复核", "")}
核查状态：{result_row.get("核查状态", "")}
建议动作：{result_row.get("建议动作", "")}

判断日志：
附件类型：{log_row.get("附件类型", "")}
附件金额合计：{log_row.get("附件金额合计", "")}
附件数量：{log_row.get("附件数量", "")}
模块1是否人工复核：{log_row.get("模块1是否人工复核", "")}
模块1复核原因：{log_row.get("模块1复核原因", "")}
模块2是否需要附件：{log_row.get("模块2是否需要附件", "")}
模块2判断方式：{log_row.get("模块2判断方式", "")}
模块2核查状态：{log_row.get("模块2核查状态", "")}
模块2建议动作：{log_row.get("模块2建议动作", "")}
""".strip()


def generate_ai_review(result_row: dict, log_row: dict, model: str = "deepseek-chat") -> str:
    client = get_deepseek_client()
    prompt = build_audit_prompt(result_row, log_row)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一个严谨、克制、专业的审计复核助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        stream=False,
    )
    return (response.choices[0].message.content or "").strip()


def build_need_attachment_prompt(voucher_text: str, expense_type: str = "") -> str:
    return f"""
你是审计执行助手。你的任务是判断：这条凭证通常是否需要附件支持（如发票、车票、报销单、合同、行程单等）。

判断原则：
1. 只基于提供的凭证文本与费用类型判断。
2. 不得编造事实，不得联网。
3. 如果无法稳定判断，返回 uncertain。
4. 对折旧、摊销、内部结转、计提、结转类分录，通常倾向于不需要外部附件。
5. 对差旅费、报销、运输费、采购、销售费用、管理费用、研发费用等，通常倾向于需要附件。

请严格输出 JSON，不要输出任何额外文字：
{{
  "need_attachment": true,
  "confidence": 0.85,
  "reason": "一句话理由"
}}
或
{{
  "need_attachment": false,
  "confidence": 0.85,
  "reason": "一句话理由"
}}
或
{{
  "need_attachment": null,
  "confidence": 0.35,
  "reason": "一句话理由"
}}

费用类型：{expense_type}
凭证文本：
{voucher_text}
""".strip()


def ai_need_attachment(voucher_text: str, expense_type: str = "", model: str = "deepseek-chat") -> dict:
    client = get_deepseek_client()
    prompt = build_need_attachment_prompt(voucher_text=voucher_text, expense_type=expense_type)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一个严谨、克制、专业的审计执行助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
        stream=False,
    )
    text = (response.choices[0].message.content or "").strip()

    try:
        data = json.loads(text)
    except Exception:
        return {
            "need_attachment": None,
            "confidence": 0.0,
            "reason": f"AI 输出解析失败：{text[:80]}"
        }

    need_attachment = data.get("need_attachment", None)
    if need_attachment not in [True, False, None]:
        need_attachment = None

    try:
        confidence = float(data.get("confidence", 0.0))
    except Exception:
        confidence = 0.0
    confidence = max(0.0, min(1.0, confidence))

    reason = str(data.get("reason", "")).strip()

    return {
        "need_attachment": need_attachment,
        "confidence": confidence,
        "reason": reason,
    }
