# Boundary files (not committed)

Put **one or more** GeoJSON / GeoPackage / Shapefile files here. The `boundaries`
stage reads every file in this folder, or only the one named by `BOUNDARY_FILE` in
`.env`. Nothing about boundaries is hardcoded in the code.

## How the loader interprets a file

| What | How it is detected (case-insensitive) | Override in `.env` |
| --- | --- | --- |
| Level | a `level` column (`block` / `district`); otherwise `block` if a block-name column exists or the file name contains `block`, `subdist`, `taluk`, `tehsil` or `adm3`; otherwise `district` | add a `level` column |
| Region name | `block`, `block_name`, `sdtname`, `sub_dist`, `tehsil`, `taluk`, `name_3`, … then `name` / `shapeName`, then the district column | `BOUNDARY_NAME_COL` |
| District | `district`, `district_name`, `dtname`, `dist_name`, `name_2`, … | `BOUNDARY_DISTRICT_COL` |
| State | `state`, `st_nm`, `stname`, `state_name`, `name_1`, … | `BOUNDARY_STATE_COL` |

* If **any** block-level features exist for the state, block level is used; otherwise district level.
* If a file has **no state column**, it is assumed to cover only `STATE_NAME` and is
  clipped to the `BBOX_*` box. Files covering all of India **must** have a state column.
* Any CRS is fine; geometries are reprojected to EPSG:4326 and repaired.

## Where to get the files

### Block level (preferred)
1. **TNGIS (Tamil Nadu Geographic Information System)**: <https://tngis.tn.gov.in>.
   The state's official portal publishes administrative layers, including block boundaries.
2. **Bhuvan Panchayat (NRSC/ISRO)**: <https://bhuvan-panchayat3.nrsc.gov.in>.
   Block and Gram Panchayat boundaries (download may need registration).
3. **SHRUG (Development Data Lab)**: <https://www.devdatalab.org/shrug>. Open Census-2011
   sub-district polygons. Note that sub-districts (taluks) are *not* identical to Community
   Development blocks. They are finer than districts and work with this pipeline
   (they are treated as `block` level), but label them accurately in any UI.

### District level (fallback)
1. **geoBoundaries (gbOpen, IND ADM2)**: <https://www.geoboundaries.org>. It's a GeoJSON for all of
   India with no state column, so either clip it to Tamil Nadu first or add a `state` column.
2. **DataMeet maps**: <https://github.com/datameet/maps> (Census-2011 district shapefiles,
   with a state column).
3. **Survey of India**: <https://onlinemaps.surveyofindia.gov.in> (official district boundaries).

## Quick checks before loading

```bash
python -c "import geopandas as g; d=g.read_file('data/raw/boundaries/YOUR_FILE.geojson'); print(d.crs, len(d)); print(d.drop(columns='geometry').head())"
```

Re-running `--stage boundaries` is safe: regions are upserted by a stable `code`
(`tn/<district-slug>/<block-slug>`). Regions that disappear from the files are marked
`active = false` rather than deleted, so their history stays intact.
