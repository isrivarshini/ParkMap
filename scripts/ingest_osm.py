"""
OSM Multi-City Ingestion Script
Pulls parking spot data from OpenStreetMap via Overpass API
for multiple cities and loads into PostGIS.

Usage:
    python scripts/ingest_osm.py                    # all cities
    python scripts/ingest_osm.py --city sf          # single city
    python scripts/ingest_osm.py --city mv,sf       # multiple cities
"""

import urllib.request
import urllib.parse
import json
import psycopg2
import os
import sys
import argparse
from dotenv import load_dotenv

load_dotenv()

CITIES = {
    "mv": {
        "name": "Mountain View",
        "slug": "mountain_view",
        "bbox": (37.3575, -122.1173, 37.4305, -122.0073),
        "center": (37.3861, -122.0840),
        "zoom": 13,
    },
    "sf": {
        "name": "San Francisco",
        "slug": "san_francisco",
        "bbox": (37.6879, -122.5135, 37.8324, -122.3531),
        "center": (37.7749, -122.4194),
        "zoom": 12,
    },
    "la": {
        "name": "Los Angeles",
        "slug": "los_angeles",
        "bbox": (33.7037, -118.6682, 34.3373, -118.1553),
        "center": (34.0522, -118.2437),
        "zoom": 11,
    },
    "seattle": {
        "name": "Seattle",
        "slug": "seattle",
        "bbox": (47.4810, -122.4596, 47.7341, -122.2244),
        "center": (47.6062, -122.3321),
        "zoom": 12,
    },
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_query(bbox):
    s, w, n, e = bbox
    return f"""
[out:json][timeout:90];
(
  node["amenity"="parking"]({s},{w},{n},{e});
  way["amenity"="parking"]({s},{w},{n},{e});
);
out center;
"""


def fetch_osm_data(city_key):
    city = CITIES[city_key]
    print(f"  Fetching from Overpass API for {city['name']}...")
    query = build_query(city["bbox"])
    req = urllib.request.Request(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": query}).encode(),
        headers={"User-Agent": "parkspot-app/1.0"}
    )
    response = urllib.request.urlopen(req, timeout=120)
    data = json.loads(response.read())
    elements = data["elements"]
    print(f"  Raw results: {len(elements)} elements")
    return elements


def parse_spot_type(tags):
    fee = tags.get("fee", "").lower()
    if fee in ("yes", "true", "paid"):
        return "paid"
    if tags.get("maxstay") or tags.get("parking:condition") or tags.get("fee:conditional"):
        return "time_limited"
    if fee in ("no", "free") or tags.get("access", "").lower() == "public":
        return "free"
    return "free"


def parse_schedule(tags):
    free_from = free_until = free_days = None
    conditional = tags.get("fee:conditional", "")
    if "no @" in conditional.lower():
        try:
            hours_part = conditional.split("@")[1].strip().strip("()")
            parts = hours_part.split(" ")
            if len(parts) == 2:
                free_days = parts[0]
                times = parts[1].split("-")
                free_from = times[0]
                free_until = times[1] if len(times) > 1 else None
        except Exception:
            pass
    return free_from, free_until, free_days


def get_coords(element):
    if element["type"] == "node":
        return element["lat"], element["lon"]
    elif element["type"] == "way" and "center" in element:
        return element["center"]["lat"], element["center"]["lon"]
    return None, None


def ensure_cities_table(conn):
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS cities (
            id SERIAL PRIMARY KEY,
            slug VARCHAR(50) UNIQUE NOT NULL,
            name VARCHAR(100) NOT NULL,
            center_lat FLOAT NOT NULL,
            center_lng FLOAT NOT NULL,
            default_zoom INTEGER NOT NULL DEFAULT 12
        );
    """)
    for key, city in CITIES.items():
        cur.execute("""
            INSERT INTO cities (slug, name, center_lat, center_lng, default_zoom)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (slug) DO UPDATE
            SET name=EXCLUDED.name,
                center_lat=EXCLUDED.center_lat,
                center_lng=EXCLUDED.center_lng,
                default_zoom=EXCLUDED.default_zoom;
        """, (city["slug"], city["name"], city["center"][0], city["center"][1], city["zoom"]))
    conn.commit()
    cur.close()


def ensure_city_column(conn):
    cur = conn.cursor()
    cur.execute("""
        ALTER TABLE spots ADD COLUMN IF NOT EXISTS city_slug VARCHAR(50) DEFAULT 'mountain_view';
    """)
    conn.commit()
    cur.close()


def ingest_city(city_key, elements, conn):
    city = CITIES[city_key]
    city_slug = city["slug"]
    inserted = skipped = 0

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

        cur = conn.cursor()
        try:
            cur.execute("""
                INSERT INTO spots
                    (geom, spot_type, name, capacity, hourly_rate,
                     free_from, free_until, free_days, source, osm_id, verified, city_slug)
                VALUES
                    (ST_SetSRID(ST_MakePoint(%s, %s), 4326),
                     %s, %s, %s, %s, %s, %s, %s, 'osm', %s, true, %s)
                ON CONFLICT (osm_id) DO NOTHING
            """, (lng, lat, spot_type, name, capacity, hourly_rate,
                  free_from, free_until, free_days, osm_id, city_slug))
            conn.commit()
            inserted += 1
        except Exception as e:
            conn.rollback()
            skipped += 1
        finally:
            cur.close()

    return inserted, skipped


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--city", type=str, default=None,
        help="Comma-separated city keys: mv, sf, la, seattle (default: all)")
    args = parser.parse_args()

    if args.city:
        keys = [k.strip() for k in args.city.split(",")]
        invalid = [k for k in keys if k not in CITIES]
        if invalid:
            print(f"Unknown city keys: {invalid}. Valid: {list(CITIES.keys())}")
            sys.exit(1)
    else:
        keys = list(CITIES.keys())

    db_url = os.getenv("DATABASE_URL_SYNC")
    conn = psycopg2.connect(db_url)

    print("Setting up cities table...")
    ensure_cities_table(conn)
    ensure_city_column(conn)

    total_inserted = total_skipped = 0

    for key in keys:
        city = CITIES[key]
        print(f"\n{'='*45}")
        print(f"Ingesting: {city['name']}")
        print(f"{'='*45}")
        try:
            elements = fetch_osm_data(key)
            inserted, skipped = ingest_city(key, elements, conn)
            total_inserted += inserted
            total_skipped += skipped
            print(f"  Inserted: {inserted} | Skipped: {skipped}")
        except Exception as e:
            print(f"  ERROR: {e}")

    conn.close()

    print(f"\n{'='*45}")
    print(f"All done!")
    print(f"  Total inserted: {total_inserted}")
    print(f"  Total skipped:  {total_skipped}")
    print(f"\nRestart your server and refresh the map.")


if __name__ == "__main__":
    main()