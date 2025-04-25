# pages/building_detail.py

import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="Building Detail", page_icon="🏢")

# 1. 从 URL 参数里拿 building name
params = st.experimental_get_query_params()
bld = params.get("name", [""])[0]

st.title(f"🏢 {bld} Utility Distribution")

# 2. 读入原始 utility 用量数据
@st.cache_data
def load_usage():
    df = pd.read_excel("data/Capstone 2025 Project- Utility Data copy.xlsx")
    df.columns = df.columns.str.replace('\n', '', regex=True)
    df["EndDate"] = pd.to_datetime(df["EndDate"])
    return df

usage = load_usage()

# 3. 给用户选一个 CommodityCode（可选：Electrical/Gas/…）
comm_map = {
    "Electrical": "ELECTRIC",
    "Gas":        "NATURALGAS",
    "Hot Water":  "HOTWATER",
    "Solar PV":   "SOLARPV",
    "ReClaimed Water": "RECLAIMEDWATER",
    "Chilled Water":   "CHILLEDWATER"
}
choice = st.selectbox("Utility Type", list(comm_map.keys()))
code = comm_map[choice]

# 4. 过滤数据
df = usage[
    (usage["Building"] == bld) &
    (usage["CommodityCode"] == code)
].copy()

if df.empty:
    st.warning("No records for this building + utility.")
    st.stop()

# 5. 聚合成月度或年度
gran = st.radio("Time granularity", ["Month","Year"])
if gran == "Month":
    df["Period"] = df["EndDate"].dt.to_period("M").dt.to_timestamp()
else:
    df["Period"] = df["EndDate"].dt.year

agg = df.groupby("Period")["Use"].sum().reset_index(name="Total Use")

# 6. 绘图
chart = alt.Chart(agg).mark_bar().encode(
    x=alt.X("Period:T" if gran=="Month" else "Period:O", title=gran),
    y=alt.Y("Total Use:Q", title="Total Use"),
    tooltip=["Period", "Total Use"]
).properties(width=700, height=400)

st.altair_chart(chart, use_container_width=True)

# 7. 返回主页
st.markdown("[← Back to Map](../streamlit_app)")
