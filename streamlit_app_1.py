# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium

# — 1. 载入并缓存数据 —
@st.cache_data
def load_data():
    # 请把三个文件都放到项目根目录的 data/ 子文件夹
    usage = pd.read_excel("data/Capstone 2025 Project- Utility Data copy.xlsx")
    # 去掉列名中的换行符
    usage.columns = usage.columns.str.replace("\n", "", regex=True)

    building = pd.read_excel("data/UCSD Building CAAN Info.xlsx")
    coords   = pd.read_csv("data/ucsd_building_coordinates.csv")
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

# — 2. Utility ↔ CommodityCode 对照 —
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER"
}

# — 3. 预计算每栋楼的 CV 和 Z-score —
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"] == code].copy()
        # 合并 Building 分类
        df = df.merge(
            building_info[["Building Capital Asset Account Number",
                           "Building", "Building Classification"]],
            left_on="CAAN",
            right_on="Building Capital Asset Account Number",
            how="left"
        )
        # 按年汇总用量
        df["Year"] = pd.to_datetime(df["EndDate"]).dt.year
        annual = df.groupby(["Building", "Year"])["Use"].sum().reset_index()

        # 计算平均 & 标准差 → CV
        cv_df = annual.groupby("Building")["Use"] \
            .agg(["mean","std"]).reset_index() \
            .rename(columns={"mean":"Mean","std":"Std"})
        cv_df["Use_CV"] = cv_df["Std"] / cv_df["Mean"]

        # 回填分类 & 坐标
        cv_df = cv_df.merge(
            building_info[["Building","Building Classification"]],
            on="Building", how="left"
        ).merge(
            coordinates[["Building Name","Latitude","Longitude"]],
            left_on="Building", right_on="Building Name", how="left"
        )
        # 同分类内部 Z-score
        cv_df["Z_score"] = cv_df.groupby("Building Classification")["Use_CV"] \
                                 .transform(lambda x:(x-x.mean())/x.std())

        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()

# 所有可能的 Building Classification
all_classes = sorted(building_info["Building Classification"].dropna().unique())

# — 4. Streamlit UI 设置 —
st.set_page_config(page_title="Campus Heatmap", layout="wide")
st.sidebar.header("🔧 Settings")
utility       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + all_classes)
compare_mode  = st.sidebar.selectbox("Compare to", ["Self", "Same classification"])

# — 5. 筛选 & 计算月均用量 —
df = cv_maps[utility].copy()
if classification != "All":
    df = df[df["Building Classification"] == classification]

# 月度用量 & 月均
u = usage_data[usage_data["CommodityCode"] == commodity_map[utility]].copy()
u = u.merge(
    building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
    left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
)
if classification != "All":
    u = u[u["Building Classification"] == classification]
u["Month"] = pd.to_datetime(u["EndDate"]).dt.to_period("M")
monthly = u.groupby(["Building","Month"])["Use"].sum().reset_index(name="Monthly_Total")
monthly_mean = monthly.groupby("Building")["Monthly_Total"] \
                      .mean().reset_index(name="Monthly_Mean")

# 合并月均到 df
df = df.merge(monthly_mean, on="Building", how="left")

# 选择指标和阈值
if compare_mode == "Self":
    col, low, high, label = "Use_CV", 0.3, 0.5, "CV"
else:
    col, low, high, label = "Z_score", -1, 1, "Z-score"

# — 6. 渲染 Folium 地图 —
st.title("📍 Campus Heatmap")
df_valid = df.dropna(subset=["Latitude","Longitude"])
if df_valid.empty:
    st.warning("✅ 这个分类下没有任何带坐标的建筑，无法显示热力图。")
else:
    center = [df_valid["Latitude"].mean(), df_valid["Longitude"].mean()]
    m = folium.Map(location=center, zoom_start=15)

    for _, r in df_valid.iterrows():
        v = r[col]
        color = "red"    if v>high else \
                "orange" if v>low  else \
                "green"
        # 月均字符串
        mon_str = f"{r['Monthly_Mean']:.2f}" if pd.notna(r["Monthly_Mean"]) else "N/A"

        popup_html = f"""
        <div style='font-size:14px; text-align:center;'>
          <b>{r['Building']}</b><br>
          🏷️ <i>{r['Building Classification']}</i><br><br>
          📊 {label}: <span style='color:{color}; font-weight:bold;'>{v:.2f}</span><br>
          📈 Avg Monthly: <b>{mon_str}</b>
        </div>
        """
        Popup(popup_html, max_width=280).add_to(
            folium.CircleMarker(
                location=[r["Latitude"],r["Longitude"]],
                radius=6, color="black",
                fill=True, fill_color=color,
                fill_opacity=0.8
            )
        )

    # 只调用一次 st_folium
    st_folium(m, width=900, height=500)

# — 7. 底下再展示一个表，列出所有 building 的月均用量 —
st.header("🏷️ Monthly Mean Usage per Building")
st.dataframe(monthly_mean.groupby("Building")["Monthly_Mean"]
                     .mean().sort_values(ascending=False)
                     .rename("Avg Monthly Use")
                     .to_frame()
                     .reset_index(),
             use_container_width=True)

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
