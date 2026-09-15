import json
import os
from openai import OpenAI


class DeepSeekConfigError(Exception):
    pass


def get_deepseek_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekConfigError("未检测到环境变量 DEEPSEEK_API_KEY。")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def build_paper_attachment_prompt(result_row: dict, log_row: dict) -> str:
    return f"""
你是审计执行复核助手。请基于“拍凭OCR得到的凭证信息 + 纸质附件情况录入信息”，输出严格三段式结果。

要求：
1. 语气专业、克制、像审计助理在写复核意见。
2. 只基于输入信息判断，不得编造不存在的附件或业务背景。
3. 允许使用“代表性录入”“纸质附件”“人工确认”等表述。
4. 如果无附件，应明确说明该样本不进入Docu或底稿流程。
5. 如果采用代表性录入，应说明这是高重复/同质材料的简化录入方式，而非全量附件识别。
6. 不得使用“舞弊”“违规”“虚假”等严重定性。

请严格按以下格式输出，不要增加其他内容：

【风险判断】
一句话给出结论。

【原因】
1-2句话说明依据。

【建议】
给出1-2条可执行后续动作。

输入信息：
凭证号：{result_row.get("凭证号", "")}
费用类型：{result_row.get("费用类型", "")}
凭证金额：{result_row.get("凭证金额", "")}
附件/估计金额：{result_row.get("附件/估计金额", "")}
核查状态：{result_row.get("核查状态", "")}
建议动作：{result_row.get("建议动作", "")}
是否需要附件：{result_row.get("是否需要附件", "")}

附件类型：{log_row.get("附件类型", "")}
附件数量：{log_row.get("附件数量", "")}
代表性录入：{log_row.get("代表性录入", "")}
代表性录入数量：{log_row.get("代表性录入数量", "")}
是否同质：{log_row.get("是否同质", "")}
人工确认覆盖：{log_row.get("人工确认覆盖", "")}
是否发现异常：{log_row.get("是否发现异常", "")}
模块1复核原因：{log_row.get("模块1复核原因", "")}
备注：{log_row.get("备注", "")}
""".strip()


def _fallback_text(result_row: dict, log_row: dict) -> str:
    state = str(result_row.get("核查状态", "")).strip()
    review_reason = str(log_row.get("模块1复核原因", "")).strip()

    if state == "已剔除（无附件类）":
        return """【风险判断】
该样本无附件，不进入Docu或底稿流程。

【原因】
当前录入信息显示该样本无附件，按流程无需继续执行附件底稿程序。

【建议】
记录该样本无需进入底稿的原因，并保留凭证基础信息。"""

    if state == "已到位":
        return """【风险判断】
当前材料基本到位，可继续后续流程。

【原因】
凭证信息已取得，附件数量及金额覆盖情况未见明显不足，现有信息下可继续推进。

【建议】
继续进入后续底稿流程，并保留本次录入说明。"""

    if state == "金额覆盖疑似不足":
        return """【风险判断】
当前材料覆盖情况疑似不足，需进一步核实。

【原因】
录入的附件估计金额未能稳定覆盖凭证金额，现有信息下不足以直接进入后续流程。

【建议】
补充说明代表性录入口径，并进一步核实附件覆盖情况。"""

    if state == "材料缺失":
        return """【风险判断】
当前纸质附件信息不足，暂不宜直接进入后续流程。

【原因】
附件数量或金额信息不足，无法形成稳定判断。

【建议】
补充附件情况录入，并由项目组进一步核实。"""

    if state == "需人工复核":
        return f"""【风险判断】
该样本需人工复核后再决定是否继续流程。

【原因】
当前录入信息已触发人工复核标记。{review_reason}

【建议】
优先由项目组复核纸质附件情况，并补充差异说明。"""

    return """【风险判断】
当前无法形成稳定判断。

【原因】
现有凭证及纸质附件情况信息不足，暂不能直接给出明确结论。

【建议】
补充附件情况录入后再判断。"""


def generate_paper_attachment_ai_review(result_row: dict, log_row: dict, model: str = "deepseek-chat") -> str:
    client = get_deepseek_client()
    prompt = build_paper_attachment_prompt(result_row, log_row)

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": "你是严谨、克制、专业的审计执行复核助手。"},
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
            stream=False,
        )
        return (response.choices[0].message.content or "").strip()
    except Exception:
        return _fallback_text(result_row, log_row)
