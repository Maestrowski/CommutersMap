from pathlib import Path
import duckdb

RAW_DATA_DIR = Path("data/raw")
READINGS_DIR = RAW_DATA_DIR / "readings"
SITES_FILE = RAW_DATA_DIR / "sites_raw.json"
DB_PATH = Path("data/air_quality.duckdb")


def get_db_connection() -> duckdb.DuckDBPyConnection:
    """Creates database directory and returns a DuckDB connection."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(DB_PATH))


def create_schema(con: duckdb.DuckDBPyConnection):
    """Initializes dimensional model tables and constraints."""
    
    # Site Metadata Dimension
    con.execute("""
        CREATE TABLE IF NOT EXISTS dim_sites (
            site_code VARCHAR PRIMARY KEY,
            site_name VARCHAR NOT NULL,
            borough_name VARCHAR,
            site_type VARCHAR,
            latitude DOUBLE,
            longitude DOUBLE,
            is_active BOOLEAN
        );
    """)

    # Hourly Air Quality Fact Table 
    con.execute("""
        CREATE TABLE IF NOT EXISTS fct_air_readings (
            reading_id VARCHAR PRIMARY KEY,
            site_code VARCHAR NOT NULL,
            species_code VARCHAR NOT NULL,
            reading_datetime TIMESTAMP NOT NULL,
            measurement_value DOUBLE,
            hour_of_day INTEGER,
            day_of_week INTEGER,
            is_rush_hour BOOLEAN,
            is_valid_reading BOOLEAN,
            FOREIGN KEY (site_code) REFERENCES dim_sites(site_code)
        );
    """)


def transform_dim_sites(con: duckdb.DuckDBPyConnection):
    """
    Transforms raw station metadata into dim_sites.
    Filters for active sites, normalizes keys, and handles data types.
    """
    if not SITES_FILE.exists():
        print(f"[dim_sites] {SITES_FILE} not found. Skipping.")
        return

    # Use staging view to unnest XML-style keys and cast types cleanly
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW stg_sites AS
        SELECT
            "@SiteCode" AS site_code,
            "@SiteName" AS site_name,
            "@LocalAuthorityName" AS borough_name,
            "@SiteType" AS site_type,
            TRY_CAST("@Latitude" AS DOUBLE) AS latitude,
            TRY_CAST("@Longitude" AS DOUBLE) AS longitude,
            CASE WHEN "@DateClosed" = '' OR "@DateClosed" IS NULL THEN TRUE ELSE FALSE END AS is_active
        FROM read_json_auto('{SITES_FILE.as_posix()}');
    """)

    # Upsert into dim_sites (Idempotent: replaces existing records on primary key conflict)
    con.execute("""
        INSERT OR REPLACE INTO dim_sites
        SELECT 
            site_code,
            site_name,
            borough_name,
            site_type,
            latitude,
            longitude,
            is_active
        FROM stg_sites
        WHERE site_code IS NOT NULL;
    """)

    site_count = con.execute("SELECT COUNT(*) FROM dim_sites").fetchone()[0]
    print(f"-> dim_sites updated. Total stations cataloged: {site_count}")


