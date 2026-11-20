import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './Dashboard.css'
import './FleetRoutes.css'

const API = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? window.location.origin : 'http://localhost:8000')
type View = 'overview' | 'trips' | 'vehicles' | 'conductors' | 'reviews' | 'cameras'
type Summary = { trips: number; expected_revenue_kes: number; declared_revenue_kes: number; variance_kes: number; open_review_cases: number; boardings: number }
type Trip = { trip_id: string; registration: string; route_name: string; direction: string; conductor_name?: string; status: string; expected_revenue_kes: number; declared_revenue_kes?: number }
type Review = { case_id: string; reason: string; registration?: string; route_name?: string; created_at: string; status?: string; event_id?: string; note?: string }
type Vehicle = { vehicle_id: string; registration: string; route_id?: string; route_name?: string; active: number }
type CameraDevice = { device_id: string; vehicle_id: string; door_id: string; name: string; active: number; online: boolean; last_seen_at?: string | null; last_event_at?: string | null; boardings_count: number; alightings_count: number }
type Route = { route_id: string; name: string; origin: string; destination: string; stages?: { stage_id: string; name: string; stage_order: number }[] }
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
  const [devices, setDevices] = useState<CameraDevice[]>([])
  const [user, setUser] = useState<User | null>(null)
  const [connected, setConnected] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [me, nextSummary, nextTrips, nextReviews, nextVehicles, nextRoutes, nextDevices] = await Promise.all([
        getJson<{ user: User }>('/auth/me'), getJson<Summary>('/operations/summary'),
        getJson<{ trips: Trip[] }>('/operations/trips'), getJson<{ reviews: Review[] }>('/operations/reviews'),
        getJson<{ vehicles: Vehicle[] }>('/operations/vehicles'), getJson<{ routes: Route[] }>('/operations/routes'),
        getJson<{ devices: CameraDevice[] }>('/operations/devices'),
      ])
      setUser(me.user); setSummary(nextSummary); setTrips(nextTrips.trips); setReviews(nextReviews.reviews)
      setVehicles(nextVehicles.vehicles); setRoutes(nextRoutes.routes); setDevices(nextDevices.devices); setConnected(true)
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
    {loading ? <div className="loading-state"><span className="status-dot" /> Loading operational data…</div> : <>{view === 'overview' && <Overview summary={summary} trips={trips} reviews={reviews} vehicles={vehicles} onNavigate={navigate} />}{view === 'trips' && <TripsView trips={trips} />}{view === 'vehicles' && <VehiclesView vehicles={vehicles} routes={routes} onSaved={load} />}{view === 'conductors' && <ConductorsView />}{view === 'reviews' && <ReviewsView reviews={reviews} onResolve={resolveReview} />}{view === 'cameras' && <CamerasView devices={devices} vehicles={vehicles} />}</>}
    <MobileNav active={view} onNavigate={navigate} />
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

