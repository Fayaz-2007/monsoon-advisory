# Hyperlocal Monsoon Onset & Break Prediction System (Block/Village Scale)

Smart India Hackathon 2026. The system predicts monsoon onset, false onset, dry spells, heavy
rain and revival at block level, 1–4 weeks ahead, and turns those forecasts into crop advisories for farmers.

| # | Segment | Folder | Status |
| --- | --- | --- | --- |
| 1 | **Data pipeline** | `backend/pipeline/` | ✅ built |
| 2 | ML models | `backend/ml/` | placeholder |
| 3 | Hazard detection | `backend/hazards/` | placeholder |
| 4 | Advisory engine | `backend/advisory/` | placeholder |
| 5 | Backend API | `backend/app/` | placeholder |
| 6 | Frontend | `frontend/` | placeholder |
| 7 | Delivery (SMS/IVR) | `backend/delivery/` | placeholder |

Demo scope: **Tamil Nadu** (block level where boundaries are available, else district). The code is
state-agnostic: adding a state means editing only `backend/.env` and adding boundary files.

```
monsoon-advisory/
├── backend/
│   ├── pipeline/        Segment 1 (see backend/pipeline/README.md)
│   ├── app/ ml/ hazards/ advisory/ delivery/   placeholders
│   ├── data/raw/        downloads + seed files (git-ignored except seeds)
│   ├── data/processed/  quality report, logs (git-ignored)
│   ├── tests/
│   ├── requirements.txt
│   └── .env.example
├── frontend/            placeholder
├── docs/contracts/      segment1_output.md (features_daily contract for Segment 2)
├── setup_db.bat (+ .ps1)   one-click native PostgreSQL + PostGIS setup (Windows, no admin)
├── start_db.bat / stop_db.bat   native PostgreSQL control (Windows)
├── .pgdata/             local PostgreSQL cluster (git-ignored)
└── docker-compose.yml   optional alternative: PostgreSQL 16 + PostGIS 3.4
```

## Setup: native Windows (primary, no Docker, no admin rights)

This is exactly how the dev machine was set up on 2026-09-29. Nothing needs admin/UAC:
PostgreSQL runs from a portable folder and stores its data inside the repo.

