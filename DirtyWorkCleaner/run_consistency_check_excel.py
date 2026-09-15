import pandas as pd

from consistency_check_core import check_consistency, read_input_file
from consistency_ai_review import enrich_consistency_reviews

SAMPLING_FILE = "抽凭清单模拟.xlsx"
VOUCHER_FILE = "实际凭证模拟.xlsx"

DETAIL_OUTPUT = "一致性检查结果明细_AI版.xlsx"
SUMMARY_OUTPUT = "一致性检查结果汇总_AI版.xlsx"


def main():
    sampling_df = read_input_file(SAMPLING_FILE)
    voucher_df = read_input_file(VOUCHER_FILE)

    result_df, summary_df = check_consistency(sampling_df, voucher_df)
    result_df = enrich_consistency_reviews(result_df)

    result_df.to_excel(DETAIL_OUTPUT, index=False)
    summary_df.to_excel(SUMMARY_OUTPUT, index=False)

    print("=== 一致性检查明细（AI版） ===")
    print(result_df.to_string(index=False))

    print("\n=== 一致性检查汇总（AI版） ===")
    print(summary_df.to_string(index=False))

    print("\n已导出：")
    print(f"- {DETAIL_OUTPUT}")
    print(f"- {SUMMARY_OUTPUT}")


if __name__ == "__main__":
    main()
