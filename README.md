# London Air Quality for commuters

## What I built and who is it for

I built an air quality tracker which analyses the number of pollutants such as NO2, PM2.5 and PM10 across London. This application allows to view the latest pollution data in a specific postcode, gathering data from the nearest pollution monitor, the user is also able to see the hourly graph and daily histogram showcasing the pollution levels in the area. There is also a map which reveals the pollution of every area in London which is colour coded to signify the pollution levels or if the monitor is offline. 

This application was designed for commuters and more specifically London residents that are within the health risk of having asthma, pneumonia, tuberculosis etc. They would use the application to look at patterns of when there is a high amount of pollution in their area or in the area they wish to travel to. They can see that for example in the last 2 weeks consistently on a Tuesday 11am there was high levels of NO2, so with that in mind they might avoid travel at that time to protect themself. 

It can also be used for runners and cyclists that would also try to avoid any polluted areas for optimal performance. 

## The data

- **Data Source:** https://api.erg.ic.ac.uk/AirQuality
- **Extra API source:** https://api.postcodes.io/
- **Documentation link:** https://api.erg.ic.ac.uk/AirQuality/Information/Documentation/pdf

Data gathered:
- **Payload details:** Station codes, Official Station names, Borough authority affiliation, site classification (Kerbside, Roadside, Urban Background), Geographic coordinates
- **Target Stations:** MY1, LB4, WA7, TH2, SK5, KC1, HG4
- **Target Pollutants:** NO2, PM2.5, PM10, 

## How it works

### Caching and Ingestion Strategy:
- API JSON responses are staged immutably in data/raw/ before the transformation stage. This ensures there is no redundant HTTP calls to the LAQN endpoint, guarantee reproducible offline testing and prevent API rate-limiting
- Tracks the latest ingested timestamp per station to only fetch record on changed records instead of doing full historical backfills.

### Transformation Pipeline
- Ingested payloads are processed directly into an embedded serverless DuckDB instance, which brings columnar query performance without database infrastructure overhead.
- **Dimensional Modeling**:
    dim_sites: Captures static geographical and administrative metadata (site code, borough, site classification, latitude, longitude).   
    fct_air_readings: Stores granular hourly observations with an MD5 surrogate key generated from MD5(site_code || species_code || reading_datetime) to ensure deduplication and idempotent upserts.
- Empty string responses ("") from offline monitors are set to NULL values with an explicit boolean flag (is_valid_reading) to ensure downstream averages do not impact real-world exposure

### Streamlit interface
- Resolve any user-provided London postcode (e.g. EC4M 9BR) into WGS84 coordinates using api.postcodes.io, then compute a radius around active stations in DuckDB to bind the user to their nearest monitoring site.
- Evaluate raw concentrations against official UK Daily Air Quality Index thresholds using colour coded status badges from (green, light green, yellow, red, dark red) to signify (Very Low, Low, Moderate, High, Dangerously High)
- Visualise the 24-hour pollution profile of NO2, PM2.5 and PM10 to show peak commuter exposure windows during rush hours
- Render multi-pollutant exposure across 14 days side by side as a histogram
- An interactive OpenStreetMap layer which allows users to see 14 days of hourly observations, dynamically adjusting station colour coded radius to reveal pollution danger levels.

## How to run it

### Prerequisites
- Python 3.10+
- Virtual environment tool (venv)

### Environment setup
git clone https://github.com/Maestrowski/CommutersMap.git
cd CommutersMap

### Virtual environment 
python -m venv .venv
.venv\Scripts\Activate.ps1

pip install -r requirements.txt

### Execute the data pipeline

python main.py

### Activate the streamlit interface 

streamlit run app/app.py

Streamlit will print a local URL in your terminal. Navigate to the URL:
http://localhost:8501

## What I would do next

Gather data and implement a feature that allows to calculate the cumulative pollutant exposure along a commuter route (from St Paul's to Mile End for example) and suggest a cleaner navigation pathway instead of the fastest pathway.

Develop a time-series model that can forecast rush-hour pollution 24 hours in advance.

Locate or scrape data that would be capable of filling in data from offline monitors.

## Where AI helped

I used AI to research the key pollutants that commuters might need to look out for. Also used AI to pick out the monitor stations and how many should be used for most optimal results without overwhelming rate limits but showing a vast coverage of London. 