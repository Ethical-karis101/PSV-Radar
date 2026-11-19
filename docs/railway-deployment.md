# Deploy PSV-Radar on Railway

The repository is set up as a single Railway web service: the Docker build
compiles the React app, then the FastAPI service serves the API and the built
single-page app from the same origin.

## Create the service

1. Push this repository to GitHub.
2. In Railway, create a project and deploy the GitHub repository from its root.
   Railway will use the root `Dockerfile` for the multi-stage frontend/backend
   build.
3. Add a Railway Volume to the service and set its mount path to `/data`.
4. Add these service variables:

   | Variable | Value |
   | --- | --- |
   | `PSV_RADAR_DATABASE_PATH` | `/data/passenger_events.sqlite3` |
   | `PSV_RADAR_SECURE_COOKIES` | `1` |
   | `PSV_RADAR_ALLOWED_ORIGINS` | The service's HTTPS origin, e.g. `https://your-service.up.railway.app` |

5. Generate a Railway public domain. The health check endpoint is `/health`.
6. Keep this SQLite deployment to one running replica with the volume attached
   to the web service. The SQLite database is persisted on that volume; the
   container filesystem itself is not persistent.

The React app automatically sends API calls to its current origin in production.
Only set `VITE_API_URL` if you intentionally deploy the frontend and backend on
different origins.

## First launch

The database schema initializes when the service starts. Register the first
owner at `/register`, then create the routes, vehicles, fare rules, and conductor
accounts for your operation. The local development database is deliberately
excluded from the Docker image; no local demo or personal records are deployed.

## Important operating note

The current backend uses SQLite, which is appropriate for the single-service
hackathon MVP. Keep one app replica, keep the volume attached, and arrange backups
for operational data. For multi-replica or higher-write production use, migrate
to a managed PostgreSQL database before scaling the web service.
