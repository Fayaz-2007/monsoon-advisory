"""Zonal aggregation on a tiny synthetic 3x3 grid (0.25° cells)."""

from __future__ import annotations

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import box

from pipeline.transform.weights import aggregate_grid, compute_weights, weight_matrix

RES = 0.25
LATS = np.array([10.0, 10.25, 10.5])
LONS = np.array([78.0, 78.25, 78.5])
EA_CRS = "EPSG:7755"


def _cell(lat: float, lon: float) -> tuple[float, float, float, float]:
    h = RES / 2
    return (lon - h, lat - h, lon + h, lat + h)


@pytest.fixture
def regions() -> gpd.GeoDataFrame:
    x0, y0, x1, y1 = _cell(10.0, 78.0)
    # Region 1: exactly cell (10.0, 78.0) plus the western half of (10.0, 78.25).
    r1 = box(x0, y0, x1 + RES / 2, y1)
    # Region 2: a small square fully inside cell (10.5, 78.5).
    cx0, cy0, _, _ = _cell(10.5, 78.5)
    r2 = box(cx0 + 0.05, cy0 + 0.05, cx0 + 0.10, cy0 + 0.10)
    return gpd.GeoDataFrame({"id": [1, 2]}, geometry=[r1, r2], crs="EPSG:4326")


def test_weights_are_area_proportional_and_sum_to_one(regions):
    w = compute_weights(regions, LATS, LONS, RES, EA_CRS)
    assert w.groupby("region_id")["weight"].sum().to_numpy() == pytest.approx([1.0, 1.0])
    r1 = w[w["region_id"] == 1].set_index("lon")["weight"]
    # Full cell vs half cell → 2/3 and 1/3 (equal-area CRS; cells at the same latitude).
    assert r1[78.0] == pytest.approx(2 / 3, rel=1e-3)
    assert r1[78.25] == pytest.approx(1 / 3, rel=1e-3)
    r2 = w[w["region_id"] == 2]
    assert len(r2) == 1 and r2["weight"].iloc[0] == pytest.approx(1.0)
    assert set(w["method"]) == {"area"}


def test_aggregate_weighted_mean_and_nan_renormalisation(regions):
    w = compute_weights(regions, LATS, LONS, RES, EA_CRS)
    wm = weight_matrix(w, LATS, LONS, [1, 2])
    values = np.zeros((2, 3, 3))
    values[:, 0, 0] = 30.0   # cell (10.0, 78.0)
    values[:, 0, 1] = 0.0    # cell (10.0, 78.25)
    values[:, 2, 2] = 7.5    # cell (10.5, 78.5)
    values[1, 0, 1] = np.nan  # day 2: half-cell missing → renormalise onto the full cell
    mean, n_cells = aggregate_grid(values, wm)
    assert mean[0, 0] == pytest.approx(20.0, rel=1e-3)  # 2/3*30 + 1/3*0
    assert mean[1, 0] == pytest.approx(30.0)
    assert mean[0, 1] == pytest.approx(7.5)
    assert n_cells[0].tolist() == [2, 1]
    assert n_cells[1].tolist() == [1, 1]


def test_region_with_all_cells_missing_is_nan(regions):
    w = compute_weights(regions, LATS, LONS, RES, EA_CRS)
    wm = weight_matrix(w, LATS, LONS, [1, 2])
    values = np.full((1, 3, 3), np.nan)
    values[0, 0, 0] = 5.0
    mean, _ = aggregate_grid(values, wm)
    assert mean[0, 0] == pytest.approx(5.0)
    assert np.isnan(mean[0, 1])


def test_valid_mask_excludes_ocean_and_nearest_fallback(regions):
    mask = np.ones((3, 3), dtype=bool)
    mask[0, 1] = False  # (10.0, 78.25) is "ocean"
    mask[2, 2] = False  # region 2's only cell is invalid → nearest fallback
    w = compute_weights(regions, LATS, LONS, RES, EA_CRS, valid_mask=mask)
    r1 = w[w["region_id"] == 1]
    assert r1["lon"].tolist() == [78.0] and r1["weight"].iloc[0] == pytest.approx(1.0)
    r2 = w[w["region_id"] == 2].iloc[0]
    assert r2["method"] == "nearest"
    assert (r2["lat"], r2["lon"]) in {(10.5, 78.25), (10.25, 78.5)}
