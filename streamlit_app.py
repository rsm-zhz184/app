# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium

# 1. 加载并缓存数据
@st.cache_data
def load_data():
    # Excel 里可能有换行符，先统一去掉
    usage = pd.read_excel(
        'data/Capstone 2025 Project- Utility Data copy.xlsx'
    )
    usage.columns = usage.columns.str.replace('\n', '', regex=True)

    building = pd.read_excel(
        'data/UCSD Building CAAN Info.xlsx'
    )
    coords = pd.read_csv(
        'data/ucsd_building_coordinates.csv'
    )
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

# 2. Utility ↔ CommodityCode 映射
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER"
}

# 3. 计算每栋楼的 CV & Z_score（每种 Utility 一份表）
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data['CommodityCode'] == code].copy()
        df = df.merge(
            building_info[[
                'Building Capital Asset Account Number',
                'Building',
                'Building Classification'
            ]],
            left_on='CAAN',
            right_on='Building Capital Asset Account Number',
            how='left'
        )
        # 年度汇总
        df['Year'] = pd.to_datetime(df['EndDate']).dt.year
        annual = df.groupby(['Building','Year'])['Use'].sum().reset_index()
        # 计算平均 & 标准差 -> CV
        cv_df = annual.groupby('Building')['Use'] \
            .agg(['mean','std']).reset_index() \
            .rename(columns={'mean':'Mean','std':'Std'})
        cv_df['Use_CV'] = cv_df['Std'] / cv_df['Mean']
        # 回填分类和坐标
        cv_df = cv_df.merge(
            building_info[['Building','Building Classification']],
            on='Building', how='left'
        ).merge(
            coordinates[['Building Name','Latitude','Longitude']],
            left_on='Building', right_on='Building Name', how='left'
        )
        # 分类内部 Z-score
        cv_df['Z_score'] = cv_df.groupby('Building Classification')['Use_CV'] \
            .transform(lambda x:(x-x.mean())/x.std())

        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
available_classes = sorted(building_info['Building Classification'].dropna().unique())

# 4. Streamlit 布局：侧边栏选项
st.sidebar.header("Settings")
utility = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox(
    "Classification",
    ["All"] + available_classes
)
compare_mode = st.sidebar.selectbox(
    "Compare to",
    ["Self", "Same classification"]
)

# 5. 筛选 CV 表 + 计算月均用量
df = cv_maps[utility].copy()
if classification != "All":
    df = df[df['Building Classification'] == classification]

# 5.1 计算每栋楼当前选择条件下的月均用量
u = usage_data[usage_data['CommodityCode'] == commodity_map[utility]].copy()
u = u.merge(
    building_info[['Building Capital Asset Account Number',
                   'Building','Building Classification']],
    left_on='CAAN', right_on='Building Capital Asset Account Number',
    how='left'
)
if classification != "All":
    u = u[u['Building Classification'] == classification]
u['Month'] = pd.to_datetime(u['EndDate']).dt.to_period('M')
monthly = u.groupby(['Building','Month'])['Use'] \
           .sum().reset_index(name='Monthly_Total')
monthly_mean = monthly.groupby('Building')['Monthly_Total'] \
               .mean().reset_index(name='Monthly_Mean')

# 把月均合并到 df，用于 popup
df = df.merge(monthly_mean, on='Building', how='left')

# 6. Folium 地图配色参数
if compare_mode == "Self":
    col, low, high, label = 'Use_CV', 0.3, 0.6, 'CV'
else:
    col, low, high, label = 'Z_score', -0.5, 0.5, 'Z‑score'

# 7. 渲染地图
if df.empty:
    st.warning("No data available for this selection.")
else:
    center = [df['Latitude'].mean(), df['Longitude'].mean()]
    m = folium.Map(location=center, zoom_start=15)

    # 每栋楼一个 CircleMarker，popup 展示 CV/Z‑score 和月均
    for _, r in df.dropna(subset=['Latitude','Longitude',col]).iterrows():
        v = r[col]
        if v > high:
            color, txt = 'red',    f"High ⚠️ ({label}={v:.2f})"
        elif v > low:
            color, txt = 'orange', f"Medium 🟠 ({label}={v:.2f})"
        else:
            color, txt = 'green',  f"Low ✅ ({label}={v:.2f})"

        monthly_str = (
            f"{r['Monthly_Mean']:.2f}"
            if not pd.isna(r['Monthly_Mean'])
            else "N/A"
        )

        html = f"""
        <div style='font-size:14px; text-align:center; padding:6px;'>
          <b>{r['Building']}</b><br>
          🏷️ <i>{r['Building Classification']}</i><br><br>
          📊 {txt}<br>
          📈 Avg Monthly Use: <b>{monthly_str}</b>
        </div>
        """
        folium.CircleMarker(
            location=[r['Latitude'], r['Longitude']],
            radius=6,
            color='black',
            fill=True, fill_color=color,
            fill_opacity=0.85,
            popup=Popup(html, max_width=250)
        ).add_to(m)

    # 8. 页面输出
    st.header("Interactive Heatmap")
    st_folium(m, width=800, height=800)

    st.header("Monthly Mean Usage per Building")
    st.dataframe(monthly_mean)
