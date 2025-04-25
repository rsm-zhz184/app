import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium
from urllib.parse import quote

# 1) 载入并缓存数据
@st.cache_data
def load_data():
    usage = pd.read_excel("data/Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n", "", regex=True)
    building = pd.read_excel("data/UCSD Building CAAN Info.xlsx")
    coords   = pd.read_csv("data/ucsd_building_coordinates.csv")
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])
    mon = (
        usage.assign(Month=usage["EndDate"].dt.to_period("M"))
             .groupby(["Building", "CommodityCode", "Month"])["Use"]
             .sum()
             .reset_index(name="Monthly_Total")
    )
    return usage, building, coords, mon

usage_data, building_info, coordinates, mon = load_data()

commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER"
}

@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"] == code].copy()
        df = df.merge(
            building_info[["Building Capital Asset Account Number", "Building", "Building Classification"]],
            left_on="CAAN",
            right_on="Building Capital Asset Account Number",
            how="left"
        )
        df["Year"] = pd.to_datetime(df["EndDate"]).dt.year
        annual = df.groupby(["Building", "Year"])["Use"].sum().reset_index()

        cv_df = (
            annual.groupby("Building")["Use"]
                  .agg(["mean", "std"])
                  .rename(columns={"mean": "Mean", "std": "Std"})
                  .reset_index()
        )
        cv_df["Use_CV"] = cv_df["Std"] / cv_df["Mean"]

        cv_df = (
            cv_df.merge(building_info[["Building", "Building Classification"]], on="Building", how="left")
                 .merge(coordinates[["Building Name", "Latitude", "Longitude"]],
                        left_on="Building", right_on="Building Name", how="left")
        )
        cv_df["Z_score"] = cv_df.groupby("Building Classification")["Use_CV"] \
                                 .transform(lambda x: (x - x.mean()) / x.std())

        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
all_classes = sorted(building_info["Building Classification"].dropna().unique())

st.set_page_config(page_title="Campus Heatmap", layout="wide")
st.title("\ud83d\udccd Campus Heatmap")
st.sidebar.header("\ud83d\udd27 Settings")
utility = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + all_classes)
compare_mode = st.sidebar.selectbox("Compare to", ["Self", "Same classification"])

df = cv_maps[utility].copy()
if classification != "All":
    df = df[df["Building Classification"] == classification]

u = usage_data[usage_data["CommodityCode"] == commodity_map[utility]].copy()
u = u.merge(
    building_info[["Building Capital Asset Account Number", "Building", "Building Classification"]],
    left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
)
if classification != "All":
    u = u[u["Building Classification"] == classification]
u["Month"] = pd.to_datetime(u["EndDate"]).dt.to_period("M")
monthly = u.groupby(["Building", "Month"])["Use"].sum().reset_index(name="Monthly_Total")
monthly_mean = monthly.groupby("Building")["Monthly_Total"].mean().reset_index(name="Monthly_Mean")
df = df.merge(monthly_mean, on="Building", how="left")

if compare_mode == "Self":
    col, low, high, label = "Use_CV", 0.3, 0.5, "CV"
else:
    col, low, high, label = "Z_score", -1, 1, "Z-score"

df_valid = df.dropna(subset=["Latitude", "Longitude"])
if df_valid.empty:
    st.warning("\u2705 \u8fd9\u4e2a\u5206\u7c7b\u4e0b\u6ca1\u6709\u4efb\u4f55\u5e26\u5750\u6807\u7684\u5efa\u7b51\uff0c\u65e0\u6cd5\u663e\u793a\u70ed\u529b\u56fe\u3002")
    st.stop()

center = [df_valid["Latitude"].mean(), df_valid["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)
for _, r in df_valid.iterrows():
    v = r[col]
    color = "red" if v > high else "orange" if v > low else "green"
    mon_str = f"{r['Monthly_Mean']:.2f}" if pd.notna(r["Monthly_Mean"]) else "N/A"
    building_encoded = quote(r["Building"])

    popup_html = f"""
    <div style='font-size:14px; text-align:center;'>
      <b>{r['Building']}</b><br>
      \ud83c\udff7\ufe0f <i>{r['Building Classification']}</i><br><br>
      \ud83d\udcca {label}: <span style='color:{color}; font-weight:bold;'>{v:.2f}</span><br>
      \ud83d\udcc8 Avg Monthly: <b>{mon_str}</b><br><br>
      <a href='?building={building_encoded}&utility={utility}' target='_self' style='text-decoration:none;color:#0066cc;'>View Details &rarr;</a>
    </div>
    """
    marker = folium.CircleMarker(
        location=[r["Latitude"], r["Longitude"]],
        radius=6,
        color="black",
        fill=True,
        fill_color=color,
        fill_opacity=0.8
    ).add_to(m)
    Popup(popup_html, max_width=300).add_to(marker)

map_data = st_folium(m, width=900, height=500, returned_objects=["last_clicked"])

st.header("\ud83c\udff7\ufe0f Monthly Mean Usage per Building")
st.dataframe(
    monthly_mean
      .rename(columns={"Monthly_Mean": "Avg Monthly Use"})
      .sort_values("Avg Monthly Use", ascending=False)
      .reset_index(drop=True),
    use_container_width=True
)

click = map_data.get("last_clicked") if map_data else None
if click:
    lat, lng = click["lat"], click["lng"]
    df_valid["dist2"] = (df_valid["Latitude"] - lat) ** 2 + (df_valid["Longitude"] - lng) ** 2
    idx = df_valid["dist2"].idxmin()
    bld = df_valid.loc[idx, "Building"]

    st.markdown("---")
    st.markdown(f"## \ud83c\udfe2 Detail for **{bld}**")

    df_month = (
        mon.query("CommodityCode == @commodity_map[utility]")
           .query("Building == @bld")
           .set_index("Month")["Monthly_Total"]
    )

    st.subheader("\ud83d\udcc8 Monthly Usage Trend")
    st.line_chart(df_month, use_container_width=True)

    yearly = df_month.groupby(df_month.index.year).sum()
    st.subheader("\ud83d\udcca Yearly Usage Totals")
    st.bar_chart(yearly, use_container_width=True)
