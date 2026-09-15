import pandas as pd
import numpy as np

AMOUNT_TOLERANCE = 0.01

# 结果明细的固定列。空输入时也要按这个形状返回空表，
# 否则下游（页面渲染、分组汇总）会因为缺列而报 KeyError。
RESULT_COLUMNS = [
    "优先级",
    "样本序号",
    "凭证号",
    "科目/费用类型",
    "底稿金额",
    "凭证金额",
    "底稿日期",
    "凭证日期",
    "附件数量",
    "是否在抽凭清单中",
    "是否找到实际凭证",
    "金额是否一致",
    "日期是否一致",
    "一致性状态",
]

SUMMARY_COLUMNS = ["一致性状态", "数量", "涉及凭证号"]

STATUS_PRIORITY = {
    "凭证缺失": 1,
    "需人工复核": 2,
    "金额不一致": 3,
    "日期不一致": 4,
    "多余凭证": 5,
    "一致": 6,
}


def _normalize_voucher_no(x) -> str:
    if pd.isna(x):
        return ""
    return str(x).strip().upper()


def _normalize_date(x):
    if pd.isna(x) or x == "":
        return ""
    dt = pd.to_datetime(x, errors="coerce")
    if pd.notna(dt):
        return dt.strftime("%Y-%m-%d")
    return str(x).strip()


def _normalize_amount(x):
    if pd.isna(x) or x == "":
        return np.nan
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return np.nan


def _safe_eq_amount(a, b, tolerance=AMOUNT_TOLERANCE) -> bool:
    if pd.isna(a) or pd.isna(b):
        return False
    return abs(a - b) <= tolerance


def _safe_eq_text(a, b) -> bool:
    return str(a).strip() == str(b).strip()


def prepare_sampling_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "凭证号" not in out.columns:
        raise ValueError(
            "抽凭清单缺少必要字段：凭证号。抽凭清单至少需要「凭证号」列；"
            "金额列请命名为「底稿金额」，日期列请命名为「底稿日期」。"
            "若误用「凭证金额」「凭证日期」，匹配行会全部落入「需人工复核」。"
        )

    for col, default in {
        "样本序号": "",
        "底稿金额": np.nan,
        "底稿日期": "",
        "科目/费用类型": "",
    }.items():
        if col not in out.columns:
            out[col] = default

    out["凭证号"] = out["凭证号"].apply(_normalize_voucher_no)
    out["底稿金额"] = out["底稿金额"].apply(_normalize_amount)
    out["底稿日期"] = out["底稿日期"].apply(_normalize_date)
    return out


