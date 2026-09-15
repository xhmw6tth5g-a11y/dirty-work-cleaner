import pandas as pd
import numpy as np

from deepseek_service import ai_need_attachment

ATTACHMENT_RULES = {
    "差旅费": True,
    "销售费用": True,
    "管理费用": True,
    "研发费用": True,
    "制造费用": True,
    "运输费": True,
    "折旧": False,
    "摊销": False,
    "内部结转": False,
}

DEFAULT_TOLERANCE_RATIO = 0.95
DEFAULT_ABS_TOLERANCE = 50.0
AI_CONFIDENCE_THRESHOLD = 0.75


def normalize_bool(x):
    if pd.isna(x):
        return False
    if isinstance(x, str):
        return x.strip().lower() in ["1", "true", "yes", "y", "是"]
    return bool(x)


def compute_estimated_amount(row):
    if pd.notna(row.get("附件金额合计", np.nan)):
        return float(row["附件金额合计"]), "直接汇总"

    use_sampling = normalize_bool(row.get("是否使用抽样", False))
    if (
        use_sampling
        and pd.notna(row.get("附件总数量", np.nan))
        and pd.notna(row.get("抽样平均金额", np.nan))
    ):
        est = float(row["附件总数量"]) * float(row["抽样平均金额"])
        return est, "抽样估计"

    return np.nan, "未知"


def rule_need_attachment(expense_type: str):
    if expense_type in ATTACHMENT_RULES:
        return ATTACHMENT_RULES[expense_type], "规则判断"
    return True, "规则(默认)"


def need_attachment(expense_type: str, voucher_text: str = ""):
    rule_result, rule_source = rule_need_attachment(expense_type)

    if not voucher_text:
        return rule_result, rule_source, np.nan, ""

    try:
        ai_result = ai_need_attachment(voucher_text=voucher_text, expense_type=expense_type)
    except Exception as e:
        return rule_result, f"{rule_source}（AI调用失败回退）", 0.0, str(e)

    ai_need = ai_result.get("need_attachment", None)
    ai_conf = float(ai_result.get("confidence", 0.0) or 0.0)
    ai_reason = str(ai_result.get("reason", "") or "")

    # AI 高置信时优先；AI 不确定或低置信时回退规则
    if ai_need in [True, False] and ai_conf >= AI_CONFIDENCE_THRESHOLD:
        return bool(ai_need), "AI初判", ai_conf, ai_reason

    return rule_result, f"{rule_source}（AI低置信回退）", ai_conf, ai_reason


def judge_amount(
    v_amount,
    a_amount,
    tolerance_ratio=DEFAULT_TOLERANCE_RATIO,
    abs_tolerance=DEFAULT_ABS_TOLERANCE,
):
    if pd.isna(a_amount) or pd.isna(v_amount):
        return None
    if (a_amount >= v_amount * tolerance_ratio) or (abs(v_amount - a_amount) <= abs_tolerance):
        return True
    return False


def suggest_action(state, expense_type):
    if state == "未提供凭证":
        return "联系客户补充原始凭证"
    if state == "金额覆盖疑似不足":
        if expense_type == "差旅费":
            return "补充车票/行程单或核对票据完整性"
        if expense_type in ["销售费用", "管理费用", "研发费用", "制造费用", "运输费"]:
            return "补充发票/合同/报销单或核对附件完整性"
        return "补充相关附件或提供说明"
    if state == "材料缺失":
        return "补充相关附件（发票/报销单/合同等）"
    if state == "已剔除（无附件类）":
        return "无附件类样本已剔除，不进入Docu底稿流程"
    if state == "无需补要":
        return "无需补要，按规则可继续流程"
    if state == "已到位":
        return "可进入Docu或后续程序"
    if state == "需人工复核":
        return "存在需人工判断材料，建议优先人工复核"
    return ""


