# streamlit_app——newest.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium

# 1) 载入并缓存数据
@st.cache_data
def load_data():
    usage = pd.read_excel("data/Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n", "", regex=True)
    building = pd.read_excel("data/UCSD Building CAAN Info.xlsx")
    coords   = pd.read_csv("data/ucsd_building_coordinates.csv")
    # 预计算 monthly 全表，后面响应点击直接用
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])
    mon = (
        usage
        .assign(Month=usage["EndDate"].dt.to_period("M"))
        .groupby(["Building","CommodityCode","Month"])["Use"]
        .sum()
        .reset_index(name="Monthly_Total")
    )
    return usage, building, coords, mon

usage_data, building_info, coordinates, mon = load_data()

# 2) Utility ↔ CommodityCode 映射
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER"
}

# 3) 预计算每栋楼的 CV 和 Z_score
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"]==code].copy()
        df = df.merge(
            building_info[[
                "Building Capital Asset Account Number",
                "Building","Building Classification"
            ]],
            left_on="CAAN", right_on="Building Capital Asset Account Number",
            how="left"
        )
        df["Year"] = df["EndDate"].dt.year
        annual = df.groupby(["Building","Year"])["Use"].sum().reset_index()
        cv_df = (
            annual.groupby("Building")["Use"]
                  .agg(["mean","std"])
                  .rename(columns={"mean":"Mean","std":"Std"})
                  .reset_index()
        )
        cv_df["Use_CV"] = cv_df["Std"] / cv_df["Mean"]
        cv_df = (
            cv_df
            .merge(building_info[["Building","Building Classification"]], on="Building", how="left")
            .merge(coordinates[["Building Name","Latitude","Longitude"]],
                   left_on="Building", right_on="Building Name", how="left")
        )
        cv_df["Z_score"] = (
            cv_df
            .groupby("Building Classification")["Use_CV"]
            .transform(lambda x: (x-x.mean())/x.std())
        )
        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
all_classes = sorted(building_info["Building Classification"].dropna().unique())

# 4) Streamlit 界面
st.set_page_config(page_title="Campus Heatmap", layout="wide")
st.title("📍 Campus Heatmap")
st.sidebar.header("🔧 Settings")
utility       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + all_classes)
compare_mode  = st.sidebar.selectbox("Compare to", ["Self", "Same classification"])

# 5) 筛数据 & 合并月均
df = cv_maps[utility].copy()
if classification != "All":
    df = df[df["Building Classification"] == classification]

monthly_mean = (
    mon
    .query("CommodityCode==@commodity_map[utility]")
    .merge(building_info[["Building","Building Classification"]], on="Building", how="left")
)
if classification != "All":
    monthly_mean = monthly_mean[monthly_mean["Building Classification"]==classification]

monthly_mean = (
    monthly_mean
    .groupby("Building")["Monthly_Total"]
    .mean()
    .reset_index(name="Monthly_Mean")
)
df = df.merge(monthly_mean, on="Building", how="left")

# 6) 指标与阈值
if compare_mode=="Self":
    col, low, high, label = "Use_CV", 0.3, 0.5, "CV"
else:
    col, low, high, label = "Z_score", -1, 1, "Z-score"

# 7) 绘 Folium 熱圖
df_valid = df.dropna(subset=["Latitude","Longitude"])
if df_valid.empty:
    st.warning("✅ 这个分类下没有任何带坐标的建筑，无法显示热力图。")
    st.stop()

center = [df_valid["Latitude"].mean(), df_valid["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)
for _, row in df_valid.iterrows():
    v = row[col]
    color = "red" if v>high else "orange" if v>low else "green"
    mon_str = f"{row['Monthly_Mean']:.2f}" if pd.notna(row["Monthly_Mean"]) else "N/A"

    html = f"""
      <div style='font-size:14px; text-align:center;'>
        <b>{row['Building']}</b><br>
        🏷️ <i>{row['Building Classification']}</i><br><br>
        📊 {label}: <span style='color:{color};font-weight:bold;'>{v:.2f}</span><br>
        📈 Avg Monthly: <b>{mon_str}</b>
      </div>"""
    marker = folium.CircleMarker(
        location=[row["Latitude"],row["Longitude"]],
        radius=6, color="black",
        fill=True, fill_color=color,
        fill_opacity=0.8
    ).add_to(m)
    Popup(html, max_width=280).add_to(marker)

# —— 只调用一次 st_folium，并获取点击 —— 
map_data = st_folium(m, width=900, height=500, returned_objects=["last_clicked"])

# 8) 底部月均表
st.header("🏷️ Monthly Mean Usage per Building")
st.dataframe(
    monthly_mean.rename(columns={"Monthly_Mean":"Avg Monthly Use"})
                 .sort_values("Avg Monthly Use", ascending=False)
                 .reset_index(drop=True),
    use_container_width=True
)

# 9) 响应点击：展示该楼的趋势图
click = map_data.get("last_clicked") if map_data else None
if click:
    lat, lng = click["lat"], click["lng"]
    df_valid["dist2"] = (df_valid["Latitude"]-lat)**2 + (df_valid["Longitude"]-lng)**2
    idx = df_valid["dist2"].idxmin()
    bld = df_valid.loc[idx, "Building"]

    st.markdown("---")
    st.markdown(f"## 🏢 Detail: {bld}")
    cls = df_valid.loc[idx, "Building Classification"]
    st.markdown(f"**Classification:** _{cls}_")

    # 取出 mon 中该楼当前 utility 的月度分布
    df_month = (
      mon.query("CommodityCode==@commodity_map[utility]")
         .query("Building==@bld")
         .set_index("Month")["Monthly_Total"]
    )
    df_year = df_month.groupby(df_month.index.year).sum()

    st.subheader("Monthly Usage Trend")
    st.line_chart(df_month, use_container_width=True)

    st.subheader("Yearly Usage Totals")
    st.bar_chart(df_year, use_container_width=True)
