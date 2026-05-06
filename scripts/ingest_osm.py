"""
OSM Top-20 US Cities Ingestion Script

Usage:
    python scripts/ingest_osm.py                      # all 20 cities
    python scripts/ingest_osm.py --city nyc           # single city
    python scripts/ingest_osm.py --city nyc,la,chi    # multiple
    python scripts/ingest_osm.py --list               # show all city keys
"""

import urllib.request
import urllib.parse
import json
import psycopg2
import os
import sys
import argparse
import time
from dotenv import load_dotenv

load_dotenv()

CITIES = {
    "mv":        {"name": "Mountain View",  "slug": "mountain_view",  "bbox": (37.3575,-122.1173,37.4305,-122.0073), "center": (37.3861,-122.0840), "zoom": 13},
    "sf":        {"name": "San Francisco",  "slug": "san_francisco",  "bbox": (37.6879,-122.5135,37.8324,-122.3531), "center": (37.7749,-122.4194), "zoom": 12},
    "la":        {"name": "Los Angeles",    "slug": "los_angeles",    "bbox": (33.7037,-118.6682,34.3373,-118.1553), "center": (34.0522,-118.2437), "zoom": 11},
    "seattle":   {"name": "Seattle",        "slug": "seattle",        "bbox": (47.4810,-122.4596,47.7341,-122.2244), "center": (47.6062,-122.3321), "zoom": 12},
    "nyc":       {"name": "New York City",  "slug": "new_york_city",  "bbox": (40.4774,-74.2591,40.9176,-73.7004), "center": (40.7128,-74.0060),  "zoom": 11},
    "chi":       {"name": "Chicago",        "slug": "chicago",        "bbox": (41.6445,-87.9401,42.0230,-87.5240), "center": (41.8781,-87.6298),  "zoom": 11},
    "hou":       {"name": "Houston",        "slug": "houston",        "bbox": (29.5238,-95.7835,30.1107,-95.0138), "center": (29.7604,-95.3698),  "zoom": 11},
    "phx":       {"name": "Phoenix",        "slug": "phoenix",        "bbox": (33.2903,-112.3236,33.9137,-111.9256),"center": (33.4484,-112.0740), "zoom": 11},
    "phi":       {"name": "Philadelphia",   "slug": "philadelphia",   "bbox": (39.8670,-75.2803,40.1379,-74.9558), "center": (39.9526,-75.1652),  "zoom": 12},
    "sat":       {"name": "San Antonio",    "slug": "san_antonio",    "bbox": (29.2098,-98.8084,29.7700,-98.2346), "center": (29.4241,-98.4936),  "zoom": 11},
    "sd":        {"name": "San Diego",      "slug": "san_diego",      "bbox": (32.5343,-117.2823,33.1141,-116.9066),"center": (32.7157,-117.1611), "zoom": 12},
    "dal":       {"name": "Dallas",         "slug": "dallas",         "bbox": (32.6177,-97.0641,33.0237,-96.5597), "center": (32.7767,-96.7970),  "zoom": 11},
    "sjc":       {"name": "San Jose",       "slug": "san_jose",       "bbox": (37.1255,-122.0429,37.4691,-121.5887),"center": (37.3382,-121.8863), "zoom": 12},
    "aus":       {"name": "Austin",         "slug": "austin",         "bbox": (30.0986,-97.9383,30.5168,-97.5688), "center": (30.2672,-97.7431),  "zoom": 12},
    "jax":       {"name": "Jacksonville",   "slug": "jacksonville",   "bbox": (30.1038,-82.0549,30.7378,-81.3924), "center": (30.3322,-81.6557),  "zoom": 11},
    "col":       {"name": "Columbus",       "slug": "columbus",       "bbox": (39.8620,-83.2001,40.1572,-82.7715), "center": (39.9612,-82.9988),  "zoom": 12},
    "ind":       {"name": "Indianapolis",   "slug": "indianapolis",   "bbox": (39.6330,-86.3282,39.9270,-85.9365), "center": (39.7684,-86.1581),  "zoom": 12},
    "den":       {"name": "Denver",         "slug": "denver",         "bbox": (39.6143,-105.1099,39.9142,-104.6001),"center": (39.7392,-104.9903), "zoom": 12},
    "por":       {"name": "Portland",       "slug": "portland",       "bbox": (45.4325,-122.8367,45.6523,-122.4718),"center": (45.5051,-122.6750), "zoom": 12},
    "las":       {"name": "Las Vegas",      "slug": "las_vegas",      "bbox": (35.9309,-115.4228,36.4024,-114.9273),"center": (36.1699,-115.1398), "zoom": 12},
}

