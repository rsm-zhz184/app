# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium
from pathlib import Path

st.set_page_config(page_title="UCSD Utility Heatmap", layout="wide")

# ─────────────────────────────────────────────────────────────────────────────
# 1. 加载并缓存数据
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def load_data():
    base = Path("data")
    # 用你本地或部署环境中的相对路径
    usage   = pd.read_excel(base/"Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n","",regex=True)
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])
    building= pd.read_excel(base/"UCSD Building CAAN Info.xlsx")
    coords  = pd.read_csv(base/"ucsd_building_coordinates.csv")
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

# ─────────────────────────────────────────────────────────────────────────────
# 2. Utility ↔ CommodityCode 映射
# ─────────────────────────────────────────────────────────────────────────────
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER",
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. 预计算 CV & Z-score 并缓存
# ─────────────────────────────────────────────────────────────────────────────
@st.cache_data
def compute_stats():
    stats = {}
    for util, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"]==code].copy()
        df = df.merge(
            building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
            left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
        )
        df["Year"] = df["EndDate"].dt.year
        ann = df.groupby(["Building","Year"])["Use"].sum().reset_index()
        cv  = ann.groupby("Building")["Use"]\
                 .agg(["mean","std"]).reset_index()\
                 .rename(columns={"mean":"Mean","std":"Std"})
        cv["Use_CV"] = cv["Std"]/cv["Mean"]
        cv = cv.merge(
            building_info[["Building","Building Classification"]],
            on="Building", how="left"
        ).merge(
            coordinates[["Building Name","Latitude","Longitude"]],
            left_on="Building", right_on="Building Name", how="left"
        )
        cv["Z_score"] = cv.groupby("Building Classification")["Use_CV"]\
                          .transform(lambda x:(x-x.mean())/x.std())
        stats[util] = cv
    return stats

cv_maps = compute_stats()
all_classes = sorted(building_info["Building Classification"].dropna())

# ─────────────────────────────────────────────────────────────────────────────
# 4. 侧栏交互控件
# ─────────────────────────────────────────────────────────────────────────────
st.sidebar.header("Heatmap Filters")
util       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
cls_filter = st.sidebar.selectbox("Classification", ["All"]+all_classes)
cmp_mode   = st.sidebar.selectbox("Compare to", ["Self (CV)","Same class (Z-score)"])

# ─────────────────────────────────────────────────────────────────────────────
# 5. 根据筛选条件准备数据
# ─────────────────────────────────────────────────────────────────────────────
df = cv_maps[util].copy()
if cls_filter!="All":
    df = df[df["Building Classification"]==cls_filter]

# 5.1 计算月均并加入 df
u = usage_data[usage_data["CommodityCode"]==commodity_map[util]].copy()
u = u.merge(
    building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
    left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
)
if cls_filter!="All":
    u = u[u["Building Classification"]==cls_filter]
u["Month"] = u["EndDate"].dt.to_period("M")
mon = u.groupby(["Building","Month"])["Use"].sum().reset_index(name="Monthly_Total")
mon_mean = mon.groupby("Building")["Monthly_Total"].mean().reset_index(name="Monthly_Mean")
df = df.merge(mon_mean, on="Building", how="left")

# ─────────────────────────────────────────────────────────────────────────────
# 6. 配置色标阈值
# ─────────────────────────────────────────────────────────────────────────────
if cmp_mode.startswith("Self"):
    col, low, high = "Use_CV", 0.3, 0.5
else:
    col, low, high = "Z_score", -1, 1

# ─────────────────────────────────────────────────────────────────────────────
# 7. 渲染 Folium 地图
# ─────────────────────────────────────────────────────────────────────────────
st.markdown("## 📍 Campus Heatmap")
center = [df["Latitude"].mean(), df["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)
for _, r in df.dropna(subset=["Latitude","Longitude",col]).iterrows():
    v = r[col]
    color = "red"    if v>high else \
            "orange" if v>low  else \
            "green"
    txt = f"{v:.2f}"
    mon_str = f"{r['Monthly_Mean']:.0f}" if pd.notna(r["Monthly_Mean"]) else "N/A"
    popup = Popup(f"""
        <b>{r['Building']}</b><br>
        <i>{r['Building Classification']}</i><br>
        {cmp_mode}: <b style='color:{color}'>{txt}</b><br>
        Avg monthly: <b>{mon_str}</b>
        """, max_width=250)
    folium.CircleMarker(
        location=[r["Latitude"],r["Longitude"]],
        radius=6, color="black",
        fill=True, fill_color=color,
        fill_opacity=0.8, popup=popup
    ).add_to(m)

map_data = st_folium(m, width=800, height=450)

# ─────────────────────────────────────────────────────────────────────────────
# 8. 点击联动：展示详细趋势图
# ─────────────────────────────────────────────────────────────────────────────
click = map_data.get("last_clicked")
if click:
    lat, lng = click["lat"], click["lng"]
    dist2    = (df["Latitude"]-lat)**2 + (df["Longitude"]-lng)**2
    idx      = dist2.idxmin()
    br       = df.loc[idx]
    bname    = br["Building"]

    st.markdown("---")
    st.markdown(f"## 🏢 Detail: {bname}")
    st.markdown(f"**Classification:** _{br['Building Classification']}_")

    sel = mon[mon["Building"]==bname].copy()
    sel["Month_ts"] = sel["Month"].dt.to_timestamp()

    st.subheader("Monthly Usage Trend")
    st.line_chart(sel.set_index("Month_ts")["Monthly_Total"], use_container_width=True)

    st.subheader("Yearly Usage Totals")
    sel["Year"] = sel["Month_ts"].dt.year
    yr = sel.groupby("Year")["Monthly_Total"].sum().reset_index()
    st.bar_chart(yr.set_index("Year")["Monthly_Total"], use_container_width=True)
