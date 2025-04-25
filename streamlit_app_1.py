import streamlit as st
import pandas as pd
import folium
from folium import GeoJson, GeoJsonPopup
from streamlit_folium import st_folium
from pathlib import Path

st.set_page_config(page_title="UCSD Utility Usage Map", layout="wide")


# --- 1) 加载并缓存数据 ---
@st.cache_data
def load_data():
    base = Path("data")
    usage = pd.read_excel(base / "Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n", "", regex=True)
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])

    building = pd.read_excel(base / "UCSD Building CAAN Info.xlsx")
    coords   = pd.read_csv(base / "ucsd_building_coordinates.csv")
    return usage, building, coords

usage_data, building_info, coordinates = load_data()


# --- 2) 定义 Utility ↔ CommodityCode 映射 ---
commodity_map = {
    "Electrical":      "ELECTRIC",
    "Gas":             "NATURALGAS",
    "Hot Water":       "HOTWATER",
    "Solar PV":        "SOLARPV",
    "ReClaimed Water": "RECLAIMEDWATER",
    "Chilled Water":   "CHILLEDWATER",
}


# --- 3) 预计算各栋楼 CV & Z-score ---
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"] == code].copy()
        df = df.merge(
            building_info[["Building Capital Asset Account Number", "Building", "Building Classification"]],
            left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
        )
        df["Year"] = df["EndDate"].dt.year
        annual = df.groupby(["Building", "Year"])["Use"].sum().reset_index()

        cv_df = annual.groupby("Building")["Use"].agg(["mean", "std"]) \
                      .reset_index().rename(columns={"mean": "Mean", "std": "Std"})
        cv_df["Use_CV"] = cv_df["Std"] / cv_df["Mean"]

        cv_df = cv_df.merge(
            building_info[["Building", "Building Classification"]],
            on="Building", how="left"
        ).merge(
            coordinates[["Building Name", "Latitude", "Longitude"]],
            left_on="Building", right_on="Building Name", how="left"
        )

        cv_df["Z_score"] = cv_df.groupby("Building Classification")["Use_CV"] \
                                 .transform(lambda x: (x - x.mean()) / x.std())

        cv_maps[util_name] = cv_df

    return cv_maps

cv_maps = compute_cv_maps()
all_classes = sorted(building_info["Building Classification"].dropna().unique())


# --- 4) Sidebar 配置 ---
st.sidebar.header("Map Settings")
utility       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + all_classes)
compare_mode  = st.sidebar.selectbox("Compare to", ["Self (CV)", "Same class (Z-score)"])


# --- 5) 筛选主表 ---
df = cv_maps[utility].copy()
if classification != "All":
    df = df[df["Building Classification"] == classification]

if df.empty:
    st.warning("No buildings match this filter.")
    st.stop()


# --- 6) 计算月均用量，并合并到主表，用于 popup 显示 ---
u = usage_data[usage_data["CommodityCode"] == commodity_map[utility]].copy()
u = u.merge(
    building_info[["Building Capital Asset Account Number", "Building", "Building Classification"]],
    left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
)
if classification != "All":
    u = u[u["Building Classification"] == classification]

u["Month"] = u["EndDate"].dt.to_period("M")
monthly = u.groupby(["Building", "Month"])["Use"] \
           .sum().reset_index(name="Monthly_Total")
monthly_mean = monthly.groupby("Building")["Monthly_Total"] \
                      .mean().reset_index(name="Avg_Monthly_Use")

df = df.merge(monthly_mean, on="Building", how="left")


# --- 7) 配色阈值 & 构建 GeoJSON FeatureCollection ---
if compare_mode.startswith("Self"):
    col, low, high, label = "Use_CV", 0.3, 0.6, "CV"
else:
    col, low, high, label = "Z_score", -1.0, 1.0, "Z-score"

features = []
for _, r in df.dropna(subset=["Latitude","Longitude",col]).iterrows():
    v = r[col]
    color = "red" if v>high else "orange" if v>low else "green"
    features.append({
        "type": "Feature",
        "properties": {
            "building":      r["Building"],
            "classification":r["Building Classification"],
            "metric":        f"{label}={v:.2f}",
            "avg_month":     f"{r['Avg_Monthly_Use']:.2f}",
            "utility":       utility  # 传给详情页
        },
        "geometry": {
            "type":        "Point",
            "coordinates": [r["Longitude"], r["Latitude"]]
        }
    })

# --- 8) 渲染地图 & 捕捉点击要素 ---
st.header("📍 UCSD Utility Usage Heatmap")
center = [df["Latitude"].mean(), df["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)

GeoJson(
    {"type":"FeatureCollection","features":features},
    name="buildings",
    marker=folium.CircleMarker(radius=6),
    style_function=lambda feat: {"fillColor": (
        "red" if float(feat["properties"]["metric"].split("=")[1])>high else
        "orange" if float(feat["properties"]["metric"].split("=")[1])>low else
        "green"
    )},
    popup=GeoJsonPopup(
        fields=["building","classification","metric","avg_month","utility"],
        aliases=["🏢 Building","🏷️ Class","📊 Metric","📈 Avg Monthly","🔧 Utility"],
        localize=True
    )
).add_to(m)

resp = st_folium(m, width=800, height=500, returned_objects=["last_active_feature"])
feat = resp.get("last_active_feature")


# --- 9) 点击后在本页展示该栋楼的详细时序图 ---
if feat:
    bld = feat["properties"]["building"]
    util = feat["properties"]["utility"]
    st.subheader(f"🔍 Details for **{bld}** ({util})")

    # 取原始月度数据，画折线
    df_bld = monthly[monthly["Building"] == bld] \
             .set_index("Month")["Monthly_Total"] \
             .sort_index().to_timestamp()

    st.line_chart(df_bld, use_container_width=True)
