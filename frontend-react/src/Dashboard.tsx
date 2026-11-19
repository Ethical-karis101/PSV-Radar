import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './Dashboard.css'

const API = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? window.location.origin : 'http://localhost:8000')
type View = 'overview' | 'trips' | 'vehicles' | 'conductors' | 'reviews'
type Summary = { trips: number; expected_revenue_kes: number; declared_revenue_kes: number; variance_kes: number; open_review_cases: number; boardings: number }
type Trip = { trip_id: string; registration: string; route_name: string; direction: string; conductor_name?: string; status: string; expected_revenue_kes: number; declared_revenue_kes?: number }
type Review = { case_id: string; reason: string; registration?: string; route_name?: string; created_at: string; status?: string; event_id?: string; note?: string }
type Vehicle = { vehicle_id: string; registration: string; route_id?: string; route_name?: string; active: number }
type Route = { route_id: string; name: string; origin: string; destination: string }
type TrendDay = { day: string; expected_revenue_kes: number; completed_journeys: number; boardings: number }
type User = { name: string; email: string }

const emptySummary: Summary = { trips: 0, expected_revenue_kes: 0, declared_revenue_kes: 0, variance_kes: 0, open_review_cases: 0, boardings: 0 }
const money = (value: number) => `KES ${Math.abs(value).toLocaleString('en-KE')}`
const signedMoney = (value: number) => `${value < 0 ? '-' : '+'}${money(value)}`

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, { credentials: 'include' })
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail ?? 'API unavailable')
  return response.json()
}

export default function Dashboard() {
  const [view, setView] = useState<View>(() => viewFromUrl())
  const [summary, setSummary] = useState<Summary>(emptySummary)
  const [trips, setTrips] = useState<Trip[]>([])
  const [reviews, setReviews] = useState<Review[]>([])
  const [vehicles, setVehicles] = useState<Vehicle[]>([])
  const [routes, setRoutes] = useState<Route[]>([])
  const [user, setUser] = useState<User | null>(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [me, nextSummary, nextTrips, nextReviews, nextVehicles, nextRoutes] = await Promise.all([
        getJson<{ user: User }>('/auth/me'), getJson<Summary>('/operations/summary'),
        getJson<{ trips: Trip[] }>('/operations/trips'), getJson<{ reviews: Review[] }>('/operations/reviews'),
        getJson<{ vehicles: Vehicle[] }>('/operations/vehicles'), getJson<{ routes: Route[] }>('/operations/routes'),
      ])
      setUser(me.user); setSummary(nextSummary); setTrips(nextTrips.trips); setReviews(nextReviews.reviews)
      setVehicles(nextVehicles.vehicles); setRoutes(nextRoutes.routes); setConnected(true)
    } catch (requestError) {
      setConnected(false); setError(requestError instanceof Error ? requestError.message : 'Could not load operational data.')
    } finally { setLoading(false) }
  }, [])

  useEffect(() => {
    const onPopState = () => setView(viewFromUrl())
    window.addEventListener('popstate', onPopState)
    const timer = window.setTimeout(() => void load(), 0)
    return () => { window.removeEventListener('popstate', onPopState); window.clearTimeout(timer) }
  }, [load])

  function navigate(nextView: View) {
    window.history.pushState({}, '', nextView === 'overview' ? '/dashboard' : `/dashboard?view=${nextView}`)
    setView(nextView)
  }

  async function resolveReview(caseId: string, status: 'resolved' | 'excluded') {
    try {
      const response = await fetch(`${API}/operations/reviews/${caseId}/resolve`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ status, note: null }) })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? 'Could not update this review.')
      await load()
    } catch (requestError) { setError(requestError instanceof Error ? requestError.message : 'Could not update this review.') }
  }

  async function signOut() { await fetch(`${API}/auth/logout`, { method: 'POST', credentials: 'include' }).catch(() => undefined); window.location.href = '/login' }

  return <div className="app-shell"><Sidebar active={view} onNavigate={navigate} onSignOut={signOut} /><main className="dashboard-main"><div className="mobile-top"><Brand /></div>
    <header className="dashboard-header"><div><p className="eyebrow">{new Date().toLocaleDateString('en-KE', { weekday: 'long', day: 'numeric', month: 'long', year: 'numeric' })}</p><h1>{viewTitle(view)}</h1><p className="header-sub">{user ? `Habari, ${user.name}. Here’s what’s happening across your fleet.` : 'Your fleet, trips and collections in one place.'}</p></div><div className="header-tools"><span className={`connection ${connected ? 'online' : ''}`}><i /> {connected ? 'Up to date' : 'Offline'}</span><button className="icon-button" onClick={() => void load()} aria-label="Refresh data">↻</button><span className="dashboard-avatar">{initials(user?.name ?? 'Owner')}</span></div></header>
    {error && <div className="data-error" role="alert"><strong>Live data unavailable.</strong> {error}<button onClick={() => void load()}>Retry</button></div>}
    {loading ? <div className="loading-state"><span className="status-dot" /> Loading operational data…</div> : <>{view === 'overview' && <Overview summary={summary} trips={trips} reviews={reviews} vehicles={vehicles} onNavigate={navigate} />}{view === 'trips' && <TripsView trips={trips} />}{view === 'vehicles' && <VehiclesView vehicles={vehicles} routes={routes} onSaved={load} />}{view === 'conductors' && <ConductorsView />}{view === 'reviews' && <ReviewsView reviews={reviews} onResolve={resolveReview} />}</>}
  </main></div>
}