def transform_fct_readings(con: duckdb.DuckDBPyConnection) -> int:
    """
    Transforms raw JSON observation batches into fct_air_readings.
    
    Guarantees idempotency:
      1. Generates surrogate primary key: site_code || '_' || species || '_' || epoch.
      2. Handles sensor gaps: empty strings ("") are converted to NULL.
      3. Performs an anti-join (INSERT WHERE NOT EXISTS) to prevent duplicate rows.
    """
    raw_files = list(READINGS_DIR.glob("*.json"))
    if not raw_files:
        print("[fct_air_readings] No raw readings batches found. Skipping.")
        return 0

    readings_glob = (READINGS_DIR / "*.json").as_posix()

    # Stage raw JSON with extraction of site_code from filename: e.g. 'MY1_20261025_133531.json'
    con.execute(f"""
        CREATE OR REPLACE TEMP VIEW stg_incoming_readings AS
        SELECT
            SPLIT_PART(REVERSE(SPLIT_PART(REVERSE(filename), '/', 1)), '_', 1) AS site_code,
            "@SpeciesCode" AS species_code,
            TRY_CAST("@MeasurementDateGMT" AS TIMESTAMP) AS reading_datetime,
            TRY_CAST(NULLIF("@Value", '') AS DOUBLE) AS measurement_value
        FROM read_json_auto('{readings_glob}', filename=TRUE)
        WHERE "@MeasurementDateGMT" IS NOT NULL
          AND "@SpeciesCode" IS NOT NULL;
    """)

    # Count rows before insert to measure net-new records inserted
    initial_count = con.execute("SELECT COUNT(*) FROM fct_air_readings").fetchone()[0]

    # Insert only distinct records that do not already exist in the fact table
    con.execute("""
        INSERT INTO fct_air_readings
        SELECT
            incoming.site_code || '_' || incoming.species_code || '_' || EPOCH(incoming.reading_datetime) AS reading_id,
            incoming.site_code,
            incoming.species_code,
            incoming.reading_datetime,
            incoming.measurement_value,
            EXTRACT(HOUR FROM incoming.reading_datetime) AS hour_of_day,
            EXTRACT(DOW FROM incoming.reading_datetime) AS day_of_week,
            CASE 
                WHEN EXTRACT(DOW FROM incoming.reading_datetime) BETWEEN 1 AND 5 
                 AND (EXTRACT(HOUR FROM incoming.reading_datetime) BETWEEN 7 AND 9 
                   OR EXTRACT(HOUR FROM incoming.reading_datetime) BETWEEN 17 AND 19)
                THEN TRUE 
                ELSE FALSE 
            END AS is_rush_hour,
            CASE WHEN incoming.measurement_value IS NOT NULL THEN TRUE ELSE FALSE END AS is_valid_reading
        FROM stg_incoming_readings incoming
        LEFT JOIN fct_air_readings existing
            ON (incoming.site_code || '_' || incoming.species_code || '_' || EPOCH(incoming.reading_datetime)) = existing.reading_id
        WHERE existing.reading_id IS NULL;
    """)

    final_count = con.execute("SELECT COUNT(*) FROM fct_air_readings").fetchone()[0]
    inserted_records = final_count - initial_count
    print(f"-> fct_air_readings updated. +{inserted_records} new rows inserted. (Total rows: {final_count})")
    return inserted_records


def build_analytical_marts(con: duckdb.DuckDBPyConnection):
    """
    Creates pre-aggregated mart views directly answering commuter exposure queries.
    """
    con.execute("""
        CREATE OR REPLACE VIEW mart_hourly_corridor_summary AS
        SELECT
            f.hour_of_day,
            f.species_code,
            s.site_type,
            ROUND(AVG(f.measurement_value), 2) AS avg_concentration,
            ROUND(MAX(f.measurement_value), 2) AS peak_concentration,
            COUNT(f.measurement_value) AS valid_readings_count,
            ROUND(COUNT(f.measurement_value)::DOUBLE / NULLIF(COUNT(*), 0) * 100, 1) AS data_completeness_pct
        FROM fct_air_readings f
        JOIN dim_sites s ON f.site_code = s.site_code
        WHERE f.is_valid_reading = TRUE
        GROUP BY f.hour_of_day, f.species_code, s.site_type
        ORDER BY f.species_code, f.hour_of_day, s.site_type;
    """)
    print("-> Analytical view 'mart_hourly_corridor_summary' created.")


def run_transformations():
    """Executes the full transformation lifecycle."""
    print("\n--- Starting Data Transformation & DuckDB Modeling ---")
    con = get_db_connection()
    try:
        create_schema(con)
        transform_dim_sites(con)
        transform_fct_readings(con)
        build_analytical_marts(con)
        print("--- Transformation Complete ---\n")
    finally:
        con.close()


if __name__ == "__main__":
    run_transformations()