def process(
    df: pd.DataFrame,
    tolerance_ratio=DEFAULT_TOLERANCE_RATIO,
    abs_tolerance=DEFAULT_ABS_TOLERANCE,
):
    df = df.copy()

    required_cols = [
        "凭证号",
        "费用类型",
        "凭证金额",
        "是否提供凭证",
        "附件金额合计",
        "是否使用抽样",
        "附件总数量",
        "抽样平均金额",
        "处理状态",
        "模块1是否人工复核",
        "是否无附件类",
        "原始凭证文本",
    ]
    for c in required_cols:
        if c not in df.columns:
            df[c] = np.nan

    df["是否提供凭证"] = df["是否提供凭证"].apply(normalize_bool)
    df["是否使用抽样"] = df["是否使用抽样"].apply(
        lambda x: normalize_bool(x) if pd.notna(x) else False
    )
    df["模块1是否人工复核"] = df["模块1是否人工复核"].apply(normalize_bool)
    df["是否无附件类"] = df["是否无附件类"].apply(
        lambda x: normalize_bool(x) if pd.notna(x) else False
    )

    results = []

    for _, row in df.iterrows():
        voucher = str(row.get("凭证号", "")).strip().upper()
        expense_type = str(row.get("费用类型", "")).strip()
        voucher_text = str(row.get("原始凭证文本", "") or "")
        v_amount = (
            float(row.get("凭证金额", np.nan))
            if pd.notna(row.get("凭证金额", np.nan))
            else np.nan
        )
        provided = normalize_bool(row.get("是否提供凭证", False))
        proc_status = row.get("处理状态", "未处理")
        if pd.isna(proc_status) or proc_status == "":
            proc_status = "未处理"

        need_att, source, ai_conf, ai_reason = need_attachment(expense_type, voucher_text)
        a_amount, method = compute_estimated_amount(row)
        attachment_count = row.get("附件总数量", np.nan)
        no_attachment_class = normalize_bool(row.get("是否无附件类", False))

        if not provided:
            state = "未提供凭证"
        else:
            if not need_att:
                state = "无需补要"
            else:
                if pd.notna(attachment_count) and float(attachment_count) == 0:
                    if no_attachment_class:
                        state = "已剔除（无附件类）"
                    else:
                        state = "材料缺失"
                else:
                    if pd.isna(a_amount):
                        state = "材料缺失"
                    else:
                        ok = judge_amount(
                            v_amount,
                            a_amount,
                            tolerance_ratio=tolerance_ratio,
                            abs_tolerance=abs_tolerance,
                        )
                        if ok is True:
                            state = "已到位"
                        elif ok is False:
                            state = "金额覆盖疑似不足"
                        else:
                            state = "材料缺失"

        module1_review_flag = normalize_bool(row.get("模块1是否人工复核", False))
        if module1_review_flag:
            state = "需人工复核"

        action = suggest_action(state, expense_type)

        results.append(
            {
                "凭证号": voucher,
                "费用类型": expense_type,
                "凭证金额": v_amount,
                "附件/估计金额": a_amount,
                "判断方式": method,
                "是否需要附件": need_att,
                "判断来源": source,
                "附件需求AI置信度": ai_conf,
                "附件需求AI理由": ai_reason,
                "模块1是否人工复核": module1_review_flag,
                "是否无附件类": no_attachment_class,
                "核查状态": state,
                "处理状态": proc_status,
                "建议动作": action,
            }
        )

    result_df = pd.DataFrame(results)

    summary = (
        result_df.groupby("核查状态")
        .agg(
            数量=("凭证号", "count"),
            涉及凭证号=("凭证号", lambda x: ", ".join(x.astype(str))),
        )
        .reset_index()
        .sort_values(by="数量", ascending=False)
    )

    flag_abn = result_df["核查状态"].isin(
        ["未提供凭证", "金额覆盖疑似不足", "材料缺失", "需人工复核"]
    )
    risk = (
        result_df.assign(是否异常=flag_abn)
        .groupby("费用类型")
        .agg(
            异常数=("是否异常", "sum"),
            总数=("凭证号", "count"),
        )
        .reset_index()
    )
    risk["异常率"] = (risk["异常数"] / risk["总数"]).round(3)

    return result_df, summary, risk