function Overview({ summary, trips, reviews, vehicles, onNavigate }: { summary: Summary; trips: Trip[]; reviews: Review[]; vehicles: Vehicle[]; onNavigate: (view: View) => void }) {
  const [selectedVehicle, setSelectedVehicle] = useState('')
  const [trend, setTrend] = useState<TrendDay[]>([])
  const [trendError, setTrendError] = useState('')
  const activeVehicle = selectedVehicle || vehicles[0]?.vehicle_id || ''
  useEffect(() => { if (!activeVehicle) return; const endDay = new Date().toISOString().slice(0, 10); getJson<{ days: TrendDay[] }>(`/revenue/weekly?vehicle_id=${encodeURIComponent(activeVehicle)}&end_day=${endDay}`).then((data) => { setTrend(data.days); setTrendError('') }).catch(() => setTrendError('Trend data is unavailable.')) }, [activeVehicle])
  const maxTrend = Math.max(...trend.map((day) => day.expected_revenue_kes), 1)
  return <><section className="dashboard-metrics"><Metric label="Expected fares" value={money(summary.expected_revenue_kes)} note={`${summary.trips} completed runs`} tone="lime" /><Metric label="Declared collections" value={money(summary.declared_revenue_kes)} note="Across completed runs" tone="blue" /><Metric label="Collection difference" value={signedMoney(summary.variance_kes)} note={summary.variance_kes < 0 ? 'Declared below expected' : 'Declared above expected'} tone="amber" /><Metric label="Needs review" value={String(summary.open_review_cases)} note="Check these trips" tone="red" /></section>
    <section className="dashboard-grid"><article className="panel performance-panel"><div className="panel-title"><div><p className="eyebrow">By vehicle · last 7 days</p><h2>Expected fares by day</h2></div><select className="compact-select" value={activeVehicle} onChange={(event) => setSelectedVehicle(event.target.value)} aria-label="Select vehicle trend"><option value="">Select vehicle</option>{vehicles.map((vehicle) => <option key={vehicle.vehicle_id} value={vehicle.vehicle_id}>{vehicle.registration}</option>)}</select></div>{trendError ? <p className="empty-state">{trendError}</p> : trend.length === 0 ? <p className="empty-state">Select a vehicle to see its seven-day trend.</p> : <div className="bar-chart"><div className="bar-labels"><span>{money(maxTrend).replace('KES ', '')}</span><span>0</span></div><div className="bars">{trend.map((day, index) => <div className={`bar-group ${index === trend.length - 1 ? 'today' : ''}`} key={day.day}><i style={{ height: `${Math.max(5, day.expected_revenue_kes / maxTrend * 100)}%` }} /><span>{new Date(`${day.day}T12:00:00`).toLocaleDateString('en-KE', { weekday: 'short' })}</span></div>)}</div></div>}<div className="chart-legend"><span><i className="legend-expected" /> Expected fares</span></div></article><article className="panel review-panel"><div className="panel-title"><div><p className="eyebrow">Needs a look</p><h2>Trips to check</h2></div><button className="text-action" onClick={() => onNavigate('reviews')}>See all →</button></div><ReviewList reviews={reviews.slice(0, 3)} onResolve={() => undefined} compact /></article></section>
    <section className="panel trips-panel"><div className="panel-title"><div><p className="eyebrow">Latest activity</p><h2>Recent runs</h2></div><button className="text-action" onClick={() => onNavigate('trips')}>All trips →</button></div><TripTable trips={trips.slice(0, 5)} /></section></>
}