| Piece | Location |
| --- | --- |
| PostgreSQL 16.15 binaries (EDB zip) + PostGIS 3.6.2 (OSGeo bundle zip) | `F:\AGRI-VARSHA\tools\pgsql\` (next to the repo, *outside* git) |
| Database cluster (data folder) | `monsoon-advisory\.pgdata\` (git-ignored), log in `.pgdata\server.log` |
| Server | `localhost:5432` only (not exposed on the network) |
| Database / app user | `monsoon` / `monsoon_app` (password in `backend\.env`, git-ignored) |
| Python | 3.11 venv in `backend\.venv\` (all packages from prebuilt Windows wheels) |

### Daily use

```bat
cd F:\AGRI-VARSHA\monsoon-advisory
start_db.bat                                  & rem starts PostgreSQL; adds psql to PATH in this window
cd backend
.venv\Scripts\activate
python -m pipeline.run --stage daily          & rem bring data up to yesterday
cd ..
stop_db.bat                                   & rem optional: stop PostgreSQL when done
```

`start_db.bat` / `stop_db.bat` look for the binaries in `..\tools\pgsql\bin`; if you move them,
`set PGBIN=C:\path\to\pgsql\bin` first.

### One-time setup on a new Windows machine (one click, no admin)

1. Clone the repo, for example to `F:\AGRI-VARSHA\monsoon-advisory`.
2. Double-click **`setup_db.bat`** (or run it from cmd). In about 1–2 minutes it:
   - downloads PostgreSQL 16.15 (EDB portable zip, ~317 MB) and PostGIS 3.6.2 (OSGeo bundle,
     ~118 MB, MD5-verified) into `..\tools\downloads\`
   - extracts them to `..\tools\pgsql\` and merges in PostGIS without overwriting PostgreSQL files
   - creates the cluster in `.pgdata\` (localhost only, scram-sha-256, random passwords)
   - starts it, then creates role `monsoon_app`, database `monsoon` and the `postgis` extension
   - writes `backend\.env` from `.env.example` with `DATABASE_URL` and `PG_SUPERUSER_PASSWORD`
     (an existing `.env` is backed up to `.env.bak`, and only those two lines change)
   - connects as `monsoon_app` and prints `postgis_full_version()`
3. Python environment:

```bat
cd backend
py -3.11 -m venv .venv
.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pytest
```

Re-running `setup_db.bat` is safe: cached downloads, the extracted binaries and the existing
cluster are reused. Options: `setup_db.bat -Port 5440 -DataDir D:\pg\data -ToolsDir D:\pg\tools
-EnvFile D:\pg\.env`. If you pick another port, `set PGPORT=5440` before `start_db.bat`.

<details><summary>Manual equivalent (what setup_db does)</summary>

```bat
mkdir F:\AGRI-VARSHA\tools && cd /d F:\AGRI-VARSHA\tools
curl -L -o pg.zip https://get.enterprisedb.com/postgresql/postgresql-16.15-1-windows-x64-binaries.zip
curl -L -o postgis.zip https://download.osgeo.org/postgis/windows/pg16/postgis-bundle-pg16-3.6.2x64.zip
%SystemRoot%\System32\tar.exe -xf pg.zip
%SystemRoot%\System32\tar.exe -xf postgis.zip
robocopy postgis-bundle-pg16-3.6.2x64 pgsql /E /XC /XN /XO
cd /d F:\AGRI-VARSHA\monsoon-advisory
..\tools\pgsql\bin\initdb.exe -D .pgdata -U postgres -W -A scram-sha-256 -E UTF8 --locale=C
start_db.bat
psql -h localhost -U postgres -c "CREATE ROLE monsoon_app LOGIN PASSWORD 'APP_PASSWORD';"
psql -h localhost -U postgres -c "CREATE DATABASE monsoon OWNER monsoon_app ENCODING 'UTF8';"
psql -h localhost -U postgres -d monsoon -c "CREATE EXTENSION postgis;"
rem then set DATABASE_URL in backend\.env
```

Use `%SystemRoot%\System32\tar.exe` explicitly: if Git for Windows' `usr\bin` is on PATH, plain
`tar` is GNU tar, which cannot extract to `C:\...` paths.
</details>

Why not the regular installers? The EDB/Stack Builder installers need admin rights, `winget`
was not available, and conda-forge has **no Windows build of PostGIS**, so the portable-zip route
is the only one that works without elevation. If you do have admin rights, the normal EDB installer
plus Stack Builder → Spatial Extensions → PostGIS for PG16 also works; just point `DATABASE_URL` at it.

### Optional: Docker instead

`docker-compose.yml` is kept as an alternative (PostGIS 16-3.4 on host port **5433**, user/password
`monsoon`/`monsoon`). If you use it, set
`DATABASE_URL=postgresql+psycopg2://monsoon:monsoon@localhost:5433/monsoon`. The pipeline itself has
no Docker assumptions; it only reads `DATABASE_URL`.

### Boundaries

Put a Tamil Nadu block-level (or district-level) GeoJSON/GPKG/SHP file in
`backend/data/raw/boundaries/`. See [its README](backend/data/raw/boundaries/README.md) for sources.
The dev database currently uses `tn_districts_geoboundaries_adm2.geojson` (38 districts,
geoBoundaries gbOpen IND ADM2, ODbL, filtered to Tamil Nadu).

## Running the pipeline

All commands run from `backend/` with the virtualenv active.

```bash
# Everything, full history. First run: ~10 min of IMD downloads (~830 MB); after that
# the district-level run takes under a minute.
python -m pipeline.run --stage all --start 1991-01-01 --end 2025-12-31

# Or stage by stage
python -m pipeline.run --stage boundaries
python -m pipeline.run --stage cropcal
python -m pipeline.run --stage indices
python -m pipeline.run --stage rainfall    --start 1991-01-01 --end 2025-12-31
python -m pipeline.run --stage era5        --start 2015-01-01 --end 2025-12-31   # optional
python -m pipeline.run --stage aggregate   --start 1991-01-01 --end 2025-12-31
python -m pipeline.run --stage climatology
python -m pipeline.run --stage features    --start 1991-01-01 --end 2025-12-31
python -m pipeline.run --stage quality     --start 1991-01-01 --end 2025-12-31

# Bring data up to yesterday using IMD real-time data (scheduler entry point)
python -m pipeline.run --stage daily
```

