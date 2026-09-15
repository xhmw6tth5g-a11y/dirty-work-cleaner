from bridge_service import build_check_log, run_module1_to_prefill
from module2_core import process


def read_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


print("开始测试主链路...")

voucher_text = read_text("voucher_02.txt")
attachment_files_data = [
    ("eticket_01.txt", read_text("eticket_01.txt")),
    ("paper_ticket_01.txt", read_text("paper_ticket_01.txt")),
]

summary_df, details_df, prefill_df = run_module1_to_prefill(
    voucher_text,
    attachment_files_data,
    is_no_attachment_case=False,
)

print("\n=== 模块1：凭证包汇总 ===")
print(summary_df.to_string(index=False))

print("\n=== 模块1：附件明细 ===")
if details_df.empty:
    print("(空)")
else:
    print(details_df.to_string(index=False))

print("\n=== 模块2预填表 ===")
print(prefill_df.to_string(index=False))

result_df, summary2_df, risk_df = process(prefill_df)

print("\n=== AI附件判断 ===")
ai_cols = ["凭证号", "费用类型", "是否需要附件", "判断来源", "附件需求AI置信度", "附件需求AI理由"]
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

log_df = build_check_log(summary_df, details_df, prefill_df, result_df)
print("\n=== 判断日志 ===")
print(log_df.to_string(index=False))

print("\n测试完成。")
