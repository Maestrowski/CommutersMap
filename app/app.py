import streamlit as st
import duckdb
import pandas as pd
import requests
import math
import folium
from streamlit_folium import st_folium

st.set_page_config(page_title="London Clean Air Map", layout="wide")

DB_PATH = "data/air_quality.duckdb"

@st.cache_resource
def get_db():
    return duckdb.connect(DB_PATH, read_only=True)

def haversine(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    return 2 * R * math.asin(math.sqrt(a))

def resolve_postcode(postcode: str):
    try:
        res = requests.get(f"https://api.postcodes.io/postcodes/{postcode.strip()}", timeout=5)
        if res.status_code == 200:
            data = res.json()["result"]
            return data["latitude"], data["longitude"], data.get("admin_district")
    except Exception:
        pass
    return None, None, None

def get_daqi_status(species: str, value: float):
    """
    Returns (label, bg_color, text_color) based on UK DEFRA DAQI bands (ug/m3).
    Bands: Low (Green), Moderate (Amber/Orange), High (Red), Very High (Dark Red).
    """
    if value is None or pd.isna(value):
        return "No Data", "#374151", "#9CA3AF"
    
    val = float(value)
    if species == "NO2":
        if val <= 67:
            return "Low", "#15803d", "#FFFFFF"         # Green
        elif val <= 134:
            return "Moderate", "#d97706", "#FFFFFF"    # Amber
        elif val <= 200:
            return "High", "#dc2626", "#FFFFFF"        # Red
        else:
            return "Very High", "#7f1d1d", "#FFFFFF"   # Dark Red
    elif species == "PM25":
        if val <= 11:
            return "Low", "#15803d", "#FFFFFF"
        elif val <= 23:
            return "Moderate", "#d97706", "#FFFFFF"
        elif val <= 35:
            return "High", "#dc2626", "#FFFFFF"
        else:
            return "Very High", "#7f1d1d", "#FFFFFF"
    elif species == "PM10":
        if val <= 16:
            return "Low", "#15803d", "#FFFFFF"
        elif val <= 33:
            return "Moderate", "#d97706", "#FFFFFF"
        elif val <= 50:
            return "High", "#dc2626", "#FFFFFF"
        else:
            return "Very High", "#7f1d1d", "#FFFFFF"
    return "Normal", "#15803d", "#FFFFFF"

con = get_db()

st.title("London Commuter Pollutant Warning Map")

st.subheader("Check the Pollutants in your Postcode Area")
col_input, col_m1, col_m2 = st.columns([2, 1, 1])

with col_input:
    postcode_input = st.text_input("Enter a London Postcode:", value="EC4M 9BR")

lat, lon, borough = resolve_postcode(postcode_input)

# Query active monitors that have valid readings for target pollutants (NO2, PM25, PM10)
active_sites_df = con.execute("""
    SELECT DISTINCT site_code 
    FROM fct_air_readings 
    WHERE is_valid_reading = TRUE
      AND species_code IN ('NO2', 'PM25', 'PM10')
""").df()

active_sites = active_sites_df["site_code"].tolist()

nearest = None
if lat and active_sites:
    sites_df = con.execute(f"""
        SELECT site_code, site_name, site_type, borough_name, latitude, longitude 
        FROM dim_sites 
        WHERE latitude IS NOT NULL 
          AND site_code IN ({','.join([f"'{s}'" for s in active_sites])})
    """).df()

    if not sites_df.empty:
        sites_df["dist_km"] = sites_df.apply(lambda r: haversine(lat, lon, r["latitude"], r["longitude"]), axis=1)
        nearest = sites_df.sort_values("dist_km").iloc[0]

        with col_m1:
            st.metric(label="Nearest Active Monitor", value=nearest["site_code"])
            st.caption(f"{nearest['site_name']} ({nearest['dist_km']:.2f} km)")

        with col_m2:
            st.metric(label="Site Type", value=nearest["site_type"])
            st.caption(f"Borough: {nearest['borough_name']}")
else:
    st.error("Invalid postcode or coordinates unavailable.")

# Local Postcode Pollution Cards 

if nearest is not None:
    st.markdown("#### 🧪 Local Air Quality Levels (Nearest Monitor)")
    
    # Query latest valid reading and its timestamp per species for this monitor
    latest_readings = con.execute(f"""
        SELECT 
            species_code, 
            measurement_value, 
            STRFTIME(reading_datetime, '%Y-%m-%d %H:%M UTC') AS reading_time
        FROM fct_air_readings
        WHERE site_code = '{nearest['site_code']}'
          AND is_valid_reading = TRUE
          AND species_code IN ('NO2', 'PM25', 'PM10')
        QUALIFY ROW_NUMBER() OVER (PARTITION BY species_code ORDER BY reading_datetime DESC) = 1
    """).df()

    # Create mapping dictionaries for values and timestamps
    readings_dict = {row["species_code"]: row["measurement_value"] for _, row in latest_readings.iterrows()}
    timestamps_dict = {row["species_code"]: row["reading_time"] for _, row in latest_readings.iterrows()}
    
    c1, c2, c3 = st.columns(3)
    target_pollutants = [
        ("NO2", "Nitrogen Dioxide (NO₂)", c1),
        ("PM25", "Fine Particulates (PM₂.₅)", c2),
        ("PM10", "Particulate Matter (PM₁₀)", c3),
    ]

    for code, label, col in target_pollutants:
        val = readings_dict.get(code)
        time_str = timestamps_dict.get(code, "N/A")
        band_label, bg_color, text_color = get_daqi_status(code, val)
        val_display = f"{val:.1f} µg/m³" if val is not None else "Sensor Offline"
        time_display = f"Updated: {time_str}" if val is not None else "No recent data"

        with col:
            st.markdown(f"""
                <div style="
                    background-color: {bg_color}; 
                    color: {text_color}; 
                    padding: 16px; 
                    border-radius: 8px; 
                    margin-bottom: 12px;
                    box-shadow: 0 2px 4px rgba(0,0,0,0.2);">
                    <div style="font-size: 13px; opacity: 0.9;">{label}</div>
                    <div style="font-size: 26px; font-weight: bold; margin: 4px 0;">{val_display}</div>
                    <div style="display: flex; justify-content: space-between; align-items: center; font-size: 11px; margin-top: 6px; opacity: 0.95;">
                        <span style="font-weight: 700; text-transform: uppercase;">DEFRA: {band_label}</span>
                        <span>{time_display}</span>
                    </div>
                </div>
            """, unsafe_allow_html=True)

st.markdown("---")

# Hourly Diurnal Profile: NO2, PM25, and PM10
st.subheader("⏱️ 24-Hour Diurnal Pattern (NO₂, PM₂.₅, PM₁₀)")
st.caption("Average hourly concentrations across London commuting corridors, exposing morning and evening rush-hour spikes.")

hourly_multi = con.execute("""
    SELECT 
        hour_of_day,
        species_code,
        ROUND(AVG(measurement_value), 2) AS concentration
    FROM fct_air_readings
    WHERE is_valid_reading = TRUE
      AND species_code IN ('NO2', 'PM25', 'PM10')
      AND hour_of_day BETWEEN 0 AND 23
    GROUP BY hour_of_day, species_code
    ORDER BY hour_of_day, species_code
""").df()

if not hourly_multi.empty:
    pivot_hourly = hourly_multi.pivot(index="hour_of_day", columns="species_code", values="concentration").reindex(range(24))
    st.line_chart(pivot_hourly)
else:
    st.info("No hourly data available.")

# Daily Average Trend (Side-by-Side: NO2, PM2.5, PM10)
st.subheader("📅 Daily Pollutant Exposure (NO₂, PM₂.₅, PM₁₀)")
st.caption("Side-by-side comparison of combustion exhaust (NO₂ - Blue), fine particulates (PM₂.₅ - Green), and dust/wear (PM₁₀ - Orange).")

# Query NO2, PM25, and PM10 aggregated by formatted date string
daily_df = con.execute("""
    SELECT 
        STRFTIME(CAST(reading_datetime AS DATE), '%Y-%m-%d') AS reading_date,
        species_code,
        ROUND(AVG(measurement_value), 2) AS avg_concentration
    FROM fct_air_readings
    WHERE is_valid_reading = TRUE
      AND species_code IN ('NO2', 'PM25', 'PM10')
    GROUP BY CAST(reading_datetime AS DATE), species_code
    ORDER BY reading_date
""").df()

if not daily_df.empty:
    # Pivot so each species gets its own column
    pivot_daily = daily_df.pivot(
        index="reading_date", 
        columns="species_code", 
        values="avg_concentration"
    )

    # Reorder columns to guarantee exact color mapping:
    # NO2 -> Blue, PM25 -> Green, PM10 -> Orange
    cols_order = [c for c in ["NO2", "PM25", "PM10"] if c in pivot_daily.columns]
    pivot_daily = pivot_daily[cols_order]

    # Map colors strictly based on available columns
    color_map = {
        "NO2": "#2563eb",   
        "PM25": "#16a34a",  
        "PM10": "#ea580c"   
    }
    chart_colors = [color_map[col] for col in cols_order]

    # stack=False places them side-by-side; formatted date eliminates the 12 PM ticks
    st.bar_chart(
        pivot_daily,
        stack=False,
        color=chart_colors
    )
else:
    st.info("No daily pollutant data available to display.")


# Interactive Map: Historical 14-Day Hourly Time Machine

st.subheader("🗺️ Monitored Commuter Corridors: Historical Hourly Exposure")
st.caption("Inspect how roadside emissions shift hour-by-hour across your historical observation window.")

# Fetch available dates from the database
available_dates = [
    r[0] for r in con.execute("""
        SELECT DISTINCT CAST(reading_datetime AS DATE) AS r_date
        FROM fct_air_readings
        ORDER BY r_date DESC
    """).fetchall()
]

if not available_dates:
    st.info("No historical readings found to map.")
else:
    # Controls: Date selector, Hour slider, and Species selector
    col_d, col_h, col_s = st.columns([1.5, 2.5, 1.2])

    with col_d:
        selected_date = st.selectbox(
            "Select Date:",
            available_dates,
            index=0,
            format_func=lambda d: d.strftime("%a, %d %b %Y")
        )

    with col_h:
        selected_hour = st.slider(
            "Select Commuting Hour:",
            min_value=0,
            max_value=23,
            value=8,
            format="%02d:00"
        )

    with col_s:
        map_species = st.selectbox("Pollutant:", ["NO2", "PM25", "PM10"], index=0)

    # Timestamp banner displaying the active view
    active_timestamp_str = f"{selected_date.strftime('%Y-%m-%d')} {selected_hour:02d}:00:00"
    st.info(f"🕒 **Viewing Snapshot:** `{selected_date.strftime('%A, %d %B %Y')} at {selected_hour:02d}:00 UTC` | Pollutant: **{map_species}**")

    # Query exact point-in-time readings for that specific date, hour, and species
    snapshot_df = con.execute(f"""
        SELECT 
            site_code,
            measurement_value
        FROM fct_air_readings
        WHERE species_code = '{map_species}'
          AND CAST(reading_datetime AS DATE) = '{selected_date}'
          AND hour_of_day = {selected_hour}
          AND is_valid_reading = TRUE
    """).df()

    snapshot_values = dict(zip(snapshot_df["site_code"], snapshot_df["measurement_value"]))

    # Initialize Folium Map (Free OpenStreetMap tiles, zero API keys required)
    m = folium.Map(location=[51.5074, -0.0940], zoom_start=11, tiles="OpenStreetMap")

    # Render corridor buffer circles and station pins
    for _, row in sites_df.iterrows():
        s_code = row["site_code"]
        val = snapshot_values.get(s_code)
        band_label, bg_color, _ = get_daqi_status(map_species, val)
        
        val_text = f"{val:.1f} µg/m³" if val is not None else "Offline / No Data"

        # 1.8 km corridor buffer zone
        folium.Circle(
            location=[row["latitude"], row["longitude"]],
            radius=1800,
            color=bg_color,
            fill=True,
            fill_color=bg_color,
            fill_opacity=0.35,
            weight=1.5,
            tooltip=f"{row['site_name']} ({row['site_type']}): {val_text} [{band_label}]"
        ).add_to(m)

        # Marker center pin
        folium.CircleMarker(
            location=[row["latitude"], row["longitude"]],
            radius=6,
            color="#111827",
            weight=1,
            fill=True,
            fill_color=bg_color,
            fill_opacity=1.0,
            popup=(
                f"<b>{row['site_name']}</b> ({row['site_code']})<br>"
                f"Type: {row['site_type']}<br>"
                f"Time: {active_timestamp_str}<br>"
                f"{map_species}: <b>{val_text}</b><br>"
                f"DEFRA Band: {band_label}"
            )
        ).add_to(m)

    # Highlight postcode target location
    if lat and lon:
        folium.Marker(
            location=[lat, lon],
            popup=f"Target: {postcode_input}",
            icon=folium.Icon(color="blue", icon="info-sign")
        ).add_to(m)

    st_folium(m, height=480, use_container_width=True)