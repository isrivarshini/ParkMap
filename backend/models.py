from sqlalchemy import Column, Integer, String, Float, Boolean, DateTime, Text
from sqlalchemy.sql import func
from geoalchemy2 import Geometry
from backend.database import Base


class Spot(Base):
    __tablename__ = "spots"

    id = Column(Integer, primary_key=True, index=True)

    # geometry column — stores lat/lng as PostGIS Point (SRID 4326 = standard GPS)
    geom = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    # spot type: "free" | "paid" | "time_limited"
    spot_type = Column(String(20), nullable=False, default="free")

    # human readable info
    name = Column(String(255), nullable=True)
    address = Column(Text, nullable=True)
    notes = Column(Text, nullable=True)

    # pricing info (null if free)
    hourly_rate = Column(Float, nullable=True)

    # time-limited fields
    free_from = Column(String(10), nullable=True)   # e.g. "18:00"
    free_until = Column(String(10), nullable=True)  # e.g. "08:00"
    free_days = Column(String(50), nullable=True)   # e.g. "Mon-Fri" or "all"

    # capacity
    capacity = Column(Integer, nullable=True)

    # data source: "osm" | "user"
    source = Column(String(20), nullable=False, default="osm")

    # osm reference id (to avoid duplicate ingestion)
    osm_id = Column(String(50), nullable=True, unique=True)

    # user submission fields
    upvotes = Column(Integer, default=0)
    downvotes = Column(Integer, default=0)
    verified = Column(Boolean, default=False)

    # timestamps
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), onupdate=func.now())