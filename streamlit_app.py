# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium

# 1. 加载并缓存数据
@st.cache_data
def load_data():
    # 数据路径均为相对路径，请确保 data/ 文件夹下存在这三个文件
    usage = pd.read_excel('data/Capstone 2025 Project- Utility Data copy.xlsx')
    # 去除列名中的换行
    usage.columns = usage.columns.str.replace('\n', '', regex=True)

    building = pd.read_excel('data/UCSD Building CAAN Info.xlsx')
    coords   = pd.read_csv('data/ucsd_building_coordinates.csv')
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

# 3. 计算每栋楼的 CV 和 Z_score
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data['CommodityCode'] == code].copy()
        # 合并建筑信息
        df = df.merge(
            building_info[['Building Capital Asset Account Number', 'Building', 'Building Classification']],
            left_on='CAAN', right_on='Building Capital Asset Account Number', how='left'
        )
        # 年度汇总
        df['Year'] = pd.to_datetime(df['EndDate']).dt.year
        annual = df.groupby(['Building','Year'])['Use'].sum().reset_index()
        # 计算 CV
        cv_df = annual.groupby('Building')['Use'].agg(['mean','std']).reset_index()
        cv_df.columns = ['Building','Mean','Std']
        cv_df['Use_CV'] = cv_df['Std'] / cv_df['Mean']
        # 回填分类和坐标
        cv_df = cv_df.merge(
            building_info[['Building','Building Classification']], on='Building', how='left'
        ).merge(
            coordinates[['Building Name','Latitude','Longitude']],
            left_on='Building', right_on='Building Name', how='left'
        )
        # 分类内部 Z-score
        cv_df['Z_score'] = cv_df.groupby('Building Classification')['Use_CV'] \
                             .transform(lambda x:(x - x.mean())/x.std())
        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
available_classes = sorted(building_info['Building Classification'].dropna().unique())

# 4. 侧边栏 UI
st.sidebar.header("Map Settings")
utility      = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + available_classes)
compare_mode  = st.sidebar.selectbox("Compare to", ["Self","Same classification"])

# 5. 筛选数据表
cv_df = cv_maps[utility].copy()
if classification != "All":
    cv_df = cv_df[cv_df['Building Classification'] == classification]

# 5.1 计算月均用量
u = usage_data[usage_data['CommodityCode'] == commodity_map[utility]].copy()
u = u.merge(
    building_info[['Building Capital Asset Account Number','Building','Building Classification']],
    left_on='CAAN', right_on='Building Capital Asset Account Number', how='left'
)
if classification != "All":
    u = u[u['Building Classification'] == classification]
u['Month'] = pd.to_datetime(u['EndDate']).dt.to_period('M')
monthly = u.groupby(['Building','Month'])['Use'].sum().reset_index(name='Monthly_Total')
monthly_mean = monthly.groupby('Building')['Monthly_Total'].mean().reset_index(name='Monthly_Mean')
# 合并
cv_df = cv_df.merge(monthly_mean, on='Building', how='left')

# 6. 配色逻辑
if compare_mode == "Self":
    col, low, high, label = 'Use_CV', 0.3, 0.6, 'CV'
else:
    col, low, high, label = 'Z_score', -0.5, 0.5, 'Z‑score'

# 7. 绘制 Folium 地图
if cv_df.empty:
    st.warning("No data for these settings.")
else:
    center = [cv_df['Latitude'].mean(), cv_df['Longitude'].mean()]
    m = folium.Map(location=center, zoom_start=15)
    for _, r in cv_df.dropna(subset=['Latitude','Longitude',col]).iterrows():
        v = r[col]
        if v > high:
            color, txt = 'red',    f"High ⚠️ ({label}={v:.2f})"
        elif v > low:
            color, txt = 'orange', f"Medium 🟠 ({label}={v:.2f})"
        else:
            color, txt = 'green',  f"Low ✅ ({label}={v:.2f})"
        monthly_str = f"{r['Monthly_Mean']:.2f}" if pd.notna(r['Monthly_Mean']) else 'N/A'
        building = r['Building']
        building_encoded = building.replace(' ','%20')
        html = f"""
        <div style='font-size:14px;text-align:center;padding:6px;'>
          <b>{building}</b><br>
          🏷️ <i>{r['Building Classification']}</i><br><br>
          📊 {txt}<br>
          📈 Avg Monthly: <b>{monthly_str}</b><br><br>
          <a href='building_detail?name={building_encoded}' target='_self'>View Detail →</a>
        </div>
        """
        folium.CircleMarker(
            location=[r['Latitude'],r['Longitude']], radius=6,
            color='black', fill=True, fill_color=color, fill_opacity=0.85,
            popup=Popup(html, max_width=300)
        ).add_to(m)
    st.header("Interactive Heatmap")
    st_folium(m, width=800, height=600)
    st.header("Monthly Mean Usage per Building")
    st.dataframe(monthly_mean)
