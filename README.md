# PSV-Radar

PSV-Radar helps Kenyan public service vehicle owners and SACCOs estimate expected fare revenue and compare it with declared collections.

Our first milestone is a daily revenue report for one vehicle on one route. The backend and dashboard will start with sample boarding and alighting events. A teammate will develop the machine learning component in a separate repository. Cashless payments and road safety features will follow in later phases.

## Operational MVP

The current vertical slice models a round-trip as two separate trips, allowing the conductor to change after every trip:

1. Create a route with ordered stages and fare rules.
2. Assign a vehicle and conductor to a trip.
3. Start the trip and ingest boarding/alighting events with `track_id`, `trip_id`, `route_id`, and `stage_id`.
4. PSV-Radar pairs matching events automatically and calculates the expected fare.
5. End the trip. Unmatched events become review cases.
6. The conductor declares cash, M-Pesa, and other collections for that trip.
7. The owner reviews expected revenue, declared revenue, variance, and exceptions.

## Railway deployment

The root Dockerfile builds the React frontend and runs it with the FastAPI API as
one Railway web service. Follow [the Railway deployment guide](docs/railway-deployment.md)
to attach persistent SQLite storage and configure the service.

For the camera MVP, use a mounted camera at the shared passenger door. A pretrained person detector plus a lightweight multi-object tracker emits line-crossing events. The tracker ID is local to the door view; it is not a permanent passenger identity. When boarding and alighting IDs differ, the backend uses FIFO occupancy matching and exposes uncertain cases in the review queue.

The React app lives in `frontend-react`. Build it with `npm install && npm run build`; the compiled shell is served by the backend at `/dashboard`. Set `VITE_API_URL` for a separate frontend deployment. The operational API is under `/operations`.

Authentication now uses server-side sessions and role-aware route protection. Further production hardening should add password reset/invites, rate limiting, and stricter organization scoping for operational records.

## Account access

Owners register themselves at `/register`. After signing in, an owner can open `/conductors` and create conductor accounts. A conductor never self-registers: they use the email and temporary password supplied by the owner at `/login`, after which PSV-Radar routes them to `/conductor`. Owner pages require an owner session; conductor accounts cannot access the owner dashboard or account-management screen.
