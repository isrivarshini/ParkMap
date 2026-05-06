# ParkSpot 🅿️

An interactive 3D parking map for the United States — built with FastAPI, PostgreSQL + PostGIS, and deck.gl. Find free, paid, and time-limited parking spots across 20 major US cities. Seeded with real OpenStreetMap data and crowd-sourced with anonymous user submissions.

![ParkSpot dark mode map showing Mountain View parking spots](https://via.placeholder.com/900x500/0f0f14/378ADD?text=ParkSpot+%E2%80%94+Interactive+US+Parking+Map)

---

## Features

- **3D interactive map** powered by deck.gl and MapLibre GL — 45° pitch, smooth pan and zoom
- **Viewport-based loading** — only fetches spots visible on screen, handles millions of records without slowdown
- **20 US cities** seeded from OpenStreetMap via Overpass API — NYC, SF, LA, Chicago, Seattle, Denver, and more
- **Color-coded spot types** — green for free, amber for time-limited, red for paid
- **Hex density view** — zooms out to a 3D heatmap showing parking density across the city
- **Filter by type** — toggle between all, free, paid, and time-limited spots with live counts
- **Geolocation** — one-click "find spots near me" with a 500m radius ring
- **Address search** — powered by Nominatim (free, no API key required)
- **Anonymous submissions** — anyone can drop a pin and add a new spot
- **Upvote and downvote** spots directly from the hover tooltip
- **Light and dark theme** with a single toggle
- **Map tilt slider** — go from flat 2D to full 3D pitch

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.11, FastAPI, uvicorn |
| Database | PostgreSQL 17 + PostGIS 3.6 |
| ORM | SQLAlchemy (async) + GeoAlchemy2 |
| Map | deck.gl 9, MapLibre GL |
| Basemap tiles | CARTO (free, no API key) |
| Geocoding | Nominatim / OpenStreetMap |
| Data source | OpenStreetMap via Overpass API |
| Frontend | Vanilla HTML + JavaScript |

---

## Project Structure

```
parkspot/
├── backend/
│   ├── __init__.py
│   ├── main.py          # FastAPI app entry point
│   ├── database.py      # async PostgreSQL connection
│   ├── models.py        # SQLAlchemy models (spots, cities)
│   └── routes.py        # API endpoints
├── scripts/
│   └── ingest_osm.py    # OSM data ingestion script
├── static/
│   └── index.html       # full frontend — map, filters, UI
├── .env                 # local environment variables
├── requirements.txt
└── README.md
```

---

## Prerequisites

- macOS with Homebrew
- Python 3.11 (via pyenv)
- PostgreSQL 17 + PostGIS 3.6

---

## Local Setup

**1. Clone the repo**

```bash
git clone https://github.com/isrivarshini/parkspot.git
cd parkspot
```

**2. Create and activate a virtual environment**

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. Set up PostgreSQL and PostGIS**

```bash
brew services start postgresql@17
createdb parkspot
psql parkspot -c "CREATE EXTENSION postgis;"
```

**4. Create your `.env` file**

```bash
cat > .env << 'EOF'
DATABASE_URL=postgresql+asyncpg://YOUR_MAC_USERNAME@localhost:5432/parkspot
DATABASE_URL_SYNC=postgresql://YOUR_MAC_USERNAME@localhost:5432/parkspot
EOF
```

Replace `YOUR_MAC_USERNAME` with your actual Mac username (run `whoami` to check).

**5. Create the database schema**

```bash
psql parkspot << 'EOF'
CREATE TABLE IF NOT EXISTS spots (
    id SERIAL PRIMARY KEY,
    geom GEOMETRY(POINT, 4326) NOT NULL,
    spot_type VARCHAR(20) NOT NULL DEFAULT 'free',
    name VARCHAR(255),
    address TEXT,
    notes TEXT,
    hourly_rate FLOAT,
    free_from VARCHAR(10),
    free_until VARCHAR(10),
    free_days VARCHAR(50),
    capacity INTEGER,
    source VARCHAR(20) NOT NULL DEFAULT 'osm',
    osm_id VARCHAR(50) UNIQUE,
    city_slug VARCHAR(50) DEFAULT 'mountain_view',
    upvotes INTEGER DEFAULT 0,
    downvotes INTEGER DEFAULT 0,
    verified BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS spots_geom_idx ON spots USING GIST(geom);
CREATE INDEX IF NOT EXISTS spots_city_idx ON spots(city_slug);
CREATE INDEX IF NOT EXISTS spots_type_idx ON spots(spot_type);
EOF
```

**6. Ingest parking data from OpenStreetMap**

```bash
# single city (recommended for first run)
python scripts/ingest_osm.py --city mv

# multiple cities
python scripts/ingest_osm.py --city mv,sf,nyc,chi,den

# all 20 cities (takes ~30 minutes)
python scripts/ingest_osm.py

# see all available city keys
python scripts/ingest_osm.py --list
```

**7. Start the server**

```bash
uvicorn backend.main:app --reload
```

Open `http://localhost:8000` in your browser.

---

## Available Cities

| Key | City |
|---|---|
| `mv` | Mountain View |
| `sf` | San Francisco |
| `la` | Los Angeles |
| `nyc` | New York City |
| `chi` | Chicago |
| `hou` | Houston |
| `phx` | Phoenix |
| `phi` | Philadelphia |
| `sat` | San Antonio |
| `sd` | San Diego |
| `dal` | Dallas |
| `sjc` | San Jose |
| `aus` | Austin |
| `jax` | Jacksonville |
| `col` | Columbus |
| `ind` | Indianapolis |
| `den` | Denver |
| `por` | Portland |
| `las` | Las Vegas |
| `seattle` | Seattle |

---

## API Endpoints

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/api/spots/viewport` | Spots within a bounding box (viewport query) |
| `GET` | `/api/spots` | Spots by city or radius |
| `POST` | `/api/spots` | Submit a new spot anonymously |
| `GET` | `/api/cities` | List all available cities |
| `POST` | `/api/spots/{id}/upvote` | Upvote a spot |
| `POST` | `/api/spots/{id}/downvote` | Downvote a spot |
| `GET` | `/health` | Health check |
| `GET` | `/docs` | Interactive Swagger UI |

### Viewport query example

```bash
curl "http://localhost:8000/api/spots/viewport?min_lng=-122.12&min_lat=37.35&max_lng=-122.00&max_lat=37.42&limit=500"
```

### Filter by type

```bash
curl "http://localhost:8000/api/spots?city=san_francisco&spot_type=free&limit=100"
```

---

## Data Sources

- **OpenStreetMap** — primary data source, queried via the Overpass API using `amenity=parking` tags
- **User submissions** — anonymous crowd-sourced spots stored with `source='user'` flag
- **Spot types** are inferred from OSM tags: `fee=yes` → paid, `maxstay` or `fee:conditional` → time-limited, everything else → free

---

## How Viewport Loading Works

Instead of loading all spots at startup, the app queries only what's visible on screen:

1. On every pan or zoom, the frontend calculates the map's bounding box
2. It calls `GET /api/spots/viewport` with `min_lng`, `min_lat`, `max_lng`, `max_lat`
3. PostGIS uses a spatial index (`GIST`) to return matching spots in milliseconds
4. The map re-renders with the new data

This approach handles millions of spots with no performance degradation.

---

## Contributing

This is a local-first development project. To add a spot:

1. Click **"+ Add a spot"** in the panel
2. Click anywhere on the map to drop a pin
3. Fill in the type, notes, and any time/rate info
4. Hit Submit — your spot appears on the map immediately

---

## License

MIT