function TripsView({ trips }: { trips: Trip[] }) { const [status, setStatus] = useState('all'); const filtered = status === 'all' ? trips : trips.filter((trip) => trip.status === status); return <section className="panel full-panel"><div className="view-heading"><div><p className="eyebrow">Operations</p><h2>Trips</h2><p>Review every run, conductor, expected fare, and collection variance.</p></div><select className="filter-select" value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter trips"><option value="all">All statuses</option><option value="active">Active</option><option value="scheduled">Scheduled</option><option value="ended">Ended</option></select></div><TripTable trips={filtered} empty="No trips match this filter." /></section> }

function VehiclesView({ vehicles, routes, onSaved }: { vehicles: Vehicle[]; routes: Route[]; onSaved: () => Promise<void> }) { const [message, setMessage] = useState(''); const [error, setError] = useState(''); async function create(event: FormEvent<HTMLFormElement>) { event.preventDefault(); setMessage(''); setError(''); const fields = new FormData(event.currentTarget); const response = await fetch(`${API}/operations/vehicles`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ vehicle_id: fields.get('vehicle_id'), registration: fields.get('registration'), route_id: fields.get('route_id') || null }) }); const payload = await response.json().catch(() => ({})); if (!response.ok) { setError(payload.detail ?? 'Could not add vehicle.'); return } event.currentTarget.reset(); setMessage('Vehicle added successfully.'); await onSaved() } return <section className="owner-columns"><article className="panel full-panel"><div className="view-heading"><div><p className="eyebrow">Fleet</p><h2>Vehicles</h2><p>Keep vehicle assignments ready for trip and camera operations.</p></div><span className="count-badge">{vehicles.length}</span></div><div className="vehicle-list">{vehicles.length === 0 ? <p className="empty-state">No vehicles registered yet.</p> : vehicles.map((vehicle) => <div className="vehicle-row" key={vehicle.vehicle_id}><span className="vehicle-icon">▣</span><div><strong>{vehicle.registration}</strong><span>{vehicle.vehicle_id} · {vehicle.route_name ?? 'No route assigned'}</span></div><em className={vehicle.active ? 'active' : ''}>{vehicle.active ? 'Active' : 'Inactive'}</em></div>)}</div></article><article className="panel full-panel"><p className="eyebrow">Fleet setup</p><h2>Add a vehicle</h2><form className="owner-form" onSubmit={create}><label>Vehicle ID<input name="vehicle_id" required placeholder="psv-van-01" /></label><label>Registration<input name="registration" required placeholder="KDA 418M" /></label><label>Default route<select name="route_id"><option value="">No route yet</option>{routes.map((route) => <option key={route.route_id} value={route.route_id}>{route.name}</option>)}</select></label>{error && <p className="form-error" role="alert">{error}</p>}{message && <p className="form-success" role="status">{message}</p>}<button className="primary-action" type="submit">Add vehicle <span>↗</span></button></form></article></section> }

