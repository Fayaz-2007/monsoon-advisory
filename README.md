<div align="center">

![header](https://capsule-render.vercel.app/api?type=waving&color=gradient&height=200&section=header&text=AgriVarsha&fontSize=45&fontColor=fff)

![Typing SVG](https://readme-typing-svg.demolab.com?font=Fira+Code&size=22&pause=1000&color=10B981&center=true&vCenter=true&width=750&lines=Hyperlocal+monsoon+onset+%26+break+prediction;Block-level+crop+advisories+for+Tamil+Nadu+farmers)

![Python](https://img.shields.io/badge/Python-3776AB?style=for-the-badge&logo=python&logoColor=white)
![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=for-the-badge&logo=fastapi&logoColor=white)
![React](https://img.shields.io/badge/React-20232A?style=for-the-badge&logo=react&logoColor=61DAFB)
![PostGIS](https://img.shields.io/badge/PostGIS-336791?style=for-the-badge&logo=postgresql&logoColor=white)
![LightGBM](https://img.shields.io/badge/LightGBM-00A3E0?style=for-the-badge)
![SIH 2026](https://img.shields.io/badge/Smart%20India%20Hackathon-2026-FF6B35?style=for-the-badge)
![Made By](https://img.shields.io/badge/Made%20by-Fayaz--2007-blueviolet?style=for-the-badge)

</div>

## 📌 Overview

Monsoon forecasts in India are usually issued at the state or district level, far too coarse for a farmer deciding when to sow. **AgriVarsha** (monsoon-advisory) closes that gap: it predicts monsoon onset, false onset, dry spells, heavy-rain spells and monsoon revival at **block level, 1–4 weeks ahead**, then turns those hazard forecasts into plain-language (English + Tamil) crop advisories. Built for **Smart India Hackathon 2026**, the system runs a real IMD-rainfall data pipeline and a validated LightGBM forecasting model behind a live dashboard, with the demo scoped to Tamil Nadu but designed to be state-agnostic.

## ✨ Features

- 📡 Real daily-rainfall pipeline ingesting IMD gridded data (1991 → present) plus ENSO, IOD and MJO climate indices
- 🧠 LightGBM-based forecasting model (`s2-lgbm-...`) with confidence-rated 1–4 week forecasts
- ⚠️ Hazard detection for false onset, dry spells, heavy rain and monsoon revival, driven by observed rainfall
- 🌾 Advisory engine that drafts farmer-facing recommendations in English and Tamil with a review workflow and audit trail
- 🗺️ Interactive block/district map dashboard (React + Leaflet) with live data, no mock state on the frontend
- 🔀 Switchable forecast source — deterministic mock generator or the real trained model — toggled per deployment
- 📲 SMS/WhatsApp/IVR advisory delivery pipeline (simulated gateway, real advisory text)
- 🧪 Built-in demo scenarios (false onset trap, NE monsoon surge, mid-season break, normal season) for live walkthroughs

## 🛠️ Tech Stack

**Languages**

![](https://skillicons.dev/icons?i=py,ts)

**ML**

![](https://skillicons.dev/icons?i=sklearn)

**Backend**

![](https://skillicons.dev/icons?i=fastapi)

**Database**

![](https://skillicons.dev/icons?i=postgres)

**Frontend**

![](https://skillicons.dev/icons?i=react,vite,tailwind)

**Tools**

![](https://skillicons.dev/icons?i=git,github)

**Also using**

![LightGBM](https://img.shields.io/badge/LightGBM-00A3E0?style=for-the-badge) ![MLflow](https://img.shields.io/badge/MLflow-0194E2?style=for-the-badge&logo=mlflow&logoColor=white) ![Pydantic](https://img.shields.io/badge/Pydantic-E92063?style=for-the-badge&logo=pydantic&logoColor=white) ![PostGIS](https://img.shields.io/badge/PostGIS-336791?style=for-the-badge&logo=postgresql&logoColor=white) ![Leaflet](https://img.shields.io/badge/Leaflet-199900?style=for-the-badge&logo=leaflet&logoColor=white) ![Claude](https://img.shields.io/badge/Claude-D97757?style=for-the-badge&logo=anthropic&logoColor=white)

## 🏗️ Architecture

```mermaid
flowchart LR
    IMD[IMD Rainfall + ENSO/IOD/MJO] --> PIPE[Segment 1\nData Pipeline]
    PIPE --> DB[(PostgreSQL + PostGIS)]
    DB --> ML[Segment 2\nLightGBM Forecast Model]
    DB --> HAZ[Hazard Detection]
    ML --> HAZ
    HAZ --> ADV[Advisory Engine\nEN + Tamil]
    ADV --> API[FastAPI Backend]
    API --> FE[React Dashboard]
    ADV --> DELIVERY[SMS / WhatsApp / IVR]
```

## 📂 Project Structure

```
monsoon-advisory/
├── backend/
│   ├── pipeline/        # Segment 1 — IMD ingestion, climatology, features
│   ├── ml/               # Segment 2 — LightGBM forecasting model
│   ├── hazards/          # Hazard detection logic
│   ├── advisory/         # Advisory drafting + review workflow
│   ├── app/               # FastAPI backend (Segments 3–5, 7)
│   ├── delivery/         # SMS/WhatsApp/IVR gateway
│   ├── data/              # raw/ and processed/ (mostly git-ignored)
│   ├── tests/
│   └── requirements.txt
├── frontend/              # React + Vite + TypeScript dashboard
├── docs/contracts/        # Inter-segment data contracts
├── setup_db.bat            # One-click native PostgreSQL + PostGIS setup (Windows)
├── start_db.bat / stop_db.bat
└── docker-compose.yml      # Optional Docker alternative
```

## ⚙️ Installation

```bash
git clone https://github.com/Fayaz-2007/monsoon-advisory.git
cd monsoon-advisory

# Database (Windows, no admin rights needed)
setup_db.bat

# Backend
cd backend
py -3.11 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt

# Frontend
cd ../frontend
npm install
```

### Environment variables (`backend/.env`)

| Variable | Description |
|---|---|
| `DATABASE_URL` | PostgreSQL + PostGIS connection string |
| `FORECAST_SOURCE` | `mock` (default) or `real` to use the trained LightGBM model |
| `CDS_API_KEY` | Optional — enables ERA5 climate data ingestion |
| `LLM_API_KEY` | Optional — enables Claude-powered plain-language rewording |

## 🚀 Usage

**One-click demo:**

```bash
run_demo.bat
```

This starts PostgreSQL, the FastAPI backend (`:8000`), the React frontend (`:5173`) and opens the dashboard. Press **D** in the app for demo scenario controls.

**Manual pipeline run:**

```bash
cd backend
python -m pipeline.run --stage all --start 1991-01-01 --end 2025-12-31
python -m app.seed --scenarios
uvicorn app.main:app --reload
```



## 🔮 Future Improvements

- Expand beyond Tamil Nadu to additional states using the existing state-agnostic pipeline
- Replace the simulated SMS/WhatsApp/IVR gateway with a real delivery integration
- Move farmer-count data from mock to a real district × crop dataset
- Promote the real LightGBM forecast source to default once validated further

## 👨‍💻 Author

**Fayaz Ahmed**
GitHub: [@Fayaz-2007](https://github.com/Fayaz-2007)
LinkedIn: [fayaz-ahmed-59287631a](https://linkedin.com/in/fayaz-ahmed-59287631a)

<div align="center">

![footer](https://capsule-render.vercel.app/api?type=waving&color=gradient&height=150&section=footer)

</div>
