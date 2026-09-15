import pandas as pd

from consistency_check_core import check_consistency, read_input_file
from consistency_ai_review import enrich_consistency_reviews

SAMPLING_FILE = "抽凭清单模拟.xlsx"
VOUCHER_FILE = "实际凭证模拟.xlsx"

OUTPUT_FILE = "一致性检查结果_分Sheet_AI版.xlsx"

SHEET_ORDER = [
    "凭证缺失",
    "需人工复核",
    "金额不一致",
    "日期不一致",
    "多余凭证",
    "一致",
]


def export_multi_sheet_excel(result_df: pd.DataFrame, summary_df: pd.DataFrame, output_file: str):
    with pd.ExcelWriter(output_file, engine="openpyxl") as writer:
        summary_df.to_excel(writer, sheet_name="汇总", index=False)

        for status in SHEET_ORDER:
            sub_df = result_df[result_df["一致性状态"] == status]
            if not sub_df.empty:
                sheet_name = status[:31]
                sub_df.to_excel(writer, sheet_name=sheet_name, index=False)

        existing_statuses = set(SHEET_ORDER)
        other_statuses = [
            s for s in result_df["一致性状态"].dropna().unique().tolist()
            if s not in existing_statuses
        ]
        for status in other_statuses:
            sub_df = result_df[result_df["一致性状态"] == status]
            if not sub_df.empty:
                sheet_name = str(status)[:31]
                sub_df.to_excel(writer, sheet_name=sheet_name, index=False)

        result_df.to_excel(writer, sheet_name="全部明细", index=False)


def main():
    sampling_df = read_input_file(SAMPLING_FILE)
    voucher_df = read_input_file(VOUCHER_FILE)

    result_df, summary_df = check_consistency(sampling_df, voucher_df)
    result_df = enrich_consistency_reviews(result_df)

    export_multi_sheet_excel(result_df, summary_df, OUTPUT_FILE)

    print("=== 一致性检查汇总（AI版） ===")
    print(summary_df.to_string(index=False))

    print("\n=== 各状态样本数量 ===")
    for status in SHEET_ORDER:
        count = (result_df["一致性状态"] == status).sum()
        if count > 0:
            print(f"{status}: {count}")

    print(f"\n已导出：{OUTPUT_FILE}")


if __name__ == "__main__":
    main()
