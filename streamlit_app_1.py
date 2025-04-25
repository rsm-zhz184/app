import streamlit as st
import pandas as pd
import folium
from folium import Popup
from streamlit_folium import st_folium
import altair as alt

# 1. Load data
@st.cache_data
def load_data():
    usage = pd.read_excel("data/Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n", "", regex=True)
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])
    building = pd.read_excel("data/UCSD Building CAAN Info.xlsx")
    coords = pd.read_csv("data/ucsd_building_coordinates.csv")
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

# 2. Utility map
commodity_map = {
    "Electrical": "ELECTRIC",
    "Gas": "NATURALGAS",
    "Hot Water": "HOTWATER",
    "Solar PV": "SOLARPV",
    "ReClaimed Water": "RECLAIMEDWATER",
    "Chilled Water": "CHILLEDWATER"
}

# 3. Precompute CV/Z-score
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util_name, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"] == code].copy()
        df = df.merge(building_info[["Building Capital Asset Account Number", "Building", "Building Classification"]],
                      left_on="CAAN", right_on="Building Capital Asset Account Number", how="left")
        df = df.merge(coordinates[["Building Name", "Latitude", "Longitude"]],
                      left_on="Building", right_on="Building Name", how="left")
        df["Year"] = df["EndDate"].dt.year
        annual = df.groupby(["Building", "Year"])["Use"].sum().reset_index()
        cv_df = annual.groupby("Building")["Use"].agg(["mean", "std"]).reset_index()
        cv_df.columns = ["Building", "Mean", "Std"]
        cv_df["Use_CV"] = cv_df["Std"] / cv_df["Mean"]
        cv_df = cv_df.merge(building_info[["Building", "Building Classification"]], on="Building", how="left")
        cv_df = cv_df.merge(coordinates[["Building Name", "Latitude", "Longitude"]],
                            left_on="Building", right_on="Building Name", how="left")
        cv_df["Z_score"] = cv_df.groupby("Building Classification")["Use_CV"].transform(lambda x: (x - x.mean()) / x.std())
        cv_maps[util_name] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()
all_classes = sorted(building_info["Building Classification"].dropna().unique())

# 4. Sidebar
st.set_page_config(page_title="Campus Heatmap", layout="wide")
st.title("📍 Campus Heatmap")
st.sidebar.header("🔧 Settings")
utility = st.sidebar.selectbox("Utility", list(cv_maps.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + all_classes)
compare_mode = st.sidebar.selectbox("Compare to", ["Self", "Same classification"])

# 5. Filter data
df = cv_maps[utility].copy()
if classification != "All":
    df = df[df["Building Classification"] == classification]

# 6. Compute monthly average
u = usage_data[usage_data["CommodityCode"] == commodity_map[utility]].copy()
u = u.merge(building_info[["Building Capital Asset Account Number", "Building", "Building Classification"]],
            left_on="CAAN", right_on="Building Capital Asset Account Number", how="left")
u = u.merge(coordinates[["Building Name", "Latitude", "Longitude"]],
            left_on="Building", right_on="Building Name", how="left")
if classification != "All":
    u = u[u["Building Classification"] == classification]
u["Month"] = u["EndDate"].dt.to_period("M")
monthly = u.groupby(["Building", "Month"])["Use"].sum().reset_index(name="Monthly_Total")
monthly_mean = monthly.groupby("Building")["Monthly_Total"].mean().reset_index(name="Monthly_Mean")
df = df.merge(monthly_mean, on="Building", how="left")

# 7. Threshold setting
col, low, high, label = ("Use_CV", 0.3, 0.5, "CV") if compare_mode == "Self" else ("Z_score", -1, 1, "Z-score")
df_valid = df.dropna(subset=["Latitude", "Longitude"])

# 8. Folium map
center = [df_valid["Latitude"].mean(), df_valid["Longitude"].mean()]
m = folium.Map(location=center, zoom_start=15)

for _, r in df_valid.iterrows():
    v = r[col]
    color = "red" if v > high else "orange" if v > low else "green"
    mon_str = f"{r['Monthly_Mean']:.2f}" if pd.notna(r['Monthly_Mean']) else "N/A"

    popup_html = f"""
    <div style='font-size:14px;text-align:center;'>
      <b>{r['Building']}</b><br>
      🏷️ <i>{r['Building Classification']}</i><br><br>
      📊 {label}: <span style='color:{color}; font-weight:bold;'>{v:.2f}</span><br>
      📈 Avg Monthly: <b>{mon_str}</b>
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

# 9. Monthly Mean Table
st.header("📊 Monthly Mean Usage per Building")
st.dataframe(monthly_mean.rename(columns={"Monthly_Mean": "Avg Monthly Use"}), use_container_width=True)

# 10. Draw trend if clicked
click = map_data.get("last_clicked") if map_data else None
if click:
    lat, lng = click["lat"], click["lng"]
    df_valid["dist2"] = (df_valid["Latitude"] - lat)**2 + (df_valid["Longitude"] - lng)**2
    bname = df_valid.loc[df_valid["dist2"].idxmin(), "Building"]

    # Filter monthly
    selected = monthly[(monthly["Building"] == bname)]
    selected["Month"] = selected["Month"].dt.to_timestamp()

    st.markdown("---")
    st.subheader(f"📈 Monthly Usage Trend for {bname}")
    line = alt.Chart(selected).mark_line(point=True).encode(
        x="Month:T", y="Monthly_Total:Q",
        tooltip=["Month", "Monthly_Total"]
    ).properties(width=800, height=300)
    st.altair_chart(line, use_container_width=True)

    st.subheader("📊 Yearly Usage Totals")
    selected["Year"] = selected["Month"].dt.year
    yearly = selected.groupby("Year")["Monthly_Total"].sum().reset_index()
    bar = alt.Chart(yearly).mark_bar().encode(
        x="Year:O", y="Monthly_Total:Q",
        tooltip=["Year", "Monthly_Total"]
    ).properties(width=800, height=300)
    st.altair_chart(bar, use_container_width=True)
