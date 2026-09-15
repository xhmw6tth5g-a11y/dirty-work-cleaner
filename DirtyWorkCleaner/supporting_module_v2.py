import os
import shutil
from pathlib import Path
from typing import List, Dict, Tuple, Optional

import pandas as pd


# =========================
# 可配置项
# =========================
COMPANIES = ["青岛", "北京", "上海", "深圳", "香港"]

BANK_ALIASES = {
    "招商": ["招商", "招行", "cmb"],
    "工行": ["工行", "工商", "icbc"],
    "建行": ["建行", "建设", "ccb"],
    "中行": ["中行", "中国银行", "boc"],
    "农行": ["农行", "农业", "abc"],
    "交行": ["交行", "交通", "bcm"],
    "HSBC": ["hsbc", "汇丰"],
}

TYPE_RULES = {
    "M1": {
        "type_name": "银行回单",
        "keywords": ["回单", "付款", "收款", "转账", "流水回单"],
        "folder_name": "M1_银行回单",
    },
    "M2": {
        "type_name": "银行对账单",
        "keywords": ["对账单", "对帐单", "账单", "statement", "bank statement"],
        "folder_name": "M2_银行对账单",
    },
    "M3": {
        "type_name": "开户证明",
        "keywords": ["开户证明", "开户信息", "开户资料", "开户许可证", "账户信息"],
        "folder_name": "M3_开户证明",
    },
}

UNCLASSIFIED_FOLDER = "UNCLASSIFIED"
OUTPUT_WORKPAPER = "货币supporting底稿.xlsx"

ENABLE_AI_ASSIST = False  # 默认关闭；你后面再接
AI_CONFIDENCE_THRESHOLD = 0.8


# =========================
# AI接口（占位）
# =========================
def ai_guess_file_type(file_name: str, extracted_text: str = "") -> Tuple[str, float]:
    """
    返回：(type_code, confidence)
    当前默认关闭，直接 unknown。
    后续你可以接 DeepSeek，只让它输出 M1/M2/M3/unknown。
    """
    return "unknown", 0.0


# =========================
# 基础识别函数
# =========================
def normalize_text(text: str) -> str:
    return str(text).strip().lower()


def detect_company(file_name: str) -> str:
    for company in COMPANIES:
        if company in file_name:
            return company
    return ""


def detect_bank(file_name: str) -> str:
    lower_name = normalize_text(file_name)
    for std_name, aliases in BANK_ALIASES.items():
        for alias in aliases:
            if alias in lower_name:
                return std_name
    return "未识别银行"


def detect_type_by_rule(file_name: str) -> Tuple[str, str, str]:
    lower_name = normalize_text(file_name)
    for code, rule in TYPE_RULES.items():
        for kw in rule["keywords"]:
            if kw.lower() in lower_name:
                return code, rule["type_name"], rule["folder_name"]
    return "", "", ""


def build_new_stem(type_code: str, company: str, bank_name: str, original_path: Path) -> str:
    suffixless = original_path.stem
    if company and bank_name != "未识别银行":
        return f"{type_code}-{company}-{bank_name}"
    if company:
        return f"{type_code}-{company}"
    return f"{type_code}-{suffixless}"


# =========================
# Step1：分类 + 重命名 + 复制/移动
# =========================
def classify_and_rename_files(
    source_dir: str,
    output_dir: str,
    copy_instead_of_move: bool = True,
    enable_ai_assist: bool = ENABLE_AI_ASSIST,
) -> pd.DataFrame:
    source_path = Path(source_dir)
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    unclassified_path = output_path / UNCLASSIFIED_FOLDER
    unclassified_path.mkdir(parents=True, exist_ok=True)

    records: List[Dict] = []

    for file_path in source_path.iterdir():
        if not file_path.is_file():
            continue

        file_name = file_path.name
        company = detect_company(file_name)
        bank_name = detect_bank(file_name)
        type_code, type_name, folder_name = detect_type_by_rule(file_name)

        ai_type_code = ""
        ai_confidence = 0.0
        ai_used = False

        # 规则识别不到类型时，再考虑 AI
        if not type_code and enable_ai_assist:
            ai_type_code, ai_confidence = ai_guess_file_type(file_name=file_name, extracted_text="")
            if ai_type_code in TYPE_RULES and ai_confidence >= AI_CONFIDENCE_THRESHOLD:
                type_code = ai_type_code
                type_name = TYPE_RULES[type_code]["type_name"]
                folder_name = TYPE_RULES[type_code]["folder_name"]
                ai_used = True

        status = "成功"
        reason = ""

        if not type_code:
            status = "未分类"
            reason = "未识别文件类型"
        elif not company:
            status = "未分类"
            reason = "未识别公司"

        new_file_name = ""
        target_file_path = ""

        if status == "成功":
            target_folder = output_path / folder_name
            target_folder.mkdir(parents=True, exist_ok=True)

            new_stem = build_new_stem(type_code, company, bank_name, file_path)
            new_file_name = f"{new_stem}{file_path.suffix}"
            target = target_folder / new_file_name

            counter = 2
            while target.exists():
                new_file_name = f"{new_stem}_{counter}{file_path.suffix}"
                target = target_folder / new_file_name
                counter += 1

            if copy_instead_of_move:
                shutil.copy2(file_path, target)
            else:
                shutil.move(str(file_path), str(target))

            target_file_path = str(target)

        else:
            # 未识别文件统一复制/移动到 UNCLASSIFIED
            target = unclassified_path / file_name
            if copy_instead_of_move:
                shutil.copy2(file_path, target)
            else:
                shutil.move(str(file_path), str(target))
            target_file_path = str(target)

        records.append({
            "原文件名": file_name,
            "识别公司": company,
            "识别银行": bank_name,
            "文件类型编号": type_code,
            "文件类型": type_name,
            "AI是否参与": ai_used,
            "AI类型结果": ai_type_code,
            "AI置信度": ai_confidence,
            "处理状态": status,
            "备注": reason,
            "新文件名": new_file_name,
            "目标路径": target_file_path,
        })

    return pd.DataFrame(records)