function CamerasView({ devices, vehicles }: { devices: CameraDevice[]; vehicles: Vehicle[] }) {
  const [refreshedItems, setRefreshedItems] = useState<CameraDevice[] | null>(null)
  const [deviceId, setDeviceId] = useState('')
  const [vehicleId, setVehicleId] = useState('')
  const [deviceName, setDeviceName] = useState('Dedicated camera')
  const [deviceToken, setDeviceToken] = useState('')
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const items = refreshedItems ?? devices
  useEffect(() => {
    let mounted = true
    const refresh = async () => {
      try { const result = await getJson<{ devices: CameraDevice[] }>('/operations/devices'); if (mounted) setRefreshedItems(result.devices) }
      catch { /* Keep the last known camera state visible during temporary network loss. */ }
    }
    const timer = window.setInterval(() => void refresh(), 5000)
    return () => { mounted = false; window.clearInterval(timer) }
  }, [])
  async function provisionDevice(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); setBusy(true); setFormError(''); setDeviceToken('')
    try {
      const response = await fetch(`${API}/operations/devices`, { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ device_id: deviceId.trim(), vehicle_id: vehicleId, door_id: 'main-door', name: deviceName.trim() }) })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? 'Could not provision camera device.')
      setDeviceToken(payload.device_token); setDeviceId(''); setRefreshedItems(null)
    } catch (error) { setFormError(error instanceof Error ? error.message : 'Could not provision camera device.') }
    finally { setBusy(false) }
  }
  const onlineCount = items.filter((item) => item.online).length
  return <section className="panel full-panel cameras-panel">
    <div className="view-heading"><div><p className="eyebrow">Edge devices</p><h2>Camera monitor</h2><p>Camera health and crossing events update while a demo agent is running.</p></div><span className="count-badge">{onlineCount} online · {items.length} total</span></div>
    <form className="owner-form camera-setup-form" onSubmit={(event) => void provisionDevice(event)}>
      <label>Device ID<input required value={deviceId} onChange={(event) => setDeviceId(event.target.value)} placeholder="e.g. camera-matatu-01" /></label>
      <label>Vehicle<select required value={vehicleId} onChange={(event) => setVehicleId(event.target.value)}><option value="">Choose a vehicle</option>{vehicles.map((vehicle) => <option key={vehicle.vehicle_id} value={vehicle.vehicle_id}>{vehicle.registration}</option>)}</select></label>
      <label>Camera name<input required value={deviceName} onChange={(event) => setDeviceName(event.target.value)} /></label>
      <button className="primary-action" type="submit" disabled={busy || vehicles.length === 0}>{busy ? 'Setting up…' : 'Add camera'}</button>
    </form>
    {formError && <p className="camera-form-error" role="alert">{formError}</p>}
    {deviceToken && <div className="camera-token-notice" role="status"><strong>Camera added. Copy this device token now—it will not be shown again.</strong><code>{deviceToken}</code><small>Use this value as PSV_CAMERA_DEVICE_TOKEN on the camera computer.</small></div>}
    {items.length === 0 ? <div className="camera-empty"><strong>No camera devices yet</strong><p>Add a camera above, save its one-time token securely, then run the local webcam demo agent.</p></div> : <div className="camera-device-list">{items.map((device) => <article className="camera-device-card" key={device.device_id}>
      <div className="camera-device-heading"><span className={`camera-health-dot ${device.online ? 'online' : ''}`} /><div><strong>{device.name}</strong><span>{device.device_id} · {device.door_id}</span></div><em className={device.online ? 'online' : ''}>{device.online ? 'Online' : device.active ? 'Offline' : 'Disabled'}</em></div>
      <p className="camera-vehicle">Vehicle <strong>{device.vehicle_id}</strong></p>
      <div className="camera-event-stats"><span><strong>{device.boardings_count.toLocaleString('en-KE')}</strong> boardings</span><span><strong>{device.alightings_count.toLocaleString('en-KE')}</strong> alightings</span></div>
      <small className="camera-last-seen">{device.online ? 'Last heartbeat' : 'Last seen'}: {device.last_seen_at ? formatTime(device.last_seen_at) : 'No heartbeat received yet'}{device.last_event_at ? ` · Last crossing ${formatTime(device.last_event_at)}` : ''}</small>
    </article>)}</div>}
    <p className="camera-monitor-note">The dashboard receives event metadata and camera health only—no live video is uploaded.</p>
  </section>
}

