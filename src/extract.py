import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
import requests

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"
RAW_DATA_DIR = Path("data/raw")
READINGS_DIR = RAW_DATA_DIR / "readings"
STATE_FILE = RAW_DATA_DIR / "ingest_state.json"

TARGET_SITES = [
    "MY1",  # Westminster - Marylebone Road (Kerbside)
    "KC1",  # Kensington & Chelsea - North Ken (Urban Background reference)
    "HK6",  # Hackney - Old Street (Roadside / City edge)
    "LB4",  # Lambeth - Brixton Road (Kerbside - notorious NO2 hotspot)
    "WA7",  # Wandsworth - Putney High Street (Kerbside - rich PM10/PM25)
    "SK5",  # Southwark - A2 Old Kent Road (Roadside)
    "HG4",  # Haringey - Priory Park South (Urban Background near N17)
    "TH2",  # Tower Hamlets - Mile End Road (Roadside - A11 corridor)
]


def load_state() -> dict:
    """Loads high-watermark timestamps per site."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(state: dict):
    """Persists high-watermark timestamps."""
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2)


def fetch_site_metadata():
    """Fetches and overwrites station metadata idempotently."""
    RAW_DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_file = RAW_DATA_DIR / "sites_raw.json"

    url = f"{BASE_URL}/Information/MonitoringSites/GroupName=London/Json"
    res = requests.get(url, timeout=15)
    res.raise_for_status()
    sites = res.json().get("Sites", {}).get("Site", [])

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(sites, f, indent=2)

    print(f"-> Metadata synced: {len(sites)} sites saved to {out_file}")
    return sites


def fetch_incremental_readings(days_backfill: int = 14) -> int:
    """
    Incrementally ingests hourly readings per target site.
    
    Guarantees idempotency:
      1. Uses exact datetime high-watermark per site.
      2. Re-queries from the watermark date to capture intra-day hourly updates.
      3. Filters payloads so only records strictly newer than the watermark are persisted.
      4. Produces zero duplicate records and zero redundant writes on repeated runs.
    """
    READINGS_DIR.mkdir(parents=True, exist_ok=True)
    state = load_state()
    now_utc = datetime.now(timezone.utc)
    today_str = now_utc.strftime("%Y-%m-%d")
    total_new_records = 0

    print(f"\n--- Checking incremental sync up to {today_str} (UTC) ---")

    for site in TARGET_SITES:
        last_watermark_str = state.get(site)
        
        if last_watermark_str:
            last_dt = datetime.strptime(last_watermark_str, "%Y-%m-%d %H:%M:%S")
            # Query from the calendar day of the watermark to capture newly added hours
            start_str = last_dt.strftime("%Y-%m-%d")
        else:
            last_dt = None
            start_date = now_utc - timedelta(days=days_backfill)
            start_str = start_date.strftime("%Y-%m-%d")

        url = f"{BASE_URL}/Data/Site/SiteCode={site}/StartDate={start_str}/EndDate={today_str}/Json"

        try:
            res = requests.get(url, timeout=15)
            res.raise_for_status()
            raw_records = res.json().get("AirQualityData", {}).get("Data", [])

            # Filter records: keep only those with a datetime > last_dt
            new_records = []
            max_dt_in_batch = last_dt

            for r in raw_records:
                ts_str = r.get("@MeasurementDateGMT")
                if not ts_str:
                    continue

                r_dt = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")

                if last_dt is None or r_dt > last_dt:
                    new_records.append(r)
                    if max_dt_in_batch is None or r_dt > max_dt_in_batch:
                        max_dt_in_batch = r_dt

            if not new_records:
                print(f"[{site}] Up to date (watermark: {last_watermark_str}). 0 new records.")
                continue

            # Persist only the newly detected delta records
            batch_ts = now_utc.strftime("%Y%m%d_%H%M%S")
            batch_filename = f"{site}_{batch_ts}.json"
            batch_path = READINGS_DIR / batch_filename

            with open(batch_path, "w", encoding="utf-8") as f:
                json.dump(new_records, f, indent=2)

            # Advance the high watermark to the newest observation timestamp
            state[site] = max_dt_in_batch.strftime("%Y-%m-%d %H:%M:%S")
            save_state(state)

            print(f"[{site}] +{len(new_records)} new records (new watermark: {state[site]}) -> {batch_filename}")
            total_new_records += len(new_records)
            time.sleep(0.5)  # Respect API rate limits

        except Exception as e:
            print(f"[{site}] Error fetching data: {e}")

    print(f"\nIncremental run complete. Total new records ingested: {total_new_records}")
    return total_new_records


if __name__ == "__main__":
    fetch_site_metadata()
    fetch_incremental_readings(days_backfill=14)