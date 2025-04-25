# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from streamlit_folium import st_folium
from folium import GeoJson

st.set_page_config(page_title="UCSD Utility Usage Map", layout="wide")

# 1. 加载并缓存数据
@st.cache_data
def load_data():
    usage = pd.read_excel('data/Capstone 2025 Project- Utility Data copy.xlsx')
    usage.columns = usage.columns.str.replace('\n', '', regex=True)
    usage['EndDate'] = pd.to_datetime(usage['EndDate'])
    building = pd.read_excel('data/UCSD Building CAAN Info.xlsx')
    coords = pd.read_csv('data/ucsd_building_coordinates.csv')
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

# 2. 定义 Utility ↔ CommodityCode 映射
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER"
}

# 3. 计算每栋楼的 CV & Z_score
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data['CommodityCode'] == code].copy()
        df = df.merge(
            building_info[['Building Capital Asset Account Number','Building','Building Classification']],
            left_on='CAAN', right_on='Building Capital Asset Account Number', how='left'
        )
        df['Year'] = df['EndDate'].dt.year
        annual = df.groupby(['Building','Year'])['Use'].sum().reset_index()
        cv_df = annual.groupby('Building')['Use'].agg(['mean','std']).reset_index()
        cv_df.columns = ['Building','Mean','Std']
        cv_df['Use_CV'] = cv_df['Std'] / cv_df['Mean']
        cv_df = cv_df.merge(
            building_info[['Building','Building Classification']],
            on='Building', how='left'
        ).merge(
            coordinates[['Building Name','Latitude','Longitude']],
            left_on='Building', right_on='Building Name', how='left'
        )
        cv_df['Z_score'] = cv_df.groupby('Building Classification')['Use_CV'] \
                                 .transform(lambda x:(x - x.mean())/x.std())
        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
available_classes = sorted(building_info['Building Classification'].dropna().unique())

# 4. 侧边栏设置
st.sidebar.header("Settings")
utility       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + available_classes)
compare_mode   = st.sidebar.selectbox("Compare to", ["Self", "Same classification"])

# 5. 筛选 CV 表
df_cv = cv_maps[utility].copy()
if classification != "All":
    df_cv = df_cv[df_cv['Building Classification'] == classification]

# 6. 计算月均用量并合并
df_usage = usage_data[usage_data['CommodityCode'] == commodity_map[utility]].copy()
df_usage = df_usage.merge(
    building_info[['Building Capital Asset Account Number','Building','Building Classification']],
    left_on='CAAN', right_on='Building Capital Asset Account Number', how='left'
)
if classification != "All":
    df_usage = df_usage[df_usage['Building Classification'] == classification]
df_usage['Month'] = df_usage['EndDate'].dt.to_period('M')
monthly = df_usage.groupby(['Building','Month'])['Use'] \
                  .sum().reset_index(name='Monthly_Total')
monthly_mean = monthly.groupby('Building')['Monthly_Total'] \
                      .mean().reset_index(name='Monthly_Mean')
df_cv = df_cv.merge(monthly_mean, on='Building', how='left')

# 7. 配色阈值
if compare_mode == "Self":
    col, low, high, label = 'Use_CV', 0.3, 0.6, 'CV'
else:
    col, low, high, label = 'Z_score', -0.5, 0.5, 'Z-score'

# 8. 构建 Folium 地图
st.header("📍 UCSD Utility Usage Heatmap")
if df_cv.empty:
    st.warning("No data available for this combination.")
    st.stop()

center = [df_cv['Latitude'].mean(), df_cv['Longitude'].mean()]
m = folium.Map(location=center, zoom_start=15)

# 用 GeoJson 让点击事件携带 building 名称
features = []
for _, r in df_cv.dropna(subset=['Latitude','Longitude']).iterrows():
    v = r.get(col)
    if pd.isna(v):
        continue
    color = 'red' if v > high else 'orange' if v > low else 'green'
    feat = {
        "type": "Feature",
        "properties": {
            "building": r['Building'],
            "color": color,
            "cv": f"{label}={v:.2f}",
            "avg_month": f"{r['Monthly_Mean']:.2f}" if pd.notna(r['Monthly_Mean']) else "N/A"
        },
        "geometry": {
            "type": "Point",
            "coordinates": [r['Longitude'], r['Latitude']]
        }
    }
    features.append(feat)

GeoJson(
    {"type":"FeatureCollection", "features": features},
    name="buildings",
    popup=folium.GeoJsonPopup(fields=["building","cv","avg_month"],
                              aliases=["Building","Metric","Avg Monthly"]),
    style_function=lambda f: {"color": f["properties"]["color"],
                              "fillColor": f["properties"]["color"],
                              "radius": 6}
).add_to(m)

# 9. 渲染地图并获取点击返回值
resp = st_folium(m, width=800, height=600, returned_objects=["last_active_feature"])
feat = resp.get("last_active_feature")

# 10. 点击后在同页下方展示详情
if feat:
    bld = feat["properties"]["building"]
    st.subheader(f"🔍 Detail for {bld}")
    df_bld = df_usage[df_usage["Building"] == bld]
    if df_bld.empty:
        st.info("No usage records for this building.")
    else:
        gran = st.radio("Time granularity", ["Month","Year"], horizontal=True)
        if gran == "Month":
            df_bld["Period"] = df_bld["EndDate"].dt.to_period("M").dt.to_timestamp()
        else:
            df_bld["Period"] = df_bld["EndDate"].dt.year
        chart_data = df_bld.groupby("Period")["Use"].sum().reset_index()
        st.line_chart(chart_data.rename(columns={"Use":"Total Use"}).set_index("Period"), use_container_width=True)
