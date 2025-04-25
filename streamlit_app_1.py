# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium
from pathlib import Path

# ─── 1. 载入并缓存数据 ────────────────────────────────
@st.cache_data
def load_data():
    base = Path("data")
    # 1.1 读用量表
    usage = pd.read_excel(base / "Capstone 2025 Project- Utility Data copy.xlsx")
    # 删列名里多余的换行
    usage.columns = usage.columns.str.replace("\n", "", regex=True)
    # **关键**：把 usage 里的 “Building Name” 改成 “Building”
    if "Building Name" in usage.columns:
        usage = usage.rename(columns={"Building Name": "Building"})
    # 转成日期
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])

    # 1.2 读 building info
    building = pd.read_excel(base / "UCSD Building CAAN Info.xlsx")

    # 1.3 读坐标
    coords = pd.read_csv(base / "ucsd_building_coordinates.csv")

    # 1.4 预算每栋楼的月度用量表，后面直接用
    mon = (
        usage
        .assign(Month=usage["EndDate"].dt.to_period("M"))
        .groupby(["Building", "CommodityCode", "Month"])["Use"]
        .sum()
        .reset_index(name="Monthly_Total")
    )

    return usage, building, coords, mon

usage_data, building_info, coordinates, mon = load_data()


# ─── 2. Utility ↔ CommodityCode 映射 ────────────────────
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER"
}


# ─── 3. 预计算每栋楼的 CV & Z-score ─────────────────────
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"] == code].copy()
        # 合并 building_info 拿分类
        df = df.merge(
            building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
            left_on="CAAN", right_on="Building Capital Asset Account Number",
            how="left"
        )
        # 按年汇总
        df["Year"] = df["EndDate"].dt.year
        annual = df.groupby(["Building","Year"])["Use"].sum().reset_index()

        # 计算 CV
        cv_df = (
            annual
            .groupby("Building")["Use"]
            .agg(["mean","std"])
            .rename(columns={"mean":"Mean","std":"Std"})
            .reset_index()
        )
        cv_df["Use_CV"] = cv_df["Std"] / cv_df["Mean"]

        # 回填 classification & 坐标
        cv_df = (
            cv_df
            .merge(building_info[["Building","Building Classification"]],
                   on="Building", how="left")
            .merge(coordinates[["Building Name","Latitude","Longitude"]],
                   left_on="Building", right_on="Building Name", how="left")
        )

        # 同分类内部 Z-score
        cv_df["Z_score"] = (
            cv_df
            .groupby("Building Classification")["Use_CV"]
            .transform(lambda x:(x-x.mean())/x.std())
        )

        cv_maps[util_name] = cv_df

    return cv_maps

cv_maps = compute_cv_maps()
all_classes = sorted(building_info["Building Classification"].dropna().unique())


# ─── 4. Streamlit 布局 ─────────────────────────────────
st.set_page_config(page_title="Campus Heatmap", layout="wide")
st.title("📍 Campus Heatmap")

st.sidebar.header("🔧 Settings")
utility       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + all_classes)
compare_mode  = st.sidebar.selectbox("Compare to", ["Self", "Same classification"])


# ─── 5. 筛选 & 合并月均 ────────────────────────────────
df = cv_maps[utility].copy()
if classification != "All":
    df = df[df["Building Classification"] == classification]

monthly_mean = (
    mon
    .query("CommodityCode == @commodity_map[utility]")
    .merge(building_info[["Building","Building Classification"]],
           on="Building", how="left")
)
if classification != "All":
    monthly_mean = monthly_mean[monthly_mean["Building Classification"] == classification]

monthly_mean = (
    monthly_mean
    .groupby("Building")["Monthly_Total"]
    .mean()
    .reset_index(name="Monthly_Mean")
)
df = df.merge(monthly_mean, on="Building", how="left")


# ─── 6. 选指标 & 阈值 ─────────────────────────────────
if compare_mode == "Self":
    col, low, high, label = "Use_CV", 0.3, 0.5, "CV"
else:
    col, low, high, label = "Z_score", -1, 1, "Z-score"


# ─── 7. 渲染地图 & 捕获点击 ───────────────────────────
dfv = df.dropna(subset=["Latitude","Longitude"])
if dfv.empty:
    st.warning("✅ 这个分类下没有任何带坐标的建筑，无法显示热力图。")
    st.stop()

center = [dfv["Latitude"].mean(), dfv["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)

for _, r in dfv.iterrows():
    v = r[col]
    color = "red" if v>high else "orange" if v>low else "green"
    mon_str = f"{r['Monthly_Mean']:.2f}" if pd.notna(r["Monthly_Mean"]) else "N/A"

    popup_html = f"""
      <div style='font-size:14px; text-align:center;'>
        <b>{r['Building']}</b><br>
        🏷️ <i>{r['Building Classification']}</i><br><br>
        📊 {label}: <span style='color:{color}; font-weight:bold;'>{v:.2f}</span><br>
        📈 Avg Monthly: <b>{mon_str}</b>
      </div>
    """
    marker = folium.CircleMarker(
        location=[r["Latitude"],r["Longitude"]],
        radius=6, color="black",
        fill=True, fill_color=color,
        fill_opacity=0.8
    ).add_to(m)
    Popup(popup_html, max_width=280).add_to(marker)

map_data = st_folium(m, width=900, height=500, returned_objects=["last_clicked"])


# ─── 8. 底部表格 ───────────────────────────────────────
st.header("🏷️ Monthly Mean Usage per Building")
st.dataframe(
    monthly_mean
    .rename(columns={"Monthly_Mean": "Avg Monthly Use"})
    .sort_values("Avg Monthly Use", ascending=False)
    .reset_index(drop=True),
    use_container_width=True
)


# ─── 9. 点击联动详情 ─────────────────────────────────
click = map_data.get("last_clicked") if map_data else None
if click:
    lat, lng = click["lat"], click["lng"]
    dfv["dist2"] = (dfv["Latitude"]-lat)**2 + (dfv["Longitude"]-lng)**2
    idx   = dfv["dist2"].idxmin()
    bld   = dfv.loc[idx, "Building"]
    cls   = dfv.loc[idx, "Building Classification"]

    st.markdown("---")
    st.markdown(f"## 🏢 Detail: {bld}")
    st.markdown(f"**Classification:** _{cls}_")

    # 月度 & 年度趋势
    sel = mon.query("CommodityCode==@commodity_map[utility]").query("Building==@bld")
    sel = sel.set_index("Month")["Monthly_Total"]
    yearly = sel.groupby(sel.index.year).sum()

    st.subheader("Monthly Usage Trend")
    st.line_chart(sel, use_container_width=True)
    st.subheader("Yearly Usage Totals")
    st.bar_chart(yearly, use_container_width=True)
