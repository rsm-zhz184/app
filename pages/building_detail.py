import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Building Detail", layout="centered")
st.title("🏢 Building Detail")

# 1. 读取URL参数
params  = st.query_params
name    = params.get("building", [""])[0]
utility = params.get("utility", ["Electrical"])[0]
classification = params.get("classification", ["All"])[0]
compare_mode   = params.get("compare", ["Self"])[0]

if not name:
    st.info("➡️ 请先在主页面点击一个建筑。")
    st.stop()

# 2. 加载数据
base = Path("data")
usage    = pd.read_excel(base / "Capstone 2025 Project- Utility Data copy.xlsx")
usage.columns = usage.columns.str.replace("\n","",regex=True).str.strip()
if "Building Name" in usage.columns:
    usage = usage.rename(columns={"Building Name":"Building"})
usage["EndDate"] = pd.to_datetime(usage["EndDate"])
building = pd.read_excel(base / "UCSD Building CAAN Info.xlsx")

# 3. 顶部信息
cls = building.loc[building["Building"] == name, "Building Classification"].iloc[0]
st.markdown(f"**Utility:** {utility}  |  **Classification filter:** {classification}  |  **Compare to:** {compare_mode}")
st.markdown(f"**Building Classification:** _{cls}_")
st.markdown("---")

# 4. 过滤 & 画图
commodity_map = {
    "Electrical":"ELECTRIC","Gas":"NATURALGAS","Hot Water":"HOTWATER",
    "Solar PV":"SOLARPV","ReClaimed Water":"RECLAIMEDWATER","Chilled Water":"CHILLEDWATER"
}
code = commodity_map[utility]
df = usage[(usage["Building"] == name) & (usage["CommodityCode"] == code)].copy()

if df.empty:
    st.warning("该建筑在此 Utility 下无数据。")
    st.stop()

# 按月累加
df["Month"] = df["EndDate"].dt.to_period("M").dt.to_timestamp()
monthly = df.groupby("Month")["Use"].sum().reset_index()

st.subheader("📈 Monthly Usage Trend")
st.line_chart(monthly.set_index("Month")["Use"], use_container_width=True)

# 按年累加
df["Year"] = df["EndDate"].dt.year
yearly = df.groupby("Year")["Use"].sum().reset_index()

st.subheader("📊 Yearly Usage Totals")
st.bar_chart(yearly.set_index("Year")["Use"], use_container_width=True)

# 5. 展示“分布”——所有月度值的直方图
st.subheader("📋 Monthly Usage Distribution")
hist = monthly["Use"]
st.bar_chart(
    hist.value_counts(bins=20).sort_index()
)

# 6. 返回主页面链接
st.markdown("---")
back_qp = urlencode({
    "utility": utility,
    "classification": classification,
    "compare": compare_mode
}, quote_via=quote)
st.markdown(f"[← Back to Heatmap](/{back_qp})")
