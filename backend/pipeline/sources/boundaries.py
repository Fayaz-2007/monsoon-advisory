"""Load block / district boundaries from data/raw/boundaries/ into the ``regions`` table.

Rules:
* Any GeoJSON / GPKG / Shapefile in the folder is a candidate (or BOUNDARY_FILE).
* A ``level`` attribute ('block' | 'district') is used if present; otherwise the
  level is inferred from the file name and the attribute columns.
* Block level wins if any block features exist for the configured state.
* Nothing is hardcoded: attribute columns are auto-detected (override with
  BOUNDARY_NAME_COL / BOUNDARY_DISTRICT_COL / BOUNDARY_STATE_COL).
"""

from __future__ import annotations

import logging
from pathlib import Path

import geopandas as gpd
import pandas as pd
from shapely import make_valid
from shapely.geometry import MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from sqlalchemy import text

from pipeline.config import get_settings
from pipeline.db import get_engine
from pipeline.utils import normalize_name, slugify

log = logging.getLogger(__name__)

SUPPORTED_SUFFIXES = {".geojson", ".json", ".gpkg", ".shp"}
BLOCK_NAME_COLS = ["block", "block_name", "blockname", "block_nam", "blk_name", "cd_block",
                   "cdblock", "sub_dist", "subdistrict", "sub_district", "sdtname", "tehsil",
                   "taluk", "taluka", "name_3"]
DISTRICT_COLS = ["district", "district_name", "districtname", "dist_name", "dtname", "dist_nm",
                 "district_n", "distname", "dist", "name_2"]
STATE_COLS = ["state", "state_name", "statename", "st_nm", "stname", "st_name", "state_ut",
              "state_nm", "name_1"]
GENERIC_NAME_COLS = ["name", "shapename"]
BLOCK_FILE_HINTS = ("block", "subdist", "sub_dist", "sub-dist", "taluk", "tehsil", "adm3")


class BoundaryError(RuntimeError):
    pass


def find_boundary_files() -> list[Path]:
    settings = get_settings()
    if settings.boundary_file:
        path = Path(settings.boundary_file)
        if not path.is_absolute():
            path = settings.boundaries_dir / path
        if not path.exists():
            raise BoundaryError(f"BOUNDARY_FILE not found: {path}")
        return [path]
    files = sorted(p for p in settings.boundaries_dir.glob("*")
                   if p.suffix.lower() in SUPPORTED_SUFFIXES)
    if not files:
        raise BoundaryError(
            f"No boundary files in {settings.boundaries_dir}. "
            "See data/raw/boundaries/README.md for where to download them."
        )
    return files


def _pick_col(columns: list[str], candidates: list[str], override: str | None) -> str | None:
    if override:
        if override not in columns:
            raise BoundaryError(f"Configured column {override!r} not in {columns}")
        return override
    lower = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in lower:
            return lower[cand]
    return None


def standardize(gdf: gpd.GeoDataFrame, source_name: str) -> gpd.GeoDataFrame:
    """Map an arbitrary boundary file to columns: name, district, state, level, geometry."""
    settings = get_settings()
    cols = [c for c in gdf.columns if c != gdf.geometry.name]
    state_col = _pick_col(cols, STATE_COLS, settings.boundary_state_col)
    district_col = _pick_col(cols, DISTRICT_COLS, settings.boundary_district_col)
    block_col = _pick_col(cols, BLOCK_NAME_COLS, None)
    generic_col = _pick_col(cols, GENERIC_NAME_COLS, None)
    lower = {c.lower(): c for c in cols}

    if "level" in lower:
        level = gdf[lower["level"]].astype(str).str.strip().str.lower()
    elif block_col or any(h in source_name.lower() for h in BLOCK_FILE_HINTS):
        level = pd.Series("block", index=gdf.index)
    else:
        level = pd.Series("district", index=gdf.index)

    name_col = settings.boundary_name_col or block_col or generic_col or district_col
    if name_col is None:
        raise BoundaryError(f"{source_name}: cannot find a name column among {cols}")

    out = gpd.GeoDataFrame(
        {
            "name": gdf[name_col].astype(str).str.strip(),
            "district": (gdf[district_col].astype(str).str.strip() if district_col
                         else gdf[name_col].astype(str).str.strip()),
            "state": (gdf[state_col].astype(str).str.strip() if state_col
                      else settings.state_name),
            "level": level.values,
            "source_file": source_name,
        },
        geometry=gdf.geometry.values,
        crs=gdf.crs,
    )
    # A district-level feature's name *is* the district.
    is_district = out["level"] == "district"
    if district_col:
        out.loc[is_district, "name"] = out.loc[is_district, "district"]
    elif (~is_district).any():
        log.warning("%s: block features have no district column; district set to block name",
                    source_name)
    if not state_col:
        log.warning("%s: no state column found - assuming the file covers only %s and "
                    "clipping to the configured bounding box", source_name, settings.state_name)
    bad = ~out["level"].isin(["block", "district"])
    if bad.any():
        raise BoundaryError(f"{source_name}: invalid level values {sorted(out.loc[bad, 'level'].unique())}")
    return out


def _to_multipolygon(geom: BaseGeometry) -> MultiPolygon | None:
    geom = make_valid(geom)
    if isinstance(geom, Polygon):
        return MultiPolygon([geom])
    if isinstance(geom, MultiPolygon):
        return geom
    polys: list[Polygon] = []
    for part in getattr(geom, "geoms", []):
        if isinstance(part, Polygon):
            polys.append(part)
        elif isinstance(part, MultiPolygon):
            polys.extend(part.geoms)
    return MultiPolygon(polys) if polys else None


