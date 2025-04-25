import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium
from pathlib import Path

st.set_page_config(page_title="UCSD Utility Usage", layout="wide")

@st.cache_data
def load_data():
    base = Path("data")
    usage    = pd.read_excel(base/"Capstone 2025 Project- Utility Data copy.xlsx")
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
def compute_cv_maps():
    cv_maps = {}
    for util, code in commodity_map.items():
        df0 = usage_data[usage_data["CommodityCode"]==code].copy()
        df0 = df0.merge(
            building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
            left_on="CAAN", right_on="Building Capital Asset Account Number", how="left"
        )
        df0["Year"] = df0["EndDate"].dt.year
        annual = df0.groupby(["Building","Year"])["Use"].sum().reset_index()
        cv_df = annual.groupby("Building")["Use"].agg(["mean","std"]).reset_index()
        cv_df["Use_CV"] = cv_df["std"]/cv_df["mean"]
        cv_df = cv_df.merge(
            building_info[["Building","Building Classification"]],
            on="Building", how="left"
        ).merge(
            coordinates[["Building Name","Latitude","Longitude"]],
            left_on="Building", right_on="Building Name", how="left"
        )
        cv_df["Z_score"] = cv_df.groupby("Building Classification")["Use_CV"] \
                                .transform(lambda x:(x-x.mean())/x.std())
        cv_maps[util] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
all_classes = sorted(building_info["Building Classification"].dropna().unique())

st.sidebar.header("Settings")
utility       = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"]+all_classes)
compare_mode  = st.sidebar.selectbox("Compare to", ["Self (CV)","Same class (Z-score)"])

df = cv_maps[utility].copy()
if classification!="All":
    df = df[df["Building Classification"]==classification]
if df.empty:
    st.warning("No buildings for this filter")
    st.stop()

u = usage_data[usage_data["CommodityCode"]==commodity_map[utility]].copy()
u = u.merge(building_info[["Building Capital Asset Account Number","Building","Building Classification"]],
            left_on="CAAN",right_on="Building Capital Asset Account Number",how="left")
if classification!="All":
    u = u[u["Building Classification"]==classification]
u["Month"] = u["EndDate"].dt.to_period("M")
monthly = u.groupby(["Building","Month"])["Use"].sum().reset_index(name="Monthly_Total")
monthly_mean = monthly.groupby("Building")["Monthly_Total"].mean().reset_index(name="Monthly_Mean")
df = df.merge(monthly_mean, on="Building", how="left")

if compare_mode.startswith("Self"):
    col,low,high,label = "Use_CV",0.3,0.5,"CV"
else:
    col,low,high,label = "Z_score",-1,1,"Z-score"

st.header("📍 Utility Usage Heatmap")
center = [df["Latitude"].mean(), df["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)

for _, r in df.dropna(subset=["Latitude","Longitude",col]).iterrows():
    v = r[col]
    if v>high:
        color, txt = "red",    f"High ⚠️ ({label}={v:.2f})"
    elif v>low:
        color, txt = "orange", f"Medium 🟠 ({label}={v:.2f})"
    else:
        color, txt = "green",  f"Low ✅ ({label}={v:.2f})"
    mon = f"{r['Monthly_Mean']:.2f}" if pd.notna(r['Monthly_Mean']) else "N/A"

    # **关键：跳转到 building_detail 页，一定要带 ?page=building_detail**
    href = (
        f"/?page=building_detail"
        f"&building={r['Building'].replace(' ','%20')}"
        f"&utility={utility.replace(' ','%20')}"
    )

    html = f"""
    <div style='font-size:14px;text-align:center;padding:6px;'>
      <b>{r['Building']}</b><br>
      🏷️ <i>{r['Building Classification']}</i><br><br>
      📊 {txt}<br>
      📈 Avg Monthly: <b>{mon}</b><br><br>
      <a href="{href}" target="_self">View Details →</a>
    </div>"""

    folium.CircleMarker(
        location=[r["Latitude"],r["Longitude"]],
        radius=6, color="black",
        fill=True, fill_color=color,
        fill_opacity=0.85,
        popup=Popup(html, max_width=300)
    ).add_to(m)

st_folium(m, width=800, height=500)
