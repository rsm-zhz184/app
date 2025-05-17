# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from folium.plugins import Search
from streamlit_folium import st_folium
import altair as alt
from rapidfuzz import process

# 1. Load & cache data
@st.cache_data
def load_data():
    usage = pd.read_excel("data/Capstone 2025 Project- Utility Data copy.xlsx")
    usage.columns = usage.columns.str.replace("\n", "", regex=True)
    usage["EndDate"] = pd.to_datetime(usage["EndDate"])
    building = pd.read_excel("data/UCSD Building CAAN Info.xlsx")
    coords   = pd.read_csv("data/ucsd_building_coordinates.csv")
    return usage, building, coords

usage_data, building_info, coordinates = load_data()

# 2. Merge Building Name via CAAN
usage_data['CAAN'] = usage_data['CAAN'].astype(str).str.strip()
building_info['Building Capital Asset Account Number'] = (
    building_info['Building Capital Asset Account Number'].astype(str).str.strip()
)
usage_data = usage_data.merge(
    building_info[['Building Capital Asset Account Number','Building','Building Classification']],
    left_on='CAAN', right_on='Building Capital Asset Account Number', how='left'
).drop(columns=['Building Capital Asset Account Number'])

usage_data = usage_data.merge(
    coordinates[['Building Name','Latitude','Longitude']],
    left_on='Building', right_on='Building Name', how='left'
)

# 3. Sidebar filters and search box
st.sidebar.header("🔍 Search or Filter")
all_buildings = sorted(usage_data['Building'].dropna().unique())
search_input = st.sidebar.text_input("Enter building name (fuzzy match supported):")
matched_bld = None
if search_input:
    match, score, _ = process.extractOne(search_input, all_buildings)
    if score >= 60:
        st.sidebar.success(f"Matched: {match} (score={score:.0f})")
        matched_bld = match
    else:
        st.sidebar.warning("No good match found.")

st.sidebar.markdown("---")
st.sidebar.header("🔧 Filters (ignored after search)")
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER",
    'Water':            "WATER"
}
utility = st.sidebar.selectbox("Utility", list(commodity_map.keys()))
classification = st.sidebar.selectbox("Classification", ["All"] + sorted(building_info['Building Classification'].dropna().unique()))
show_dist = st.sidebar.checkbox("Show distribution charts", value=False)

# 4. Prepare data based on either search or filter
if matched_bld:
    df_map = usage_data[usage_data['Building'] == matched_bld]
    center = [df_map['Latitude'].mean(), df_map['Longitude'].mean()]
else:
    df_map = usage_data[usage_data['CommodityCode'] == commodity_map[utility]]
    if classification != "All":
        df_map = df_map[df_map['Building Classification'] == classification]
    center = [df_map['Latitude'].mean(), df_map['Longitude'].mean()]

df_map = df_map.dropna(subset=['Latitude','Longitude'])

# 5. Build map with Search and Markers
m = folium.Map(location=center, zoom_start=15)
fg = folium.FeatureGroup(name='buildings').add_to(m)
for _, r in df_map.iterrows():
    popup = f"{r['Building']}<br>{r['CommodityCode']}"
    folium.Marker(
        location=[r['Latitude'], r['Longitude']],
        popup=popup,
        icon=folium.Icon(color='blue', icon='info-sign')
    ).add_to(fg)
Search(
    layer=fg,
    search_label='popup',
    placeholder='Search building... (map)',
    collapsed=False,
    position='topleft'
).add_to(m)
map_data = st_folium(m, width=900, height=500)

# 6. Show distribution charts if enabled
bld = None
if matched_bld:
    bld = matched_bld
elif map_data.get('last_object_clicked'):
    popup_text = map_data['last_object_clicked'].get('popup')
    if popup_text:
        bld = popup_text.split("<br>")[0]

if show_dist and bld:
    st.markdown("---")
    st.subheader(f"📈 Monthly Usage Trends for {bld}")
    for util, code in commodity_map.items():
        sub = usage_data[(usage_data['Building'] == bld) & 
                         (usage_data['CommodityCode'] == code)].copy()
        if sub.empty:
            continue
        sub['Month'] = sub['EndDate'].dt.to_period('M').dt.to_timestamp()
        monthly = sub.groupby('Month')['Use'].sum().reset_index()
        line = alt.Chart(monthly).mark_line(point=True).encode(
            x='Month:T', y='Use:Q', tooltip=['Month','Use']
        ).properties(width=300, height=200, title=util)
        st.altair_chart(line, use_container_width=False)
