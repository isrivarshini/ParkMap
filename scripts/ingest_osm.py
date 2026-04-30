"""
OSM Ingestion Script
Pulls parking spot data from OpenStreetMap via Overpass API
for Mountain View, CA and loads it into PostGIS.

Usage:
    python scripts/ingest_osm.py
"""

import urllib.request
import urllib.parse
import json
import psycopg2
import os
from dotenv import load_dotenv

load_dotenv()

# Mountain View bounding box (south, west, north, east)
MV_BBOX = (37.3575, -122.1173, 37.4305, -122.0073)

OVERPASS_URL = "https://overpass-api.de/api/interpreter"

QUERY = f"""
[out:json][timeout:60];
(
  node["amenity"="parking"]({MV_BBOX[0]},{MV_BBOX[1]},{MV_BBOX[2]},{MV_BBOX[3]});
  way["amenity"="parking"]({MV_BBOX[0]},{MV_BBOX[1]},{MV_BBOX[2]},{MV_BBOX[3]});
);
out center;
"""


def fetch_osm_data():
    print("Fetching parking data from Overpass API...")
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": QUERY}).encode(),
        headers={"User-Agent": "parkspot-app/1.0"}
    )
    response = urllib.request.urlopen(req, timeout=90)
    data = json.loads(response.read())
    print(f"Raw results from OSM: {len(data['elements'])} elements")
    return data["elements"]


def parse_spot_type(tags: dict) -> str:
    """Determine spot type from OSM tags."""
    fee = tags.get("fee", "").lower()
    access = tags.get("access", "").lower()

    if fee in ("yes", "true", "paid"):
        return "paid"

    # check for time-limited free parking
    if tags.get("maxstay") or tags.get("parking:condition") or tags.get("fee:conditional"):
        return "time_limited"

    if fee in ("no", "free") or access == "public":
        return "free"

    # default to free if no fee info
    return "free"


def parse_schedule(tags: dict):
    """Extract free hours from OSM tags."""
    free_from = None
    free_until = None
    free_days = None

    conditional = tags.get("fee:conditional", "")
    if "no @" in conditional.lower():
        # e.g. "no @ (Mo-Fr 18:00-08:00)"
        try:
            hours_part = conditional.split("@")[1].strip().strip("()")
            if "-" in hours_part:
                parts = hours_part.split(" ")
                if len(parts) == 2:
                    free_days = parts[0]
                    times = parts[1].split("-")
                    free_from = times[0]
                    free_until = times[1]
        except Exception:
            pass

    return free_from, free_until, free_days


def get_coords(element: dict):
    """Get lat/lng from node or way (way uses center)."""
    if element["type"] == "node":
        return element["lat"], element["lon"]
    elif element["type"] == "way" and "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    return None, None


def ingest(elements: list):
    db_url = os.getenv("DATABASE_URL_SYNC")
    conn = psycopg2.connect(db_url)

    inserted = 0
    skipped = 0

    for el in elements:
        tags = el.get("tags", {})
        osm_id = f"{el['type']}/{el['id']}"
        lat, lng = get_coords(el)

        if lat is None or lng is None:
            skipped += 1
            continue

        spot_type = parse_spot_type(tags)
        free_from, free_until, free_days = parse_schedule(tags)

        name = tags.get("name") or tags.get("operator") or None
        capacity_str = tags.get("capacity")
        capacity = int(capacity_str) if capacity_str and capacity_str.isdigit() else None

        hourly_rate = None
        if spot_type == "paid":
            rate_str = tags.get("charge", "")
            try:
                hourly_rate = float("".join(c for c in rate_str if c.isdigit() or c == "."))
            except Exception:
                pass

        # fresh cursor per row so one failure doesn't kill the transaction
        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO spots
                    (geom, spot_type, name, capacity, hourly_rate,
                     free_from, free_until, free_days, source, osm_id, verified)
                VALUES
                    (ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                     %s, %s, %s, %s, %s, %s, %s, 'osm', %s, true)
                ON CONFLICT (osm_id) DO NOTHING
            """, (lng, lat, spot_type, name, capacity, hourly_rate,
                  free_from, free_until, free_days, osm_id))
            conn.commit()
            inserted += 1
        except Exception as e:
            conn.rollback()
            print(f"  Skipped {osm_id}: {e}")
            skipped += 1
        finally:
            cur.close()

    conn.close()

    print(f"\nIngestion complete:")
    print(f"  Inserted: {inserted}")
    print(f"  Skipped:  {skipped}")
    print(f"  Total:    {len(elements)}")

def main():
    print("ParkSpot OSM Ingestion — Mountain View, CA")
    print("=" * 45)
    elements = fetch_osm_data()
    if not elements:
        print("No elements returned from Overpass. Try again later.")
        return
    ingest(elements)
    print("\nDone! Run the FastAPI server to see your data.")
    print("  uvicorn backend.main:app --reload")


if __name__ == "__main__":
    main()