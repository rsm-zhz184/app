import streamlit as st
import pandas as pd
from pathlib import Path

st.set_page_config(page_title="Building Detail", layout="centered")
st.title("🏢 Building Detail")

# 新 API：st.query_params
params  = st.query_params
name    = params.get("building", [""])[0]
utility = params.get("utility", ["Electrical"])[0]

if not name:
    st.info("➡️ Please click a building on the main heatmap first.")
    st.stop()

# 重新加载数据
base = Path("data")
usage    = pd.read_excel(base/"Capstone 2025 Project- Utility Data copy.xlsx")
usage.columns = usage.columns.str.replace("\n","",regex=True)
usage["EndDate"] = pd.to_datetime(usage["EndDate"])
building = pd.read_excel(base/"UCSD Building CAAN Info.xlsx")

# 顶部信息
st.header(name)
cls = building.loc[building["Building"]==name, "Building Classification"].iloc[0]
st.markdown(f"**Classification:** _{cls}_")

# 过滤并画图
commodity_map = {
    "Electrical":"ELECTRIC","Gas":"NATURALGAS","Hot Water":"HOTWATER",
    "Solar PV":"SOLARPV","ReClaimed Water":"RECLAIMEDWATER","Chilled Water":"CHILLEDWATER"
}

df = usage[
    (usage["Building"]==name)&
    (usage["CommodityCode"]==commodity_map[utility])
]
if df.empty:
    st.warning("No data for this building & utility.")
    st.stop()

df["Month"] = df["EndDate"].dt.to_period("M").dt.to_timestamp()
monthly = df.groupby("Month")["Use"].sum().reset_index()

st.subheader("📈 Monthly Usage Trend")
st.line_chart(monthly.set_index("Month")["Use"], use_container_width=True)

st.subheader("📊 Yearly Usage Totals")
df["Year"] = df["EndDate"].dt.year
yearly = df.groupby("Year")["Use"].sum().reset_index()
st.bar_chart(yearly.set_index("Year")["Use"], use_container_width=True)
