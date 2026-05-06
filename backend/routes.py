from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from backend.database import get_db
from typing import Optional

router = APIRouter()


def make_feature(row):
    return {
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [row["lng"], row["lat"]]},
        "properties": {
            "id": row["id"],
            "spot_type": row["spot_type"],
            "name": row["name"],
            "address": row.get("address"),
            "notes": row.get("notes"),
            "hourly_rate": row.get("hourly_rate"),
            "free_from": row.get("free_from"),
            "free_until": row.get("free_until"),
            "free_days": row.get("free_days"),
            "capacity": row.get("capacity"),
            "source": row["source"],
            "upvotes": row.get("upvotes", 0),
            "downvotes": row.get("downvotes", 0),
            "verified": row.get("verified", False),
            "city_slug": row.get("city_slug", ""),
        }
    }


@router.get("/api/cities")
async def get_cities(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("""
            SELECT slug, name, center_lat, center_lng, default_zoom
            FROM cities ORDER BY name
        """))
        rows = result.mappings().all()
        return {"cities": [dict(r) for r in rows]}
    except Exception:
        return {"cities": [
            {"slug": "mountain_view", "name": "Mountain View",
             "center_lat": 37.3861, "center_lng": -122.0840, "default_zoom": 13}
        ]}


@router.get("/api/spots/viewport")
async def get_spots_viewport(
    db: AsyncSession = Depends(get_db),
    min_lng: float = Query(..., description="West boundary"),
    min_lat: float = Query(..., description="South boundary"),
    max_lng: float = Query(..., description="East boundary"),
    max_lat: float = Query(..., description="North boundary"),
    spot_type: Optional[str] = Query(None),
    limit: Optional[int] = Query(1000),
):
    """
    Return spots within a bounding box (viewport).
    Called every time the map pans or zooms.
    Uses PostGIS spatial index for fast queries.
    """
    filters = ["""
        geom && ST_MakeEnvelope(:min_lng, :min_lat, :max_lng, :max_lat, 4326)
    """]
    params = {
        "min_lng": min_lng, "min_lat": min_lat,
        "max_lng": max_lng, "max_lat": max_lat,
        "limit": limit,
    }

    if spot_type and spot_type != "all":
        filters.append("spot_type = :spot_type")
        params["spot_type"] = spot_type

    where_clause = " AND ".join(filters)

    query = text(f"""
        SELECT id, spot_type, name, address, notes, hourly_rate,
               free_from, free_until, free_days, capacity, source,
               upvotes, downvotes, verified,
               COALESCE(city_slug, 'mountain_view') as city_slug,
               ST_X(geom::geometry) AS lng,
               ST_Y(geom::geometry) AS lat
        FROM spots
        WHERE {where_clause}
        LIMIT :limit
    """)

    result = await db.execute(query, params)
    rows = result.mappings().all()
    features = [make_feature(row) for row in rows]

    return {
        "type": "FeatureCollection",
        "count": len(features),
        "features": features,
        "viewport": {"min_lng": min_lng, "min_lat": min_lat, "max_lng": max_lng, "max_lat": max_lat}
    }


@router.get("/api/spots")
async def get_spots(
    db: AsyncSession = Depends(get_db),
    spot_type: Optional[str] = Query(None),
    lat: Optional[float] = Query(None),
    lng: Optional[float] = Query(None),
    radius: Optional[int] = Query(500),
    city: Optional[str] = Query(None),
    limit: Optional[int] = Query(500),
):
    filters = ["1=1"]
    params: dict = {"limit": limit}

    if spot_type and spot_type != "all":
        filters.append("spot_type = :spot_type")
        params["spot_type"] = spot_type

    if city:
        filters.append("city_slug = :city")
        params["city"] = city

    if lat is not None and lng is not None:
        filters.append(
            "ST_DWithin(geom::geography, ST_MakePoint(:lng, :lat)::geography, :radius)"
        )
        params["lat"] = lat
        params["lng"] = lng
        params["radius"] = radius

    where_clause = " AND ".join(filters)

    query = text(f"""
        SELECT id, spot_type, name, address, notes, hourly_rate,
               free_from, free_until, free_days, capacity, source,
               upvotes, downvotes, verified,
               COALESCE(city_slug, 'mountain_view') as city_slug,
               ST_X(geom::geometry) AS lng,
               ST_Y(geom::geometry) AS lat
        FROM spots
        WHERE {where_clause}
        LIMIT :limit
    """)

    result = await db.execute(query, params)
    rows = result.mappings().all()
    features = [make_feature(row) for row in rows]

    return {"type": "FeatureCollection", "count": len(features), "features": features}


@router.post("/api/spots")
async def create_spot(
    lat: float, lng: float, spot_type: str,
    db: AsyncSession = Depends(get_db),
    name: Optional[str] = None,
    address: Optional[str] = None,
    notes: Optional[str] = None,
    hourly_rate: Optional[float] = None,
    free_from: Optional[str] = None,
    free_until: Optional[str] = None,
    capacity: Optional[int] = None,
    city: Optional[str] = "mountain_view",
):
    query = text("""
        INSERT INTO spots
            (geom, spot_type, name, address, notes, hourly_rate,
             free_from, free_until, source, city_slug)
        VALUES
            (ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
             :spot_type, :name, :address, :notes, :hourly_rate,
             :free_from, :free_until, 'user', :city)
        RETURNING id
    """)
    result = await db.execute(query, {
        "lng": lng, "lat": lat, "spot_type": spot_type,
        "name": name, "address": address, "notes": notes,
        "hourly_rate": hourly_rate, "free_from": free_from,
        "free_until": free_until, "city": city,
    })
    await db.commit()
    return {"success": True, "id": result.scalar(), "message": "Spot added!"}


@router.post("/api/spots/{spot_id}/upvote")
async def upvote_spot(spot_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("UPDATE spots SET upvotes = upvotes + 1 WHERE id = :id"), {"id": spot_id}
    )
    await db.commit()
    return {"success": True}


@router.post("/api/spots/{spot_id}/downvote")
async def downvote_spot(spot_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("UPDATE spots SET downvotes = downvotes + 1 WHERE id = :id"), {"id": spot_id}
    )
    await db.commit()
    return {"success": True}