def prepare_voucher_df(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "凭证号" not in out.columns:
        raise ValueError(
            "实际凭证表缺少必要字段：凭证号。实际凭证表至少需要「凭证号」列；"
            "金额列请命名为「凭证金额」，日期列请命名为「凭证日期」，附件数列请命名为「附件数量」。"
        )

    for col, default in {
        "凭证金额": np.nan,
        "凭证日期": "",
        "附件数量": np.nan,
    }.items():
        if col not in out.columns:
            out[col] = default

    out["凭证号"] = out["凭证号"].apply(_normalize_voucher_no)
    out["凭证金额"] = out["凭证金额"].apply(_normalize_amount)
    out["凭证日期"] = out["凭证日期"].apply(_normalize_date)
    return out


def check_consistency(
    sampling_df: pd.DataFrame,
    voucher_df: pd.DataFrame,
    amount_tolerance: float = AMOUNT_TOLERANCE,
):
    s_df = prepare_sampling_df(sampling_df)
    v_df = prepare_voucher_df(voucher_df)

    results = []

    for _, s in s_df.iterrows():
        voucher_no = s["凭证号"]
        matched = v_df[v_df["凭证号"] == voucher_no]

        if matched.empty:
            status = "凭证缺失"
            results.append({
                "优先级": STATUS_PRIORITY[status],
                "样本序号": s.get("样本序号", ""),
                "凭证号": voucher_no,
                "科目/费用类型": s.get("科目/费用类型", ""),
                "底稿金额": s.get("底稿金额", np.nan),
                "凭证金额": np.nan,
                "底稿日期": s.get("底稿日期", ""),
                "凭证日期": "",
                "附件数量": np.nan,
                "是否在抽凭清单中": True,
                "是否找到实际凭证": False,
                "金额是否一致": False,
                "日期是否一致": False,
                "一致性状态": status,
            })
            continue

        if len(matched) > 1:
            v = matched.iloc[0]
            status = "需人工复核"
            results.append({
                "优先级": STATUS_PRIORITY[status],
                "样本序号": s.get("样本序号", ""),
                "凭证号": voucher_no,
                "科目/费用类型": s.get("科目/费用类型", ""),
                "底稿金额": s.get("底稿金额", np.nan),
                "凭证金额": v.get("凭证金额", np.nan),
                "底稿日期": s.get("底稿日期", ""),
                "凭证日期": v.get("凭证日期", ""),
                "附件数量": v.get("附件数量", np.nan),
                "是否在抽凭清单中": True,
                "是否找到实际凭证": True,
                "金额是否一致": _safe_eq_amount(s.get("底稿金额", np.nan), v.get("凭证金额", np.nan), amount_tolerance),
                "日期是否一致": _safe_eq_text(s.get("底稿日期", ""), v.get("凭证日期", "")),
                "一致性状态": status,
            })
            continue

        v = matched.iloc[0]
        amount_ok = _safe_eq_amount(s.get("底稿金额", np.nan), v.get("凭证金额", np.nan), amount_tolerance)
        date_ok = _safe_eq_text(s.get("底稿日期", ""), v.get("凭证日期", ""))

        if amount_ok and date_ok:
            status = "一致"
        elif (not amount_ok) and date_ok:
            status = "金额不一致"
        elif amount_ok and (not date_ok):
            status = "日期不一致"
        else:
            status = "需人工复核"

        results.append({
            "优先级": STATUS_PRIORITY[status],
            "样本序号": s.get("样本序号", ""),
            "凭证号": voucher_no,
            "科目/费用类型": s.get("科目/费用类型", ""),
            "底稿金额": s.get("底稿金额", np.nan),
            "凭证金额": v.get("凭证金额", np.nan),
            "底稿日期": s.get("底稿日期", ""),
            "凭证日期": v.get("凭证日期", ""),
            "附件数量": v.get("附件数量", np.nan),
            "是否在抽凭清单中": True,
            "是否找到实际凭证": True,
            "金额是否一致": amount_ok,
            "日期是否一致": date_ok,
            "一致性状态": status,
        })

    sampled_voucher_nos = set(s_df["凭证号"].tolist())
    for _, v in v_df.iterrows():
        voucher_no = v["凭证号"]
        if voucher_no not in sampled_voucher_nos:
            status = "多余凭证"
            results.append({
                "优先级": STATUS_PRIORITY[status],
                "样本序号": "",
                "凭证号": voucher_no,
                "科目/费用类型": "",
                "底稿金额": np.nan,
                "凭证金额": v.get("凭证金额", np.nan),
                "底稿日期": "",
                "凭证日期": v.get("凭证日期", ""),
                "附件数量": v.get("附件数量", np.nan),
                "是否在抽凭清单中": False,
                "是否找到实际凭证": True,
                "金额是否一致": False,
                "日期是否一致": False,
                "一致性状态": status,
            })

    # 两侧都为空时 results 会是空 list，此时 pd.DataFrame([]) 没有任何列，
    # 直接 sort_values 会抛 KeyError('优先级')。空输入是合法场景（用户传了空表），
    # 应该返回"形状正确但零行"的结果，由调用方决定怎么提示。
    if results:
        result_df = pd.DataFrame(results).sort_values(
            by=["优先级", "样本序号", "凭证号"], ascending=[True, True, True]
        ).reset_index(drop=True)
    else:
        result_df = pd.DataFrame(columns=RESULT_COLUMNS)

    if result_df.empty:
        summary_df = pd.DataFrame(columns=SUMMARY_COLUMNS)
    else:
        summary_df = (
            result_df.groupby("一致性状态")
            .agg(
                数量=("凭证号", "count"),
                涉及凭证号=("凭证号", lambda x: "，".join([str(i) for i in x if str(i).strip()])),
            )
            .reset_index()
        )
        summary_df["优先级"] = summary_df["一致性状态"].map(STATUS_PRIORITY)
        summary_df = summary_df.sort_values(by=["优先级", "数量"], ascending=[True, False]).drop(columns=["优先级"])

    return result_df, summary_df


def read_input_file(path: str) -> pd.DataFrame:
    path_lower = path.lower()
    if path_lower.endswith(".csv"):
        return pd.read_csv(path)
    if path_lower.endswith(".xlsx") or path_lower.endswith(".xls"):
        return pd.read_excel(path)
    raise ValueError("仅支持 csv / xlsx / xls 文件")


if __name__ == "__main__":
    print("这是 consistency_check_core.py。请在其他脚本中调用 check_consistency()。")