type ConductorAccount = { user_id: string; conductor_id: string; name: string; email: string; phone?: string; active: number }
function ConductorsView() {
  const [conductors, setConductors] = useState<ConductorAccount[]>([])
  const [error, setError] = useState('')
  const [message, setMessage] = useState('')
  const [loadingConductors, setLoadingConductors] = useState(true)
  const loadConductors = useCallback(async () => {
    setLoadingConductors(true)
    try { const data = await getJson<{ conductors: ConductorAccount[] }>('/auth/conductors'); setConductors(data.conductors); setError('') }
    catch (loadError) { setError(loadError instanceof Error ? loadError.message : 'Could not load conductor accounts.') }
    finally { setLoadingConductors(false) }
  }, [])
  useEffect(() => { const timer = window.setTimeout(() => void loadConductors(), 0); return () => window.clearTimeout(timer) }, [loadConductors])
  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setError(''); setMessage('')
    const form = event.currentTarget
    const fields = new FormData(event.currentTarget)
    const response = await fetch(`${API}/auth/conductors`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ conductor_id: fields.get('conductor_id'), name: fields.get('name'), email: fields.get('email'), phone: fields.get('phone') || null, password: fields.get('password') }) })
    const payload = await response.json().catch(() => ({}))
    if (!response.ok) { setError(payload.detail ?? 'Could not create the account.'); return }
    form.reset(); setMessage('Conductor account created. Share the login details securely.'); await loadConductors()
  }
  return <section className="owner-columns conductor-management"><article className="panel full-panel"><div className="view-heading"><div><p className="eyebrow">The crew</p><h2>Conductors</h2><p>Manage who can sign in and close out each run.</p></div><span className="count-badge">{conductors.length}</span></div>{loadingConductors ? <p className="empty-state">Loading conductor accounts…</p> : conductors.length === 0 ? <p className="empty-state">No conductor accounts yet. Add the first account to get started.</p> : <div className="vehicle-list">{conductors.map((conductor) => <div className="vehicle-row conductor-row" key={conductor.user_id}><span className="conductor-initial">{initials(conductor.name)}</span><div><strong>{conductor.name}</strong><span>{conductor.email}{conductor.phone ? ` · ${conductor.phone}` : ''} · {conductor.conductor_id}</span></div><em className={conductor.active ? 'active' : ''}>{conductor.active ? 'Can sign in' : 'Access off'}</em></div>)}</div>}</article><article className="panel full-panel"><p className="eyebrow">Team access</p><h2>Add a conductor</h2><p className="form-intro">Create their sign-in details before assigning them to a trip.</p><form className="owner-form" onSubmit={create}><label>Full name<input name="name" required placeholder="e.g. Mary Wanjiku" /></label><label>Conductor ID<input name="conductor_id" required placeholder="cond-mary-01" /></label><label>Email address<input name="email" type="email" required placeholder="mary@example.com" /></label><label>Phone <span className="optional">Optional</span><input name="phone" type="tel" placeholder="07XX XXX XXX" /></label><label>Temporary password<input name="password" type="password" minLength={8} required placeholder="At least 8 characters" /></label>{error && <p className="form-error" role="alert">{error}</p>}{message && <p className="form-success" role="status">{message}</p>}<button className="primary-action" type="submit">Create account <span>↗</span></button></form></article></section>
}

function ReviewsView({ reviews, onResolve }: { reviews: Review[]; onResolve: (caseId: string, status: 'resolved' | 'excluded') => Promise<void> }) { return <section className="panel full-panel"><div className="view-heading"><div><p className="eyebrow">Data quality control</p><h2>Needs review</h2><p>Resolve uncertain matches before relying on the revenue numbers.</p></div><span className="count-badge warning">{reviews.length} open</span></div><ReviewList reviews={reviews} onResolve={onResolve} /></section> }