Every run ends with a summary table. The quality report is written to
`backend/data/processed/quality_report.md`, and a full log to `backend/data/processed/pipeline.log`.

Segment 2 usage:

```python
from pipeline import load_features
df = load_features(start="2015-01-01", end="2025-12-31")
```

## Data sources

| Data | Source | Notes |
| --- | --- | --- |
| Daily rainfall 0.25° | IMD Pune gridded data via [`imdlib`](https://github.com/iamsaswata/imdlib) | final data to 2025; real-time provisional grid for 2026+ |
| ENSO | NOAA CPC ONI `oni.ascii.txt` | monthly, forward-filled to daily |
| IOD | NOAA PSL `dmi.had.long.data` | monthly, forward-filled to daily |
| MJO | BoM `rmm.74toRealtime.txt` (ends 2024-02-24) + NOAA PSL ROMI (real-time) | see the contract for the RMM→ROMI switch |
| ERA5 (optional) | Copernicus CDS | u/v 850 hPa, TCWV, OLR proxy |
| Boundaries | user-supplied (TNGIS / Bhuvan / SHRUG / geoBoundaries / DataMeet) | never hardcoded |
| Crop calendar | `backend/data/raw/crop_calendar_tn.csv` | **SAMPLE**, verify with TNAU / Agri Dept |

All URLs are configurable in `backend/.env`.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| `Cannot connect to the database` | Run `start_db.bat` from the repo root, then check with `pg_isready -h localhost -p 5432`. Check `DATABASE_URL` in `backend\.env`. |
| `start_db.bat`: "Start failed" | Read `.pgdata\server.log`. The usual causes are another PostgreSQL already using port 5432 (stop it, or change `port` in `.pgdata\postgresql.conf` and in `DATABASE_URL`), or a stale `.pgdata\postmaster.pid` after a crash (delete it only if no `postgres.exe` is running). |
| `psql` not found | Run `start_db.bat` in that same cmd window (it adds `..\tools\pgsql\bin` to PATH), or call it by full path. |
| `could not open extension control file ... postgis.control` | The PostGIS bundle wasn't copied into `tools\pgsql`; redo the robocopy step. |
| `No boundary files in …` | Add a file to `backend/data/raw/boundaries/` (see its README). |
| `cannot find a name column` | Set `BOUNDARY_NAME_COL` (and `BOUNDARY_DISTRICT_COL`, `BOUNDARY_STATE_COL`) in `.env`. |
| 0 regions for the state | The state column's spelling differs. Matching ignores case and spaces, so check the value; or set `BOUNDARY_STATE_COL`. |
| IMD download slow or failing | The IMD server is slow (10–30 s per request) and sometimes returns empty files. Each download is retried 3 times; just re-run to fill any remaining gaps, since completed files are cached. Behind a proxy, set `HTTP_PROXY_URL`. |
| `IMD final rainfall for 2026 not available` | Expected. IMD publishes final data about a year late. `rainfall`/`daily` use the real-time grid instead. |
| Index download 403/timeout | Cached copies are used if present. Check the URL in a browser and update `ONI_URL` / `DMI_URL` / `RMM_URL` / `ROMI_URL`. |
| ERA5 `skipped` | No `CDS_API_KEY`. That's fine: ERA5 columns stay NULL. To enable it, add your CDS token **and** accept the licence for "ERA5 hourly data on pressure levels" and "single levels" on the CDS website. |
| Changed the bounding box | Delete `backend/data/raw/imd/cropped/` and re-run `rainfall` and `aggregate`. |
| Start over | `stop_db.bat`, delete `.pgdata\`, repeat one-time setup steps 2–3, then run `--stage all`. Raw downloads are kept. (Docker: `docker compose down -v`.) |
