# Wind outlook — historical pilot

A day-ahead planning aid for Elexon's Great Britain wind series. The Decision view shows the forecast available at a selected January 2026 decision time for the following civil day. The Accuracy view evaluates those forecasts against subsequently observed generation. This is a historical snapshot, not a live feed or a purchasing recommendation.

## Run

Prerequisites: Docker and Docker Compose, or Python 3.11+ with the IANA timezone database and Node.js 20.19+ or 22.12+ (Node 24 used for the build). From the repository root:

```sh
docker compose up --build
```

Open http://localhost:8000. The image builds the React app and serves it and the API from the same Python process. The container build and startup were verified locally; the server exposes the frontend and API on the same origin.

For local development, in two terminals:

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
pip install -r requirements-dev.txt  # for tests
python3 -m uvicorn backend.main:app --reload --port 8000
```

```sh
cd frontend
npm ci
npm run dev
```

Open the Vite URL shown in the terminal; Vite proxies `/api` to port 8000. For production without Docker, run `npm run build --prefix frontend` first, then start Uvicorn as above and open port 8000. The backend serves `frontend/dist` when it exists. The committed npm lockfile fixes the frontend dependency tree; the Docker build uses `npm ci`.

## Deployment to Vercel

The repository contains `vercel.json` for Vercel Services: a Vite frontend and a FastAPI service share one public origin. The API service is rooted at the repository root so the Python code, requirements, `data/manifest.json` and `data/raw/` are available. `.vercelignore` excludes preparation notes and development artifacts; the historical snapshot remains included. Vercel Services is a beta feature; a local Services run is not proof of a cloud deployment.

No public deployment URL is available yet. Import the GitHub repository into Vercel with the repository root as the project root, or use the Vercel CLI from this directory:

```sh
npx vercel login
npx vercel
npx vercel --prod
```

When prompted, link or create the intended Vercel project. No application secrets or database are needed. Check the resulting URL, `/api/health` and `/api/analysis` in a fresh browser, then change the dashboard filters and verify the results. Ensure deployment protection allows the intended reviewers access. Add the actual production URL here after deployment.

To test Services locally without linking an account, use `npx vercel dev --local` and open the printed URL. The frontend and API run locally; this does not verify Vercel's cloud build, data packaging, plan limits or public access.

The existing `heroku.yml` and Docker configuration remain available as an alternative. Do not publish the source challenge or local preparation notes. No credentials belong in the repository.

## Data and method

The supplied raw arrays come from Elexon's [WINDFOR stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/WINDFOR/stream) and [FUELHH stream](https://bmrs.elexon.co.uk/api-documentation/endpoint/datasets/FUELHH/stream), filtered to WIND. `data/manifest.json` records exact requests, retrieval times (28 October 2026 UTC), row counts and SHA-256 checksums. The service verifies these on first load and reads the snapshot in memory; requests never fetch source data. `scripts/fetch_elexon.py` is an explicit acquisition script: rerunning it can change the snapshot and baseline. The saved schema is in `evidence/elexon-openapi-subset.json`.

Decision dates are 1–31 January 2026, with delivery on the following civil day in Europe/London, 00:00–24:00. This produces deliveries from 2 January to 1 February. This is an assumption, not a venue-specific trading calendar. The default 09:00 London cutoff is illustrative, not a universal auction gate; it can be changed. For each target hour, select the row with the latest `publishTime` at or before the cutoff, including equality. Publication time is a proxy for availability; actual receipt delays are unknown. If no row qualifies or the latest eligible value is null, the forecast is missing; an older non-null value or a later forecast is never substituted.

For each hour, compare forecast MW at `h` with the mean of FUELHH actual MW at `h` and `h+30 minutes`. Both half-hours must be present and non-null. The latest downloaded actual revision is retrospective truth. This hourly alignment is an explicit pilot convention. Errors are forecast minus actual: positive bias means overforecasting. MAE is mean absolute error, RMSE the square root of mean squared error, and bias the mean signed error. Metrics use only matched hours; missing points remain null and coverage shows the denominator. Decision view excludes actuals and retrospective statistics.

The snapshot's full January decision range at 09:00 has 744/744 matched hours, MAE 2,038.912634 MW, RMSE 2,504.758653 MW and bias +1,747.887097 MW. These are regression values for that specific snapshot and method, not values used by the app for other filters.

The series represents Elexon's metered GB wind coverage, not every UK wind generator. The app has no customer demand, supply commitments, prices, procurement volume, realized profit or calibrated forecast probabilities. It cannot calculate how much power to buy or claim financial savings.

## Checks

```sh
python3 scripts/analyze_data.py
python3 -m unittest discover -s tests -v
npm ci --prefix frontend
npm run build --prefix frontend
docker compose up --build
```

The reference analysis and 18 tests passed, including HTTP requests through FastAPI TestClient, the baseline, changed cutoff, missing-data serialization and input validation. A clean `npm ci` and production build passed (with a bundle-size warning); a clean Python virtual environment with the runtime and test requirements also passed the tests. `docker compose up --build -d` built and started the container; HTTP health and analysis requests and the browser flow were checked against it. The browser was tested locally, not as a public deployment. The build warns that Recharts 2 is no longer maintained. The original `python` commands were unavailable in the earlier environment, so the `python3` equivalents were used.

## Files

- `backend/main.py`: FastAPI routes, snapshot verification, filtering and aggregation.
- `frontend/`: Vite, React, TypeScript and Recharts interface.
- `scripts/analyze_data.py`: shared selection/alignment/metrics and reproducible reference outputs; `scripts/fetch_elexon.py`: explicit source acquisition.
- `data/raw/` and `data/manifest.json`: source snapshot and provenance; `data/derived/`: reference outputs.
- `tests/`: reference and HTTP-level API regression tests.
- `Dockerfile`, `compose.yaml`, `heroku.yml`, `vercel.json` and `.vercelignore`: container and deployment configuration; `requirements-dev.txt` supplies HTTP test dependencies.
- `context/methodology.md` and `evidence/`: methodology and saved source schema. Other supplied preparation notes are not part of the curated commit.
- `DEMO.md`: customer and technical video outline.

## AI assistance and submission

OpenAI Codex assisted with implementation, testing and documentation. The checks and limitations above describe what was actually verified. No public repository, deployed app or video URL is available yet. Record an unlisted video of at most ten minutes, create an anonymous public repository, verify app/repository/video URLs in an incognito session, and submit the required form only after the video is ready.
