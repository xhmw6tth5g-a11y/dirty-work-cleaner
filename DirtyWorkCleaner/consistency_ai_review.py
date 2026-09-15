import json
import os
from typing import Tuple

import pandas as pd
from openai import OpenAI


class DeepSeekConfigError(Exception):
    pass


def get_deepseek_client() -> OpenAI:
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise DeepSeekConfigError("未检测到环境变量 DEEPSEEK_API_KEY。请先在终端中设置 API Key。")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")


def build_consistency_review_prompt(row: dict) -> str:
    return f"""
你是审计底稿复核助手。请基于以下一致性检查结果，生成三部分内容：
1. 审阅结论
2. 风险提示
3. 建议动作

要求：
- 使用中文
- 简洁、专业、克制
- 只基于提供字段，不得编造
- 不要使用“舞弊”“违规”等严重定性
- 输出严格为 JSON，不要输出额外文字

输出格式：
{{
  "审阅结论": "...",
  "风险提示": "...",
  "建议动作": "..."
}}

输入信息：
样本序号：{row.get("样本序号", "")}
凭证号：{row.get("凭证号", "")}
科目/费用类型：{row.get("科目/费用类型", "")}
底稿金额：{row.get("底稿金额", "")}
凭证金额：{row.get("凭证金额", "")}
底稿日期：{row.get("底稿日期", "")}
凭证日期：{row.get("凭证日期", "")}
附件数量：{row.get("附件数量", "")}
是否在抽凭清单中：{row.get("是否在抽凭清单中", "")}
是否找到实际凭证：{row.get("是否找到实际凭证", "")}
金额是否一致：{row.get("金额是否一致", "")}
日期是否一致：{row.get("日期是否一致", "")}
一致性状态：{row.get("一致性状态", "")}
""".strip()


def _fallback_review(row: dict) -> Tuple[str, str, str]:
    status = str(row.get("一致性状态", "")).strip()
    if status == "一致":
        return (
            "该样本与抽凭清单记录一致，可进入后续Docu底稿流程。",
            "未发现明显一致性异常。",
            "可优先处理该样本。"
        )
    if status == "凭证缺失":
        return (
            "抽凭清单中存在该样本，但当前未找到对应实际凭证。",
            "该样本暂不具备进入底稿编制的材料基础。",
            "先补齐对应凭证，再进入Docu底稿流程。"
        )
    if status == "金额不一致":
        return (
            "该样本凭证金额与抽凭清单底稿金额不一致。",
            "可能存在底稿录入错误、样本错配或凭证金额记录不完整。",
            "核对底稿金额、凭证金额及抽样清单来源。"
        )
    if status == "日期不一致":
        return (
            "该样本凭证日期与抽凭清单底稿日期不一致。",
            "可能存在底稿录入错误或样本对应关系偏差。",
            "核对底稿日期与凭证日期，确认是否录入错误或样本错配。"
        )
    if status == "多余凭证":
        return (
            "当前凭证不在抽凭清单范围内。",
            "若误纳入样本包，可能影响后续底稿执行准确性。",
            "确认该凭证是否误放入样本包。"
        )
    return (
        "该样本存在多项差异，暂不宜直接进入底稿流程。",
        "当前一致性判断存在冲突或信息不充分。",
        "建议先人工复核后再做底稿。"
    )


def ai_review_consistency_row(row: dict, model: str = "deepseek-chat") -> dict:
    client = get_deepseek_client()
    prompt = build_consistency_review_prompt(row)

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": "你是一个严谨、克制、专业的审计复核助手。"},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
        stream=False,
    )
    text = (response.choices[0].message.content or "").strip()

    try:
        data = json.loads(text)
        return {
            "审阅结论": str(data.get("审阅结论", "")).strip(),
            "风险提示": str(data.get("风险提示", "")).strip(),
            "建议动作": str(data.get("建议动作", "")).strip(),
        }
    except Exception:
        conclusion, risk, action = _fallback_review(row)
        return {
            "审阅结论": conclusion,
            "风险提示": risk,
            "建议动作": action,
        }


def enrich_consistency_reviews(result_df: pd.DataFrame) -> pd.DataFrame:
    out = result_df.copy()
    conclusions = []
    risks = []
    actions = []

    for _, row in out.iterrows():
        try:
            review = ai_review_consistency_row(row.to_dict())
        except Exception:
            conclusion, risk, action = _fallback_review(row.to_dict())
            review = {
                "审阅结论": conclusion,
                "风险提示": risk,
                "建议动作": action,
            }

        conclusions.append(review["审阅结论"])
        risks.append(review["风险提示"])
        actions.append(review["建议动作"])

    out["审阅结论"] = conclusions
    out["风险提示"] = risks
    out["建议动作"] = actions
    return out