function VehiclesView({ vehicles, routes, onSaved }: { vehicles: Vehicle[]; routes: Route[]; onSaved: () => Promise<void> }) {
  const [routeName, setRouteName] = useState('')
  const [origin, setOrigin] = useState('')
  const [destination, setDestination] = useState('')
  const [intermediateStops, setIntermediateStops] = useState<string[]>([])
  const [fareRules, setFareRules] = useState([{ boardingIndex: '0', alightingIndex: 'last', fare: '' }])
  const [routeBusy, setRouteBusy] = useState(false)
  const [routeMessage, setRouteMessage] = useState('')
  const [routeError, setRouteError] = useState('')
  const [vehicleMessage, setVehicleMessage] = useState('')
  const [vehicleError, setVehicleError] = useState('')
  const routeId = slugify(routeName).slice(0, 80)

  async function createRoute(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setRouteMessage('')
    setRouteError('')
    const routeStages = [origin.trim(), ...intermediateStops.map((stop) => stop.trim()).filter(Boolean), destination.trim()]
    if (new Set(routeStages.map((stop) => stop.toLocaleLowerCase())).size !== routeStages.length) {
      setRouteError('Each stop must have a different name.')
      return
    }
    const stages = routeStages.map((name, index) => ({
      stage_id: `${String(index + 1).padStart(2, '0')}-${slugify(name).slice(0, 60) || `stop-${index + 1}`}`,
      name,
    }))
    const configuredRules = fareRules.filter((rule) => rule.fare !== '')
    const farePairs = new Set<string>()
    const fares = []
    for (const rule of configuredRules) {
      const boardingIndex = Number(rule.boardingIndex)
      const alightingIndex = rule.alightingIndex === 'last' ? stages.length - 1 : Number(rule.alightingIndex)
      if (!stages[boardingIndex] || !stages[alightingIndex]) {
        setRouteError('A fare rule refers to a stop that was removed. Please update or remove that rule.')
        return
      }
      if (boardingIndex === alightingIndex) {
        setRouteError('A fare must be for travel between two different stops.')
        return
      }
      const pair = `${boardingIndex}:${alightingIndex}`
      if (farePairs.has(pair)) {
        setRouteError('Each stop pair can only have one fare rule.')
        return
      }
      farePairs.add(pair)
      fares.push({
        boarding_stage: stages[boardingIndex].stage_id,
        alighting_stage: stages[alightingIndex].stage_id,
        fare_kes: Number(rule.fare),
      })
    }
    setRouteBusy(true)
    try {
      const response = await fetch(`${API}/operations/routes`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ route_id: routeId, name: routeName.trim(), origin: origin.trim(), destination: destination.trim(), stages, fares }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? 'Could not create route.')
      setRouteMessage('Route created. It is now available in the vehicle setup form.')
      setRouteName(''); setOrigin(''); setDestination(''); setIntermediateStops([])
      setFareRules([{ boardingIndex: '0', alightingIndex: 'last', fare: '' }])
      await onSaved()
    } catch (requestError) {
      setRouteError(requestError instanceof Error ? requestError.message : 'Could not create route.')
    } finally {
      setRouteBusy(false)
    }
  }

  async function createVehicle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setVehicleMessage(''); setVehicleError('')
    const form = event.currentTarget
    const fields = new FormData(form)
    try {
      const response = await fetch(`${API}/operations/vehicles`, {
        method: 'POST', credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ vehicle_id: fields.get('vehicle_id'), registration: fields.get('registration'), route_id: fields.get('route_id') || null }),
      })
      const payload = await response.json().catch(() => ({}))
      if (!response.ok) throw new Error(payload.detail ?? 'Could not add vehicle.')
      form.reset(); setVehicleMessage('Vehicle added successfully.'); await onSaved()
    } catch (requestError) {
      setVehicleError(requestError instanceof Error ? requestError.message : 'Could not add vehicle.')
    }
  }

  const routeStages = [origin.trim(), ...intermediateStops.map((stop) => stop.trim()).filter(Boolean), destination.trim()].filter(Boolean)
  return <section className="owner-columns fleet-layout">
    <div className="fleet-setup-stack">
      <article className="panel full-panel">
        <div className="view-heading"><div><p className="eyebrow">Fleet routes</p><h2>Routes</h2><p>Routes define the stops and fare stages used to calculate journeys.</p></div><span className="count-badge">{routes.length}</span></div>
        {routes.length ? <div className="vehicle-list">{routes.map((route) => <div className="vehicle-row route-row" key={route.route_id}><span className="vehicle-icon">↗</span><div><strong>{route.name}</strong><span>{route.origin} → {route.destination} · {route.stages?.length ?? 0} stages</span></div></div>)}</div> : <p className="empty-state">No routes yet. Create one to make it available for vehicle assignments.</p>}
      </article>
      <article className="panel full-panel">
        <div className="view-heading"><div><p className="eyebrow">Fleet</p><h2>Vehicles</h2><p>Keep vehicle assignments ready for trip and camera operations.</p></div><span className="count-badge">{vehicles.length}</span></div>
        <div className="vehicle-list">{vehicles.length === 0 ? <p className="empty-state">No vehicles registered yet.</p> : vehicles.map((vehicle) => <div className="vehicle-row" key={vehicle.vehicle_id}><span className="vehicle-icon">▣</span><div><strong>{vehicle.registration}</strong><span>{vehicle.vehicle_id} · {vehicle.route_name ?? 'No route assigned'}</span></div><em className={vehicle.active ? 'active' : ''}>{vehicle.active ? 'Active' : 'Inactive'}</em></div>)}</div>
      </article>
    </div>
    <div className="fleet-setup-stack">
      <article className="panel full-panel">
        <p className="eyebrow">Route setup</p><h2>Add a route</h2>
        <p className="form-intro">Stops are ordered from origin to destination. Route ID: <code>{routeId || 'generated-from-name'}</code></p>
        <form className="owner-form" onSubmit={(event) => void createRoute(event)}>
          <label>Route name<input value={routeName} onChange={(event) => setRouteName(event.target.value)} maxLength={120} required placeholder="e.g. Rongai – CBD" /></label>
          <div className="route-endpoints"><label>Origin<input value={origin} onChange={(event) => setOrigin(event.target.value)} maxLength={120} required placeholder="Starting point" /></label><label>Destination<input value={destination} onChange={(event) => setDestination(event.target.value)} maxLength={120} required placeholder="Final stop" /></label></div>
          <fieldset className="route-stops"><legend>Intermediate stops <span className="optional">Optional · in travel order</span></legend>
            {intermediateStops.map((stop, index) => <div className="route-stop-row" key={index}><label className="sr-only" htmlFor={`route-stop-${index}`}>Stop {index + 1}</label><input id={`route-stop-${index}`} value={stop} onChange={(event) => setIntermediateStops((items) => items.map((item, itemIndex) => itemIndex === index ? event.target.value : item))} maxLength={120} placeholder={`Stop ${index + 1}`} /><button type="button" className="remove-stop" aria-label={`Remove stop ${index + 1}`} onClick={() => setIntermediateStops((items) => items.filter((_, itemIndex) => itemIndex !== index))}>×</button></div>)}
            <button type="button" className="add-stop" onClick={() => setIntermediateStops((items) => [...items, ''])}>+ Add stop</button>
          </fieldset>
          <fieldset className="route-stops fare-rules"><legend>Fare rules <span className="optional">Optional, in KES</span></legend>
            <p className="route-hint">Add a fare for each stop pair you charge differently. Unconfigured journeys are sent for review instead of receiving a guessed fare.</p>
            {fareRules.map((rule, index) => <div className="fare-rule-row" key={index}>
              <label className="sr-only" htmlFor={`fare-from-${index}`}>Boarding stop</label><select id={`fare-from-${index}`} value={rule.boardingIndex} onChange={(event) => setFareRules((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, boardingIndex: event.target.value } : item))}>{routeStages.map((stage, stageIndex) => <option key={stageIndex} value={stageIndex}>{stage || `Stop ${stageIndex + 1}`}</option>)}</select>
              <span aria-hidden="true">→</span>
              <label className="sr-only" htmlFor={`fare-to-${index}`}>Alighting stop</label><select id={`fare-to-${index}`} value={rule.alightingIndex === 'last' ? String(Math.max(routeStages.length - 1, 1)) : rule.alightingIndex} onChange={(event) => setFareRules((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, alightingIndex: event.target.value } : item))}>{routeStages.map((stage, stageIndex) => <option key={stageIndex} value={stageIndex}>{stage || `Stop ${stageIndex + 1}`}</option>)}</select>
              <label className="sr-only" htmlFor={`fare-amount-${index}`}>Fare in Kenyan shillings</label><input id={`fare-amount-${index}`} type="number" min="0" step="1" inputMode="numeric" value={rule.fare} onChange={(event) => setFareRules((items) => items.map((item, itemIndex) => itemIndex === index ? { ...item, fare: event.target.value } : item))} placeholder="KES" />
              <button type="button" className="remove-stop" aria-label="Remove fare rule" onClick={() => setFareRules((items) => items.filter((_, itemIndex) => itemIndex !== index))}>×</button>
            </div>)}
            <button type="button" className="add-stop" onClick={() => setFareRules((items) => [...items, { boardingIndex: '0', alightingIndex: 'last', fare: '' }])}>+ Add fare rule</button>
          </fieldset>
          {routeError && <p className="form-error" role="alert">{routeError}</p>}{routeMessage && <p className="form-success" role="status">{routeMessage}</p>}
          <button className="primary-action" type="submit" disabled={routeBusy || !routeId}>{routeBusy ? 'Creating route…' : 'Create route'} <span>↗</span></button>
        </form>
      </article>
      <article className="panel full-panel">
        <p className="eyebrow">Fleet setup</p><h2>Add a vehicle</h2>
        <form className="owner-form" onSubmit={(event) => void createVehicle(event)}>
          <label>Vehicle ID<input name="vehicle_id" required placeholder="psv-van-01" /></label>
          <label>Registration<input name="registration" required placeholder="KDA 418M" /></label>
          <label>Default route<select name="route_id" required={routes.length > 0} disabled={routes.length === 0}><option value="" disabled={routes.length > 0}>{routes.length ? 'Choose a route' : 'Create a route first'}</option>{routes.map((route) => <option key={route.route_id} value={route.route_id}>{route.name}</option>)}</select></label>
          {vehicleError && <p className="form-error" role="alert">{vehicleError}</p>}{vehicleMessage && <p className="form-success" role="status">{vehicleMessage}</p>}
          <button className="primary-action" type="submit">Add vehicle <span>↗</span></button>
        </form>
      </article>
    </div>
  </section>
}

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
function Sidebar({ active, onNavigate, onSignOut }: { active: View; onNavigate: (view: View) => void; onSignOut: () => void }) { return <aside className="sidebar"><Brand /><nav aria-label="Owner workspace"><span className="side-label">Workspace</span><NavButton active={active === 'overview'} onClick={() => onNavigate('overview')} icon="⌂">Overview</NavButton><NavButton active={active === 'trips'} onClick={() => onNavigate('trips')} icon="↗">Trips</NavButton><NavButton active={active === 'vehicles'} onClick={() => onNavigate('vehicles')} icon="▣">Vehicles</NavButton><NavButton active={active === 'cameras'} onClick={() => onNavigate('cameras')} icon="◉">Cameras</NavButton><NavButton active={active === 'conductors'} onClick={() => onNavigate('conductors')} icon="♙">Conductors</NavButton><NavButton active={active === 'reviews'} onClick={() => onNavigate('reviews')} icon="!">Reviews</NavButton></nav><span className="side-label second">Manage</span><div className="sidebar-bottom"><span className="help-dot">?</span><div><strong>Needs attention?</strong><small>Review uncertain journeys</small></div></div><button className="sign-out" onClick={onSignOut}>Sign out</button></aside> }
function NavButton({ active, onClick, icon, children }: { active: boolean; onClick: () => void; icon: string; children: string }) { return <button className={`side-link side-button ${active ? 'active' : ''}`} onClick={onClick} aria-current={active ? 'page' : undefined}><i aria-hidden="true">{icon}</i>{children}</button> }
function MobileNav({ active, onNavigate }: { active: View; onNavigate: (view: View) => void }) { const items: { id: View; label: string; icon: string }[] = [{ id: 'overview', label: 'Home', icon: '⌂' }, { id: 'trips', label: 'Trips', icon: '↗' }, { id: 'vehicles', label: 'Vehicles', icon: '▣' }, { id: 'cameras', label: 'Cameras', icon: '◉' }, { id: 'conductors', label: 'Crew', icon: '♙' }, { id: 'reviews', label: 'Review', icon: '!' }]; return <nav className="mobile-dashboard-nav" aria-label="Owner dashboard sections">{items.map((item) => <button key={item.id} className={active === item.id ? 'active' : ''} onClick={() => onNavigate(item.id)} aria-current={active === item.id ? 'page' : undefined} aria-label={item.id === active ? `${item.label}, current section` : item.label}><span aria-hidden="true">{item.icon}</span><small>{item.label}</small></button>)}</nav> }
function Brand() { return <a className="dashboard-brand" href="/dashboard"><span className="brand-mark"><span /></span> PSV<span>Radar</span></a> }
function viewFromUrl(): View { const value = new URLSearchParams(window.location.search).get('view'); return value === 'trips' || value === 'vehicles' || value === 'conductors' || value === 'reviews' || value === 'cameras' ? value : 'overview' }
function viewTitle(view: View) { return view === 'overview' ? 'Your fleet today' : view === 'trips' ? 'Trip log' : view === 'vehicles' ? 'Your vehicles' : view === 'conductors' ? 'Your crew' : view === 'cameras' ? 'Camera monitor' : 'Trips to check' }
function initials(name: string) { return name.split(/\s+/).map((part) => part[0]).join('').slice(0, 2).toUpperCase() }
function formatTime(value: string) { const date = new Date(value); return Number.isNaN(date.getTime()) ? value : date.toLocaleString('en-KE', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' }) }
function slugify(value: string) { return value.normalize('NFKD').replace(/[\u0300-\u036f]/g, '').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '') }
