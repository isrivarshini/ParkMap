from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from backend.database import get_db
from typing import Optional

router = APIRouter()


@router.get("/api/spots")
async def get_spots(
    db: AsyncSession = Depends(get_db),
    spot_type: Optional[str] = Query(None, description="free | paid | time_limited | all"),
    lat: Optional[float] = Query(None, description="center latitude for radius search"),
    lng: Optional[float] = Query(None, description="center longitude for radius search"),
    radius: Optional[int] = Query(1000, description="search radius in meters"),
    limit: Optional[int] = Query(500, description="max spots to return"),
):
    """
    Return parking spots as GeoJSON FeatureCollection.
    Supports filtering by type and radius search around a coordinate.
    """

    filters = ["1=1"]
    params: dict = {"limit": limit}

    if spot_type and spot_type != "all":
        filters.append("spot_type = :spot_type")
        params["spot_type"] = spot_type

    if lat is not None and lng is not None:
        filters.append(
            "ST_DWithin(geom::geography, ST_MakePoint(:lng, :lat)::geography, :radius)"
        )
        params["lat"] = lat
        params["lng"] = lng
        params["radius"] = radius

    where_clause = " AND ".join(filters)

    query = text(f"""
        SELECT
            id,
            spot_type,
            name,
            address,
            notes,
            hourly_rate,
            free_from,
            free_until,
            free_days,
            capacity,
            source,
            upvotes,
            downvotes,
            verified,
            ST_X(geom::geometry) AS lng,
            ST_Y(geom::geometry) AS lat
        FROM spots
        WHERE {where_clause}
        LIMIT :limit
    """)

    result = await db.execute(query, params)
    rows = result.mappings().all()

    features = []
    for row in rows:
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [row["lng"], row["lat"]]
            },
            "properties": {
                "id": row["id"],
                "spot_type": row["spot_type"],
                "name": row["name"],
                "address": row["address"],
                "notes": row["notes"],
                "hourly_rate": row["hourly_rate"],
                "free_from": row["free_from"],
                "free_until": row["free_until"],
                "free_days": row["free_days"],
                "capacity": row["capacity"],
                "source": row["source"],
                "upvotes": row["upvotes"],
                "downvotes": row["downvotes"],
                "verified": row["verified"],
            }
        })

    return {
        "type": "FeatureCollection",
        "count": len(features),
        "features": features
    }


@router.post("/api/spots")
async def create_spot(
    spot_type: str,
    lat: float,
    lng: float,
    db: AsyncSession = Depends(get_db),
    name: Optional[str] = None,
    address: Optional[str] = None,
    notes: Optional[str] = None,
    hourly_rate: Optional[float] = None,
    free_from: Optional[str] = None,
    free_until: Optional[str] = None,
    capacity: Optional[int] = None,
):
    """
    Anonymous user submission — add a new parking spot.
    """
    query = text("""
        INSERT INTO spots
            (geom, spot_type, name, address, notes, hourly_rate,
             free_from, free_until, source)
        VALUES
            (ST_SetSRID(ST_MakePoint(:lng, :lat), 4326),
             :spot_type, :name, :address, :notes, :hourly_rate,
             :free_from, :free_until, 'user')
        RETURNING id
    """)

    result = await db.execute(query, {
        "lng": lng, "lat": lat, "spot_type": spot_type,
        "name": name, "address": address, "notes": notes,
        "hourly_rate": hourly_rate, "free_from": free_from,
        "free_until": free_until,
    })
    await db.commit()
    new_id = result.scalar()

    return {"success": True, "id": new_id, "message": "Spot added — thanks for contributing!"}


@router.post("/api/spots/{spot_id}/upvote")
async def upvote_spot(spot_id: int, db: AsyncSession = Depends(get_db)):
    await db.execute(
        text("UPDATE spots SET upvotes = upvotes + 1 WHERE id = :id"),
        {"id": spot_id}
    )
    await db.commit()
    return {"success": True}