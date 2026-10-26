import requests

BASE_URL = "https://api.erg.ic.ac.uk/AirQuality"

# 1. Inspect a station entry
sites_res = requests.get(f"{BASE_URL}/Information/MonitoringSites/GroupName=London/Json")
sites_list = sites_res.json()["Sites"]["Site"]
print(f"Total sites: {len(sites_list)}")
print("Sample site record:", sites_list[0])

# 2. Inspect a reading entry for Marylebone Road (MY1)
readings_url = f"{BASE_URL}/Data/Site/SiteCode=MY1/StartDate=2026-10-01/EndDate=2026-10-02/Json"
readings_res = requests.get(readings_url)
readings_list = readings_res.json()["AirQualityData"]["Data"]
print(f"Total sample readings: {len(readings_list)}")
print("Sample reading record:", readings_list[0])