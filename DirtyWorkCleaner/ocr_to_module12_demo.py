from pathlib import Path

from bridge_service import build_check_log, run_module1_to_prefill
from module2_core import process
from ocr_bridge import clean_ocr_text, build_voucher_ready_text


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def main():
    # 1. 读取 OCR 输出
    ocr_path = "ocr_output.txt"
    if not Path(ocr_path).exists():
        raise FileNotFoundError("未找到 ocr_output.txt，请先运行 paddle_ocr_test.py")

    raw_text = read_text(ocr_path)
    clean_text = clean_ocr_text(raw_text)
    voucher_text = build_voucher_ready_text(clean_text)

    with open("voucher_ocr_ready.txt", "w", encoding="utf-8") as f:
        f.write(voucher_text)

    # 2. 当前演示：仅凭证进入模块1/2（附件可后续替换为真实 OCR 附件文本）
    attachment_files_data = []

    summary_df, details_df, prefill_df = run_module1_to_prefill(
        voucher_text,
        attachment_files_data,
        is_no_attachment_case=False,
    )

    # 3. 无附件时，不视为金额=0，而视为“材料未提供/待判断”
    prefill_df["附件金额合计"] = None
    prefill_df["附件总数量"] = 0
    prefill_df["是否使用抽样"] = False
    prefill_df["是否无附件类"] = False

    # 4. 跑模块2（这里会自动触发“AI先判断是否需要附件”）
    result_df, summary2_df, risk_df = process(prefill_df)
    log_df = build_check_log(summary_df, details_df, prefill_df, result_df)

    print("=== 标准化凭证文本 ===")
    print(voucher_text)

    print("\n=== 模块1：凭证包汇总 ===")
    print(summary_df.to_string(index=False))

    print("\n=== 模块1：附件明细 ===")
    if details_df.empty:
        print("(空)")
    else:
        print(details_df.to_string(index=False))

    print("\n=== 模块2预填表 ===")
    print(prefill_df.to_string(index=False))

    print("\n=== AI附件判断 ===")
    ai_cols = ["是否需要附件", "判断来源", "附件需求AI置信度", "附件需求AI理由"]
    existing_ai_cols = [c for c in ai_cols if c in result_df.columns]
    if existing_ai_cols:
        print(result_df[existing_ai_cols].to_string(index=False))
    else:
        print("当前结果中未找到 AI 附件判断字段。")

    print("\n=== 模块2：核查明细 ===")
    print(result_df.to_string(index=False))

    print("\n=== 模块2：汇总 ===")
    print(summary2_df.to_string(index=False))

    print("\n=== 模块2：异常率 ===")
    print(risk_df.to_string(index=False))

    print("\n=== 判断日志 ===")
    print(log_df.to_string(index=False))


if __name__ == "__main__":
    main()