# =========================
# Step2：生成底稿表
# =========================
def build_supporting_workpaper(classified_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "公司",
        "银行回单(M1)",
        "银行对账单(M2)",
        "开户证明(M3)",
    ]

    rows = []
    success_df = classified_df[classified_df["处理状态"] == "成功"].copy()

    for company in COMPANIES:
        row = {"公司": company}

        for code, rule in TYPE_RULES.items():
            type_name = rule["type_name"]
            col_name = f"{type_name}({code})"

            sub = success_df[
                (success_df["识别公司"] == company) &
                (success_df["文件类型编号"] == code)
            ]

            if sub.empty:
                row[col_name] = ""
            else:
                values = sub["新文件名"].astype(str).tolist()
                row[col_name] = "；".join(values)

        rows.append(row)

    return pd.DataFrame(rows, columns=columns)


def build_missing_list(workpaper_df: pd.DataFrame) -> pd.DataFrame:
    missing_rows = []
    type_columns = [
        "银行回单(M1)",
        "银行对账单(M2)",
        "开户证明(M3)",
    ]

    for _, row in workpaper_df.iterrows():
        company = row["公司"]
        missing_types = [col for col in type_columns if not str(row[col]).strip()]
        if missing_types:
            missing_rows.append({
                "公司": company,
                "缺失文件类型": "、".join(missing_types),
            })

    return pd.DataFrame(missing_rows)


def build_coverage(workpaper_df: pd.DataFrame) -> pd.DataFrame:
    rows = []
    type_columns = [
        "银行回单(M1)",
        "银行对账单(M2)",
        "开户证明(M3)",
    ]

    for _, row in workpaper_df.iterrows():
        company = row["公司"]
        total = len(type_columns)
        ok = sum(1 for col in type_columns if str(row[col]).strip())
        rows.append({
            "公司": company,
            "已覆盖数量": ok,
            "应覆盖数量": total,
            "覆盖率": f"{round(ok / total * 100)}%",
        })

    return pd.DataFrame(rows)


# =========================
# Step3：导出Excel（多sheet）
# =========================
def export_supporting_excel(
    workpaper_df: pd.DataFrame,
    missing_df: pd.DataFrame,
    coverage_df: pd.DataFrame,
    classified_df: pd.DataFrame,
    output_file: str,
):
    unclassified_df = classified_df[classified_df["处理状态"] != "成功"].copy()

    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        workpaper_df.to_excel(writer, sheet_name="supporting底稿", index=False)
        missing_df.to_excel(writer, sheet_name="缺失清单", index=False)
        coverage_df.to_excel(writer, sheet_name="覆盖率", index=False)
        classified_df.to_excel(writer, sheet_name="分类结果", index=False)
        unclassified_df.to_excel(writer, sheet_name="未识别文件", index=False)


# =========================
# 总流程
# =========================
def run_supporting_pipeline(
    source_dir: str,
    output_dir: str = "supporting_output",
    output_excel: str = OUTPUT_WORKPAPER,
    copy_instead_of_move: bool = True,
    enable_ai_assist: bool = ENABLE_AI_ASSIST,
):
    classified_df = classify_and_rename_files(
        source_dir=source_dir,
        output_dir=output_dir,
        copy_instead_of_move=copy_instead_of_move,
        enable_ai_assist=enable_ai_assist,
    )

    workpaper_df = build_supporting_workpaper(classified_df)
    missing_df = build_missing_list(workpaper_df)
    coverage_df = build_coverage(workpaper_df)

    export_supporting_excel(
        workpaper_df=workpaper_df,
        missing_df=missing_df,
        coverage_df=coverage_df,
        classified_df=classified_df,
        output_file=output_excel,
    )

    return classified_df, workpaper_df, missing_df, coverage_df


if __name__ == "__main__":
    # 把你的原始文件都放到这个目录
    SOURCE_DIR = "raw_supporting_files"

    classified_df, workpaper_df, missing_df, coverage_df = run_supporting_pipeline(
        source_dir=SOURCE_DIR,
        output_dir="supporting_output",
        output_excel="货币supporting底稿.xlsx",
        copy_instead_of_move=True,   # True=复制，False=移动
        enable_ai_assist=False,      # 先关，后续再接
    )

    print("=== 分类结果 ===")
    print(classified_df.to_string(index=False))

    print("\n=== supporting底稿 ===")
    print(workpaper_df.to_string(index=False))

    print("\n=== 缺失清单 ===")
    if missing_df.empty:
        print("无缺失")
    else:
        print(missing_df.to_string(index=False))

    print("\n=== 覆盖率 ===")
    print(coverage_df.to_string(index=False))

    print("\n已导出：货币supporting底稿.xlsx")