def filter_state(gdf: gpd.GeoDataFrame, had_state_col: bool) -> gpd.GeoDataFrame:
    settings = get_settings()
    if had_state_col:
        key = normalize_name(settings.state_name)
        gdf = gdf[gdf["state"].map(normalize_name) == key].copy()
        gdf["state"] = settings.state_name
        return gdf
    bbox = box(*settings.bbox)
    return gdf[gdf.geometry.representative_point().within(bbox)].copy()


def prepare_regions(frames: list[gpd.GeoDataFrame]) -> gpd.GeoDataFrame:
    """Pick the level, dissolve duplicates, compute codes and areas."""
    settings = get_settings()
    gdf = gpd.GeoDataFrame(pd.concat(frames, ignore_index=True), crs="EPSG:4326")
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]
    level = "block" if (gdf["level"] == "block").any() else "district"
    gdf = gdf[gdf["level"] == level].copy()
    if gdf.empty:
        raise BoundaryError(f"No features for state {settings.state_name!r} in boundary files")

    def make_code(row: pd.Series) -> str:
        if level == "block":
            return f"{settings.state_code}/{slugify(row['district'])}/{slugify(row['name'])}"
        return f"{settings.state_code}/{slugify(row['district'])}"

    gdf["code"] = gdf.apply(make_code, axis=1)
    gdf["geometry"] = gdf.geometry.apply(make_valid)
    dissolved = gdf.dissolve(by="code", aggfunc="first", as_index=False)
    dissolved["geometry"] = dissolved.geometry.apply(_to_multipolygon)
    dissolved = dissolved[dissolved.geometry.notna()].copy()
    dissolved["area_km2"] = dissolved.to_crs(settings.equal_area_crs).geometry.area / 1e6
    return dissolved[["code", "name", "district", "level", "state", "area_km2",
                      "source_file", "geometry"]]


def load_boundaries() -> tuple[int, str]:
    """Read boundary files and upsert regions. Returns (rows_written, level)."""
    settings = get_settings()
    frames: list[gpd.GeoDataFrame] = []
    for path in find_boundary_files():
        log.info("Reading boundary file %s", path.name)
        raw = gpd.read_file(path)
        if raw.crs is None:
            log.warning("%s has no CRS - assuming EPSG:4326", path.name)
            raw = raw.set_crs("EPSG:4326")
        raw = raw.to_crs("EPSG:4326")
        std = standardize(raw, path.name)
        cols_lower = [c.lower() for c in raw.columns]
        has_state = bool(settings.boundary_state_col) or any(c in cols_lower for c in STATE_COLS)
        std = filter_state(std, has_state)
        log.info("  %s: %d features for %s (%s)", path.name, len(std), settings.state_name,
                 ", ".join(f"{k}={v}" for k, v in std["level"].value_counts().items()))
        if not std.empty:
            frames.append(std)
    if not frames:
        raise BoundaryError(f"No boundary features matched state {settings.state_name!r}")

    regions = prepare_regions(frames)
    level = str(regions["level"].iloc[0])
    rows = [
        {"code": r.code, "name": r.name, "district": r.district, "level": r.level,
         "state": r.state, "area_km2": float(r.area_km2), "source_file": r.source_file,
         "wkt": r.geometry.wkt}
        for r in regions.itertuples(index=False)
    ]
    upsert_sql = text("""
        INSERT INTO regions (code, name, district, level, state, geom, area_km2, active,
                             source_file, updated_at)
        VALUES (:code, :name, :district, :level, :state,
                ST_Multi(ST_CollectionExtract(ST_MakeValid(ST_GeomFromText(:wkt, 4326)), 3)),
                :area_km2, true, :source_file, now())
        ON CONFLICT (code) DO UPDATE SET
            name = EXCLUDED.name, district = EXCLUDED.district, level = EXCLUDED.level,
            state = EXCLUDED.state, geom = EXCLUDED.geom, area_km2 = EXCLUDED.area_km2,
            active = true, source_file = EXCLUDED.source_file, updated_at = now()
    """)
    with get_engine().begin() as conn:
        conn.execute(upsert_sql, rows)
        deactivated = conn.execute(
            text("UPDATE regions SET active = false, updated_at = now() "
                 "WHERE state = :state AND active AND NOT (code = ANY(:codes))"),
            {"state": settings.state_name, "codes": [r["code"] for r in rows]},
        ).rowcount
    if deactivated:
        log.warning("Marked %d previously loaded regions inactive (not in current files)",
                    deactivated)
    log.info("Loaded %d %s-level regions for %s", len(rows), level, settings.state_name)
    return len(rows), level


def load_regions_gdf(active_only: bool = True) -> gpd.GeoDataFrame:
    """Read regions from PostGIS as a GeoDataFrame (id, code, name, district, level, geometry)."""
    settings = get_settings()
    sql = text("SELECT id, code, name, district, level, area_km2, geom FROM regions "
               "WHERE state = :state" + (" AND active" if active_only else "") + " ORDER BY id")
    with get_engine().connect() as conn:
        gdf = gpd.read_postgis(sql, conn, geom_col="geom", params={"state": settings.state_name})
    return gdf.rename_geometry("geometry")
