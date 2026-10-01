# PocketSmart AI

Budget-aware lifestyle recommendations for home interiors, parties and jewelry. Built with FastAPI, Jinja2 and Google's Gemini API.

## Run locally
1. Install Python 3.10+.
2. In this folder run `python -m venv .venv` and activate it.
3. Install dependencies: `pip install -r requirements.txt`
4. Copy `.env.example` to `.env`. Add `GEMINI_API_KEY` to enable Gemini; without it the app uses clearly labelled demo recommendations.
5. Start: `uvicorn app.main:app --reload`
6. Open http://127.0.0.1:8000

Register an account to save planner history. SQLite data is stored in `pocketsmart.db` and created on first run. The demo provider suggestions are illustrative; they are not live inventory or verified prices. Connect official affiliate/product APIs before using them as real listings.

## API
- `POST /api/register`, `POST /api/login`, `POST /api/logout`
- `GET /api/session-info`, `GET /api/session-data`, `GET /api/history`
- `POST /api/generate-home`, `POST /api/generate-party`
- `POST /api/generate-jewelry` (multipart; optional outfit image)
- `GET /api/recommendations-details/{id}`
- `GET /health`

The UI uses cookie sessions. Configure a long random `SECRET_KEY` before deployment. This starter stores passwords with PBKDF2 hashing and should be served over HTTPS in production.
