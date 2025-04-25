# streamlit_app.py
import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium
from pathlib import Path

st.set_page_config(layout="wide", page_title="UCSD Utility Usage")

@st.cache_data
def load_data():
    base = Path("data")
    usage = pd.read_excel(base/"Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n","",regex=True)
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])
    building = pd.read_excel(base/"UCSD Building CAAN Info.xlsx")
    coords   = pd.read_csv(base/"ucsd_building_coordinates.csv")
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

commodity_map = {
    "Electrical":"ELECTRIC",
    "Gas":"NATURALGAS",
    "Hot Water":"HOTWATER",
    "Solar PV":"SOLARPV",
    "ReClaimed Water":"RECLAIMEDWATER",
    "Chilled Water":"CHILLEDWATER"
}

@st.cache_data
def compute_cv():
    out = {}
    for util, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"]==code].copy()
        df = df.merge(
            building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
            left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
        )
        df["Year"] = df["EndDate"].dt.year
        ann = df.groupby(["Building","Year"])["Use"].sum().reset_index()
        cv = ann.groupby("Building")["Use"].agg(["mean","std"]).reset_index()
        cv["Use_CV"] = cv["std"]/cv["mean"]
        cv = cv.merge(
            building_info[["Building","Building Classification"]],
            on="Building", how="left"
        ).merge(
            coordinates[["Building Name","Latitude","Longitude"]],
            left_on="Building", right_on="Building Name", how="left"
        )
        cv["Z_score"] = cv.groupby("Building Classification")["Use_CV"] \
                         .transform(lambda x:(x-x.mean())/x.std())
        out[util] = cv
    return out

cv_maps = compute_cv()
all_classes = sorted(building_info["Building Classification"].dropna())

### --- Sidebar 选项 ---
st.sidebar.header("Filter")
util      = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
cls       = st.sidebar.selectbox("Classification", ["All"]+all_classes)
cmp_mode  = st.sidebar.selectbox("Compare to", ["Self (CV)","Same class (Z-score)"])

df = cv_maps[util].copy()
if cls!="All":
    df = df[df["Building Classification"]==cls]

if df.empty:
    st.sidebar.error("No buildings match this filter")
    st.stop()

# 叠加月平均
u = usage_data[usage_data["CommodityCode"]==commodity_map[util]].copy()
u = u.merge(
    building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
    left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
)
if cls!="All":
    u = u[u["Building Classification"]==cls]
u["Month"] = u["EndDate"].dt.to_period("M")
mon = u.groupby(["Building","Month"])["Use"].sum().reset_index(name="Monthly_Total")
mon_mean = mon.groupby("Building")["Monthly_Total"].mean().reset_index(name="Monthly_Mean")
df = df.merge(mon_mean, on="Building", how="left")

# 画地图
col, low, high = ("Use_CV",0.3,0.5) if cmp_mode.startswith("Self") else ("Z_score",-1,1)
st.header("📍 Heatmap")
center = [df["Latitude"].mean(), df["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)
for _, r in df.dropna(subset=["Latitude","Longitude",col]).iterrows():
    v = r[col]
    if   v>high: color="red"
    elif v>low:  color="orange"
    else:        color="green"
    mon_str = f"{r['Monthly_Mean']:.1f}" if pd.notna(r['Monthly_Mean']) else "N/A"
    txt = f"{v:.2f}"
    popup = Popup(f"""
        <b>{r['Building']}</b><br>
        <i>{r['Building Classification']}</i><br>
        {cmp_mode}: <b style='color:{color}'>{txt}</b><br>
        Avg Month: <b>{mon_str}</b>
    """, max_width=250)
    folium.CircleMarker(
        location=[r["Latitude"],r["Longitude"]],
        radius=6, color="black",
        fill=True, fill_color=color, fill_opacity=0.8,
        popup=popup
    ).add_to(m)

map_data = st_folium(m, width=800, height=500)

# 捕获用户点击事件
sel = map_data.get("last_clicked")
if sel:
    lat, lon = sel["lat"], sel["lng"]
    # 精确匹配这两个坐标
    hit = df[
        (df["Latitude"]==lat)&(df["Longitude"]==lon)
    ]
    if not hit.empty:
        bld = hit.iloc[0]["Building"]
        st.subheader(f"🏢 Detail: {bld}")
        # 取出原 usage，画图
        sub = u[u["Building"]==bld].copy()
        sub["Month_ts"] = sub["Month"].dt.to_timestamp()
        trend = sub.groupby("Month_ts")["Use"].sum().reset_index()
        st.line_chart(trend.set_index("Month_ts")["Use"], use_container_width=True)
        yearly = sub.copy()
        yearly["Year"] = yearly["Month_ts"].dt.year
        year_tot = yearly.groupby("Year")["Use"].sum().reset_index()
        st.bar_chart(year_tot.set_index("Year")["Use"], use_container_width=True)