OVERPASS_URL = "https://overpass-api.de/api/interpreter"


def build_query(bbox):
    s, w, n, e = bbox
    return f"""
[out:json][timeout:120];
(
  node["amenity"="parking"]({s},{w},{n},{e});
  way["amenity"="parking"]({s},{w},{n},{e});
);
out center;
"""


def fetch_osm_data(city_key, retries=3):
    city = CITIES[city_key]
    for attempt in range(retries):
        try:
            print(f"  Fetching OSM data (attempt {attempt+1})...")
            query = build_query(city["bbox"])
            req = urllib.request.Request(
                OVERPASS_URL,
                data=urllib.parse.urlencode({"data": query}).encode(),
                headers={"User-Agent": "parkspot-app/1.0"}
            )
            response = urllib.request.urlopen(req, timeout=150)
            data = json.loads(response.read())
            elements = data["elements"]
            print(f"  Raw results: {len(elements)} elements")
            return elements
        except Exception as e:
            print(f"  Attempt {attempt+1} failed: {e}")
            if attempt < retries - 1:
                wait = (attempt + 1) * 10
                print(f"  Waiting {wait}s before retry...")
                time.sleep(wait)
    return []


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


def ensure_schema(conn):
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

    cur.execute("""
        ALTER TABLE spots ADD COLUMN IF NOT EXISTS city_slug VARCHAR(50) DEFAULT 'mountain_view';
    """)

    # spatial index for viewport queries
    cur.execute("""
        CREATE INDEX IF NOT EXISTS spots_geom_idx ON spots USING GIST(geom);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS spots_city_idx ON spots(city_slug);
    """)
    cur.execute("""
        CREATE INDEX IF NOT EXISTS spots_type_idx ON spots(spot_type);
    """)

    # upsert all cities into cities table
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
    print("  Schema and indexes ready.")


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
    parser.add_argument("--city", type=str, default=None)
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable city keys:")
        for key, city in CITIES.items():
            print(f"  {key:<10} {city['name']}")
        return

    if args.city:
        keys = [k.strip() for k in args.city.split(",")]
        invalid = [k for k in keys if k not in CITIES]
        if invalid:
            print(f"Unknown: {invalid}. Run --list to see valid keys.")
            sys.exit(1)
    else:
        keys = list(CITIES.keys())

    db_url = os.getenv("DATABASE_URL_SYNC")
    conn = psycopg2.connect(db_url)

    print("Setting up schema...")
    ensure_schema(conn)

    total_inserted = total_skipped = 0
    failed = []

    for i, key in enumerate(keys):
        city = CITIES[key]
        print(f"\n[{i+1}/{len(keys)}] {city['name']}")
        print("-" * 40)

        elements = fetch_osm_data(key)
        if not elements:
            print(f"  No data returned — skipping.")
            failed.append(key)
            continue

        inserted, skipped = ingest_city(key, elements, conn)
        total_inserted += inserted
        total_skipped += skipped
        print(f"  Done — inserted: {inserted}, skipped: {skipped}")

        # be polite to Overpass — wait between cities
        if i < len(keys) - 1:
            print("  Waiting 5s before next city...")
            time.sleep(5)

    conn.close()

    print(f"\n{'='*40}")
    print(f"Ingestion complete!")
    print(f"  Total inserted: {total_inserted:,}")
    print(f"  Total skipped:  {total_skipped:,}")
    if failed:
        print(f"  Failed cities:  {failed} (re-run with --city {','.join(failed)})")
    print(f"\nRestart server: uvicorn backend.main:app --reload")


if __name__ == "__main__":
    main()