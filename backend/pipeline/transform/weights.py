"""Area weights linking grid cells to region polygons.

Each grid point (cell centre) becomes a square cell polygon of side ``res``. The
weight of cell *c* for region *r* is ``area(r ∩ c) / Σ_c area(r ∩ c)``, computed in
an equal-area CRS. Only cells that actually carry data (``valid_mask``) are used,
so coastal regions are not diluted by ocean cells. A region with no valid overlap
(e.g. a tiny coastal block inside an ocean cell) falls back to its nearest valid
cell with weight 1 and ``method='nearest'``.
"""

from __future__ import annotations

import logging

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import box

log = logging.getLogger(__name__)


def grid_cells(lats: np.ndarray, lons: np.ndarray, res: float,
               valid_mask: np.ndarray | None = None) -> gpd.GeoDataFrame:
    """Square cell polygons centred on each (lat, lon); ``valid_mask`` is [nlat, nlon]."""
    lat2d, lon2d = np.meshgrid(lats, lons, indexing="ij")
    keep = np.ones_like(lat2d, dtype=bool) if valid_mask is None else valid_mask.astype(bool)
    la, lo = lat2d[keep], lon2d[keep]
    h = res / 2.0
    geoms = [box(x - h, y - h, x + h, y + h) for y, x in zip(la, lo, strict=True)]
    return gpd.GeoDataFrame({"lat": la.round(4), "lon": lo.round(4)}, geometry=geoms,
                            crs="EPSG:4326")


def compute_weights(regions: gpd.GeoDataFrame, lats: np.ndarray, lons: np.ndarray, res: float,
                    equal_area_crs: str, valid_mask: np.ndarray | None = None) -> pd.DataFrame:
    """Return DataFrame[region_id, lat, lon, weight, method] (weights sum to 1 per region).

    ``regions`` needs columns ``id`` and a geometry in EPSG:4326.
    """
    cells = grid_cells(lats, lons, res, valid_mask)
    if cells.empty:
        raise ValueError("No valid grid cells to build weights from")
    # Intersect in lon/lat (cells are exact rectangles there; projecting first turns
    # shared edges into mismatched chords and creates slivers), then measure areas
    # in the equal-area CRS.
    reg = regions[["id", "geometry"]].to_crs("EPSG:4326")
    inter = gpd.overlay(reg, cells, how="intersection", keep_geom_type=True)
    inter["area"] = inter.to_crs(equal_area_crs).geometry.area
    inter = inter[inter["area"] > 0]
    reg = reg.to_crs(equal_area_crs)
    inter["weight"] = inter["area"] / inter.groupby("id")["area"].transform("sum")
    out = inter[["id", "lat", "lon", "weight"]].rename(columns={"id": "region_id"})
    out["method"] = "area"

    missing = sorted(set(regions["id"]) - set(out["region_id"]))
    if missing:
        centres = gpd.GeoSeries(gpd.points_from_xy(cells["lon"], cells["lat"]),
                                crs="EPSG:4326").to_crs(equal_area_crs)
        extra = []
        for rid in missing:
            pt = reg.loc[reg["id"] == rid].geometry.representative_point().iloc[0]
            j = int(np.argmin(centres.distance(pt).to_numpy()))
            extra.append({"region_id": rid, "lat": cells["lat"].iloc[j],
                          "lon": cells["lon"].iloc[j], "weight": 1.0, "method": "nearest"})
        log.warning("%d region(s) had no valid grid overlap; using nearest cell: %s",
                    len(missing), missing[:20])
        out = pd.concat([out, pd.DataFrame(extra)], ignore_index=True)
    out["region_id"] = out["region_id"].astype(int)
    return out.sort_values(["region_id", "lat", "lon"]).reset_index(drop=True)


def weight_matrix(weights: pd.DataFrame, lats: np.ndarray, lons: np.ndarray,
                  region_ids: list[int]) -> np.ndarray:
    """Dense [n_regions, nlat*nlon] matrix from a weights table."""
    lat_idx = {round(float(v), 4): i for i, v in enumerate(lats)}
    lon_idx = {round(float(v), 4): i for i, v in enumerate(lons)}
    row_idx = {rid: i for i, rid in enumerate(region_ids)}
    w = np.zeros((len(region_ids), len(lats) * len(lons)), dtype=np.float64)
    skipped = 0
    for rid, la, lo, wt in weights[["region_id", "lat", "lon", "weight"]].itertuples(index=False):
        i = row_idx.get(int(rid))
        a, b = lat_idx.get(round(float(la), 4)), lon_idx.get(round(float(lo), 4))
        if i is None or a is None or b is None:
            skipped += 1
            continue
        w[i, a * len(lons) + b] += wt
    if skipped:
        log.debug("weight_matrix: %d weight rows outside the data grid ignored", skipped)
    return w


def aggregate_grid(values: np.ndarray, w: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Area-weighted zonal mean of gridded values.

    Args:
        values: [time, nlat, nlon] with NaN for missing cells.
        w: [n_regions, nlat*nlon] weights (from :func:`weight_matrix`).

    Returns:
        (means [time, n_regions], n_valid_cells [time, n_regions]). Weights are
        renormalised over the cells that are valid on each day; a region with no
        valid cell on a day gets NaN.
    """
    x = values.reshape(values.shape[0], -1).astype(np.float64)
    valid = ~np.isnan(x)
    num = np.where(valid, x, 0.0) @ w.T
    den = valid.astype(np.float64) @ w.T
    with np.errstate(invalid="ignore", divide="ignore"):
        mean = np.where(den > 1e-9, num / den, np.nan)
    n_cells = valid.astype(np.int32) @ (w > 0).T.astype(np.int32)
    return mean, n_cells
