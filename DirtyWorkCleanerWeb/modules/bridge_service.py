import re
from typing import Dict, List, Tuple

import pandas as pd

from DirtyWorkCleaner_text_typing import build_result


def extract_expense_type(voucher_text: str) -> str:
    match = re.search(r"摘要[:：](.+?报销)", voucher_text)
    if match:
        text = match.group(1)
        for target in ["差旅费", "管理费用", "销售费用", "研发费用", "制造费用", "运输费", "折旧", "摊销", "内部结转"]:
            if target in text:
                return target
    return "其他"


def extract_voucher_no(voucher_text: str) -> str:
    match = re.search(r"API\d{8,}", voucher_text)
    return match.group(0) if match else "AUTO"


def extract_voucher_amount(voucher_text: str):
    match = re.search(r"凭证金额[:：]?\s*([\d\.]+)", voucher_text)
    if match:
        return float(match.group(1))
    return None


def extract_amount_from_attachment(text: str) -> float:
    match = re.search(r"价税合计[:：]?\s*([\d\.]+)", text)
    if match:
        return float(match.group(1))
    match = re.search(r"票价[:：]?\s*([\d\.]+)", text)
    if match:
        return float(match.group(1))
    return 0.0


def sum_attachment_amounts(attachment_texts: List[str]) -> float:
    return round(sum(extract_amount_from_attachment(text) for text in attachment_texts), 2)


def build_prefill_row(voucher_text: str, attachment_texts: List[str]) -> Dict:
    expense_type = extract_expense_type(voucher_text)
    voucher_no = extract_voucher_no(voucher_text)
    voucher_amount = extract_voucher_amount(voucher_text)
    total_attachment_amount = sum_attachment_amounts(attachment_texts)

    return {
        "凭证号": voucher_no,
        "费用类型": expense_type,
        "凭证金额": voucher_amount,
        "是否提供凭证": True,
        "附件金额合计": total_attachment_amount,
        "是否使用抽样": False,
        "附件总数量": len(attachment_texts),
        "抽样平均金额": None,
        "处理状态": "未处理",
        "是否无附件类": False,
        "原始凭证文本": voucher_text,
    }


def build_prefill_df(voucher_text: str, attachment_texts: List[str]) -> pd.DataFrame:
    return pd.DataFrame([build_prefill_row(voucher_text, attachment_texts)])


def build_check_log(
    summary_df: pd.DataFrame,
    details_df: pd.DataFrame,
    prefill_df: pd.DataFrame,
    result_df: pd.DataFrame,
) -> pd.DataFrame:
    detail_types = "、".join(details_df["附件类型"].astype(str).tolist()) if not details_df.empty else ""
    review_reason = summary_df.loc[0, "复核原因"] if ("复核原因" in summary_df.columns and not summary_df.empty) else ""

    row_prefill = prefill_df.iloc[0].to_dict() if not prefill_df.empty else {}
    row_result = result_df.iloc[0].to_dict() if not result_df.empty else {}

    log_row = {
        "凭证号": row_prefill.get("凭证号", ""),
        "费用类型": row_prefill.get("费用类型", ""),
        "附件类型": detail_types,
        "附件金额合计": row_prefill.get("附件金额合计", ""),
        "附件数量": row_prefill.get("附件总数量", ""),
        "模块1是否人工复核": summary_df.loc[0, "是否人工复核"] if ("是否人工复核" in summary_df.columns and not summary_df.empty) else "",
        "模块1复核原因": review_reason,
        "模块2是否需要附件": row_result.get("是否需要附件", ""),
        "模块2判断方式": row_result.get("判断方式", ""),
        "模块2核查状态": row_result.get("核查状态", ""),
        "模块2建议动作": row_result.get("建议动作", ""),
        "附件需求AI置信度": row_result.get("附件需求AI置信度", ""),
        "附件需求AI理由": row_result.get("附件需求AI理由", ""),
    }
    return pd.DataFrame([log_row])


def run_module1_to_prefill(
    voucher_text: str,
    attachment_files_data: List[Tuple[str, str]],
    is_no_attachment_case: bool = False,
) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    summary_df, details_df = build_result(voucher_text, attachment_files_data)
    attachment_texts = [text for _, text in attachment_files_data]
    prefill_df = build_prefill_df(voucher_text, attachment_texts)
    prefill_df["模块1是否人工复核"] = summary_df.loc[0, "是否人工复核"] == "TRUE"
    prefill_df["是否无附件类"] = bool(is_no_attachment_case)
    return summary_df, details_df, prefill_df
