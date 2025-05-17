# streamlit_app.py

import streamlit as st
import pandas as pd
import folium
from folium import Popup
from folium.plugins import Search
from streamlit_folium import st_folium
import altair as alt

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
    building_info[['Building Capital Asset Account Number','Building']],
    left_on='CAAN', right_on='Building Capital Asset Account Number', how='left'
).drop(columns=['Building Capital Asset Account Number'])

# 3. Precompute CV & Z-score maps (for sidebar filters if needed)
commodity_map = {
    "Electrical":       "ELECTRIC",
    "Gas":              "NATURALGAS",
    "Hot Water":        "HOTWATER",
    "Solar PV":         "SOLARPV",
    "ReClaimed Water":  "RECLAIMEDWATER",
    "Chilled Water":    "CHILLEDWATER",
    'Water':            "WATER"
}
@st.cache_data
def compute_cv_maps():
    cv_maps = {}
    for util, code in commodity_map.items():
        df = usage_data[usage_data["CommodityCode"] == code].copy()
        df = df.merge(
            building_info[['Building','Building Classification']], on='Building', how='left'
        ).merge(
            coordinates[['Building Name','Latitude','Longitude']],
            left_on='Building', right_on='Building Name', how='left'
        )
        df['Year'] = df['EndDate'].dt.year
        annual = df.groupby(['Building','Year'])['Use'].sum().reset_index()
        cv_df = (annual.groupby('Building')['Use']
                 .agg(['mean','std']).reset_index()
                 .rename(columns={'mean':'Mean','std':'Std'})
        )
        cv_df['Use_CV'] = cv_df['Std'] / cv_df['Mean']
        cv_df = cv_df.merge(
            building_info[['Building','Building Classification']], on='Building', how='left'
        ).merge(
            coordinates[['Building Name','Latitude','Longitude']],
            left_on='Building', right_on='Building Name', how='left'
        )
        cv_df['Z_score'] = cv_df.groupby('Building Classification')['Use_CV'] \
                             .transform(lambda x: (x - x.mean())/x.std())
        cv_maps[util] = cv_df
    return cv_maps

cv_maps = compute_cv_maps()

# 4. Sidebar settings (Utility/Classification) + Distribution toggle
st.sidebar.header("🔧 Settings")
utility       = st.sidebar.selectbox("Utility", list(commodity_map.keys()))
classification = st.sidebar.selectbox(
    "Classification", ["All"] + sorted(building_info['Building Classification'].dropna().unique())
)
show_dist     = st.sidebar.checkbox("Show distribution charts", value=False)

# 5. Prepare df_map according to filters
#    If no search, default: filtered by utility + classification
if utility:
    df_map = cv_maps[utility]
    if classification != "All":
        df_map = df_map[df_map['Building Classification'] == classification]
else:
    df_map = usage_data.merge(
        building_info[['Building','Building Classification']], on='Building', how='left'
    ).merge(
        coordinates[['Building Name','Latitude','Longitude']],
        left_on='Building', right_on='Building Name', how='left'
    )

# drop null coords
df_map = df_map.dropna(subset=['Latitude','Longitude'])

# 6. Build Folium map with Search plugin
center = [df_map['Latitude'].mean(), df_map['Longitude'].mean()]
m = folium.Map(location=center, zoom_start=15)
fg = folium.FeatureGroup(name='buildings').add_to(m)
for _, r in df_map.iterrows():
    folium.Marker(
        location=[r['Latitude'], r['Longitude']],
        popup=r['Building'],
        icon=folium.Icon(color='blue', icon='info-sign')
    ).add_to(fg)
Search(
    layer=fg,
    search_label='popup',
    placeholder='Search building... (type and select)',
    collapsed=False,
    position='topleft'
).add_to(m)
map_data = st_folium(m, width=900, height=500)

# 7. Show distribution charts below map on marker click or after search selection
if show_dist and map_data.get('last_object_clicked'):
    props = map_data['last_object_clicked'].get('properties', {})
    bld = props.get('popup') or props.get('building')
    if bld:
        st.markdown("---")
        st.subheader(f"📈 All Utilities Monthly Trend for {bld}")
        for util, code in commodity_map.items():
            sub = usage_data[(usage_data['Building'] == bld) & 
                              (usage_data['CommodityCode'] == code)].copy()
            if sub.empty:
                continue
            sub['Month'] = sub['EndDate'].dt.to_period('M').dt.to_timestamp()
            monthly = sub.groupby('Month')['Use'].sum().reset_index()
            line = alt.Chart(monthly).mark_line(point=True).encode(
                x='Month:T', y='Use:Q', tooltip=['Month','Use']
            ).properties(width=250, height=150, title=util)
            st.altair_chart(line, use_container_width=False)