function ReviewList({ reviews, onResolve, compact = false }: { reviews: Review[]; onResolve: (caseId: string, status: 'resolved' | 'excluded') => void; compact?: boolean }) { if (reviews.length === 0) return <p className="empty-state">All caught up. No open reviews.</p>; return <div className={`review-list ${compact ? 'compact' : ''}`}>{reviews.map((review) => <div className="review-item" key={review.case_id}><span className="review-symbol">!</span><div><strong>{review.reason}</strong><span>{review.registration ?? 'Unassigned'} · {review.route_name ?? 'Route pending'} · {formatTime(review.created_at)}</span>{!compact && <small>{review.event_id ? `Event ${review.event_id}` : 'Event details unavailable'}</small>}</div>{!compact && <div className="review-actions"><button onClick={() => onResolve(review.case_id, 'resolved')}>Resolve</button><button onClick={() => onResolve(review.case_id, 'excluded')}>Exclude</button></div>}</div>)}</div> }

function TripTable({ trips, empty = 'No trips recorded yet.' }: { trips: Trip[]; empty?: string }) { if (trips.length === 0) return <p className="empty-state">{empty}</p>; return <div className="trip-table"><div className="trip-table-head"><span>VEHICLE & ROUTE</span><span>CONDUCTOR</span><span>EXPECTED FARES</span><span>DIFFERENCE</span><span>TRIP STATUS</span></div>{trips.map((trip) => { const variance = trip.declared_revenue_kes == null ? null : trip.declared_revenue_kes - trip.expected_revenue_kes; return <div className="trip-table-row" key={trip.trip_id}><div><strong>{trip.registration}</strong><span>{trip.route_name} · {trip.direction === 'return' ? 'return leg' : 'outbound leg'}</span><small>{trip.trip_id}</small></div><span>{trip.conductor_name ?? 'Not assigned'}</span><strong>{money(trip.expected_revenue_kes)}</strong><span className={variance != null && variance < 0 ? 'negative' : 'positive'}>{variance == null ? 'Awaiting collection' : signedMoney(variance)}</span><span className={`status-pill ${trip.status}`}>{trip.status === 'active' ? 'On route' : trip.status === 'ended' ? 'Trip ended' : trip.status}</span></div> })}</div> }

function Metric({ label, value, note, tone }: { label: string; value: string; note: string; tone: string }) { return <article className={`dash-metric ${tone}`}><span>{label}</span><strong>{value}</strong><small><b>↗</b> {note}</small></article> }
function Sidebar({ active, onNavigate, onSignOut }: { active: View; onNavigate: (view: View) => void; onSignOut: () => void }) { return <aside className="sidebar"><Brand /><nav><span className="side-label">Workspace</span><NavButton active={active === 'overview'} onClick={() => onNavigate('overview')} icon="⌂">Overview</NavButton><NavButton active={active === 'trips'} onClick={() => onNavigate('trips')} icon="↗">Trips</NavButton><NavButton active={active === 'vehicles'} onClick={() => onNavigate('vehicles')} icon="▣">Vehicles</NavButton><NavButton active={active === 'conductors'} onClick={() => onNavigate('conductors')} icon="◉">Conductors</NavButton><NavButton active={active === 'reviews'} onClick={() => onNavigate('reviews')} icon="!">Reviews</NavButton></nav><span className="side-label second">Manage</span><div className="sidebar-bottom"><span className="help-dot">?</span><div><strong>Needs attention?</strong><small>Review uncertain journeys</small></div></div><button className="sign-out" onClick={onSignOut}>Sign out</button></aside> }
function NavButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: string; children: string }) { return <button className={`side-link side-button ${active ? 'active' : ''}`} onClick={onClick}><i>{icon}</i>{children}</button> }
function Brand() { return <a className="dashboard-brand" href="/dashboard"><span className="brand-mark"><span /></span> PSV<span>Radar</span></a> }
function viewFromUrl(): View { const value = new URLSearchParams(window.location.search).get('view'); return value === 'trips' || value === 'vehicles' || value === 'conductors' || value === 'reviews' ? value : 'overview' }
function viewTitle(view: View) { return view === 'overview' ? 'Your fleet today' : view === 'trips' ? 'Trip log' : view === 'vehicles' ? 'Your vehicles' : view === 'conductors' ? 'Your crew' : 'Trips to check' }
function initials(name: string) { return name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-KE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) }
