
import streamlit as st
import pandas as pd
import os
import re
from openai import OpenAI

from bridge_service import build_check_log, run_module1_to_prefill
from module2_core import process

# ---------------------------
# DeepSeek Client
# ---------------------------
def get_client():
    api_key = os.getenv("DEEPSEEK_API_KEY")
    if not api_key:
        raise ValueError("未检测到 DEEPSEEK_API_KEY")
    return OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

# ---------------------------
# Masking (脱敏)
# ---------------------------
def mask_text(text):
    if not text:
        return text

    text = re.sub(r'API\d{8,}', 'API****', text)
    text = re.sub(r'\d{8,20}', lambda m: '*'*(len(m.group(0))-4)+m.group(0)[-4:], text)
    text = re.sub(r'[\w\.-]+@[\w\.-]+', '***@***', text)
    text = re.sub(r'某[\u4e00-\u9fa5A-Za-z0-9（）()]+公司', '某企业', text)
    return text

# ---------------------------
# Prompt
# ---------------------------
SYSTEM_PROMPT = """
你是审计底稿复核助手，服务对象为审计实习生和A1级别审计人员。

你的职责：
- 辅助其完成初步复核
- 提供结构化、克制、可执行的判断
- 不做最终审计结论

工作原则：
1. 严格基于提供的结构化信息进行判断
2. 不得编造数据、不得臆想不存在的业务或证据
3. 不调用外部知识，不联网，不补充背景信息
4. 不使用“舞弊”“虚假”“违规”等严重定性，除非有明确证据
5. 优先保持审慎，而非过度放大风险
"""

def build_prompt(result_row, log_row):
    return f"""
请基于以下结构化核查信息，输出审计复核意见。

【输入信息】
凭证号：{mask_text(str(result_row.get("凭证号","")))}
费用类型：{result_row.get("费用类型","")}
凭证金额：{result_row.get("凭证金额","")}
附件金额：{result_row.get("附件/估计金额","")}
核查状态：{result_row.get("核查状态","")}
建议动作：{result_row.get("建议动作","")}

附件类型：{mask_text(str(log_row.get("附件类型","")))}
模块1复核原因：{log_row.get("模块1复核原因","")}
模块2核查状态：{log_row.get("模块2核查状态","")}

【判断边界】
1. 只能基于上述信息判断，不得补充不存在的事实、背景、业务流程或证据。
2. 如果信息完整且金额匹配、未触发人工复核，只能判断为“低风险”或“可继续流程”，不得上升为严重风险。
3. 如果信息不足，但没有明确异常证据，应判断为“信息不足”，不得直接推断为高风险。
4. 只有在存在明确异常信号时，才判断为“存在异常”。明确异常包括：
   - 金额覆盖不足
   - 材料缺失
   - 触发人工复核
   - 凭证与附件类型明显不匹配
   - 日期或关键信息明显冲突
5. 不得使用以下表述，除非输入信息明确支持：
   - 舞弊
   - 虚假
   - 违规
   - 不真实
   - 非法
6. 不得联网，不得引用常识外推，不得根据行业经验自行补事实。

【输出要求】
请严格按以下格式输出，不要增加其他内容：

【风险判断】
仅可填写以下三种之一：低风险 / 信息不足 / 存在异常

【原因】
用1-2句话说明判断依据，禁止空话，禁止夸大。

【建议】
给出1-2条可执行的后续动作，面向审计实习生或A1，要求直接、具体、能落地。
"""

def generate_ai_review(result_row, log_row):
    client = get_client()
    prompt = build_prompt(result_row, log_row)

    resp = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
    )
    return resp.choices[0].message.content.strip()

# ---------------------------
# Streamlit UI
# ---------------------------
st.set_page_config(page_title="Dirty Work Cleaner AI版", layout="wide")

st.title("Dirty Work Cleaner (AI增强版)")
st.caption("说明：AI仅基于脱敏后的结构化信息进行复核，不上传原始凭证文本")

voucher_file = st.file_uploader("上传凭证", type=["txt"])
attachment_files = st.file_uploader("上传附件", type=["txt"], accept_multiple_files=True)

if st.button("运行"):

    if not voucher_file or not attachment_files:
        st.warning("请上传凭证和附件")
        st.stop()

    voucher_text = voucher_file.getvalue().decode("utf-8", errors="ignore")
    attachment_data = [(f.name, f.getvalue().decode("utf-8", errors="ignore")) for f in attachment_files]

    summary_df, details_df, prefill_df = run_module1_to_prefill(voucher_text, attachment_data)
    result_df, summary2_df, risk_df = process(prefill_df)
    log_df = build_check_log(summary_df, details_df, prefill_df, result_df)

    st.success("运行完成")

    # AI review
    try:
        ai_text = generate_ai_review(result_df.iloc[0].to_dict(), log_df.iloc[0].to_dict())
        st.subheader("AI复核")
        st.write(ai_text)
    except Exception as e:
        st.error(f"AI调用失败：{e}")

    tab1, tab2, tab3, tab4, tab5 = st.tabs(
        ["模块1汇总","模块1明细","模块2预填","模块2结果","日志"]
    )

    with tab1:
        st.dataframe(summary_df)

    with tab2:
        st.dataframe(details_df)

    with tab3:
        st.dataframe(prefill_df)

    with tab4:
        st.dataframe(result_df)

    with tab5:
        st.dataframe(log_df)
