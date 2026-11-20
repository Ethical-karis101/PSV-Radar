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
owner at `/register`, then prepare routes, vehicles, fare rules, camera devices,
and conductor accounts for your operation. Conductors sign in on the conductor
dashboard and create their own trip using a prepared vehicle; they can then start
the run and submit its collection at handover. The local development database is
deliberately excluded from the Docker image; no local demo or personal records
are deployed.

## Connect the local camera demo to Railway

Deploy only the owner/conductor web app and API to Railway. The Railway
container does not have access to a camera attached to your laptop or vehicle,
so do not run the webcam detector inside the Railway service. The camera console
and detector run on the computer physically connected to the webcam; they send
crossing-event metadata and heartbeats to the public Railway API. Video frames
stay on that local computer.

1. Open the deployed app at its HTTPS Railway domain and sign in as the owner.
2. In **Cameras**, add a device and assign it to the vehicle. Copy the displayed
   device token immediately; it is shown only once. Prepare the vehicle's route
   and have the conductor start a trip from the deployed conductor dashboard.
3. On the computer connected to the webcam, from the repository root, install
   the optional local detector dependencies:

   ```bash
   python3 -m pip install -r edge_agent/requirements-webcam.txt
   ```

4. Run the local camera console, replacing the Railway URL and device credentials:

   ```bash
   PSV_RADAR_API_URL='https://your-service.up.railway.app' \
   PSV_RADAR_DASHBOARD_URL='https://your-service.up.railway.app' \
   PSV_CAMERA_DEVICE_ID='camera-matatu-01' \
   PSV_CAMERA_DEVICE_TOKEN='paste-the-one-time-token-here' \
   python3 -m uvicorn edge_agent.webcam_ui:app --host 127.0.0.1 --port 8765
   ```

5. On that same computer, open `http://127.0.0.1:8765`, allow camera access,
   position the virtual door line, and start the demo. The conductor updates the
   current route stage from their deployed screen. The owner can watch device
   heartbeat and event totals at `https://your-service.up.railway.app/dashboard?view=cameras`.

The first detector launch downloads the `yolo11n.pt` model, so install the
dependencies and warm the model before the presentation. Keep the device token
private and do not store it in Railway variables: it is only needed by the local
camera process. Run this supervised prototype on the same computer that has the
webcam; opening the local console URL on a different phone or computer will not
connect it to the first computer's camera or detector. The local console is a
hackathon demo, not an unattended vehicle deployment or a replacement for the
planned Android camera app.

## Optional: hosted camera demo service

For a short demo without a local install, deploy the webcam UI as a second
Railway service from this repository. The browser sends camera frames to this
service and YOLO runs on its CPU, so video frames leave the device: use it only
with consent, and prefer the local console above otherwise.

1. Create a service from this repository and set its Dockerfile path to
   `Dockerfile.camera`. Give it a public domain (HTTPS is required for camera access).
2. Set variables: `PSV_RADAR_API_URL` (the main service's HTTPS URL),
   `PSV_CAMERA_DEVICE_ID`, `PSV_CAMERA_DEVICE_TOKEN` and `CAMERA_UI_PASSWORD`.
   Without `CAMERA_UI_PASSWORD` the service is open to anyone.
3. Open the service URL, sign in with any username and that password, then start the camera.

The state is global, so one camera and one viewer per service. The image is
about 2.5 GB and CPU inference may be slow; test it before presenting.

## Important operating note

The current backend uses SQLite, which is appropriate for the single-service
hackathon MVP. Keep one app replica, keep the volume attached, and arrange backups
for operational data. For multi-replica or higher-write production use, migrate
to a managed PostgreSQL database before scaling the web service.
