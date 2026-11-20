import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import './Conductor.css'
import './Camera.css'

const API = import.meta.env.VITE_API_URL ?? (import.meta.env.PROD ? window.location.origin : 'http://localhost:8000')
type TripStage = { stage_id: string; name: string; stage_order: number }
type Trip = { trip_id: string; route_id: string; registration: string; route_name: string; direction: string; status: string; expected_revenue_kes: number; boardings_count: number; declared_revenue_kes: number | null; current_stage_id: string | null; current_stage_name: string | null; stages: TripStage[] }
type TripVehicle = { vehicle_id: string; registration: string; route_id: string; route_name: string; origin: string; destination: string }

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, credentials: 'include' })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) throw new Error(payload.detail ?? 'Could not complete the request. Please try again.')
  return payload as T
}

export default function Conductor() {
  const [trip, setTrip] = useState<Trip | null>(null)
  const [vehicles, setVehicles] = useState<TripVehicle[]>([])
  const [vehicleId, setVehicleId] = useState('')
  const [direction, setDirection] = useState<'outbound' | 'return'>('outbound')
  const [loading, setLoading] = useState(true)
  const [busy, setBusy] = useState(false)
  const [cash, setCash] = useState('')
  const [mpesa, setMpesa] = useState('')
  const [other, setOther] = useState('')
  const [notes, setNotes] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')

  async function loadTrips() {
    setLoading(true)
    setError('')
    try {
      const data = await request<{ trips: Trip[] }>('/operations/trips')
      const currentTrip = data.trips.find((item) => item.status === 'active') ?? data.trips.find((item) => item.status === 'scheduled') ?? null
      setTrip(currentTrip)
      if (!currentTrip) {
        const options = await request<{ vehicles: TripVehicle[] }>('/operations/trip-options')
        setVehicles(options.vehicles)
        setVehicleId((current) => options.vehicles.some((vehicle) => vehicle.vehicle_id === current) ? current : options.vehicles[0]?.vehicle_id ?? '')
      }
    } catch (loadError) {
      setError(loadError instanceof Error ? loadError.message : 'Could not load your assigned trip.')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { void loadTrips() }, [])

  async function createTrip(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    const vehicle = vehicles.find((item) => item.vehicle_id === vehicleId)
    if (!vehicle) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      await request('/operations/trips', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ trip_id: `trip-${crypto.randomUUID()}`, vehicle_id: vehicle.vehicle_id, route_id: vehicle.route_id, direction }),
      })
      setMessage('Trip created. Start it when you are ready to depart.')
      await loadTrips()
    } catch (createError) {
      setError(createError instanceof Error ? createError.message : 'Could not create your trip.')
    } finally {
      setBusy(false)
    }
  }

  async function startTrip() {
    if (!trip) return
    setBusy(true)
    setError('')
    try {
      await request(`/operations/trips/${encodeURIComponent(trip.trip_id)}/start`, { method: 'POST' })
      setTrip({ ...trip, status: 'active' })
      setMessage('Trip started. The provisioned camera will connect through its device credentials.')
    } catch (startError) {
      setError(startError instanceof Error ? startError.message : 'Could not start this trip.')
      await loadTrips()
    } finally {
      setBusy(false)
    }
  }

  async function changeStage(stageId: string) {
    if (!trip || !stageId) return
    const stage = trip.stages.find((item) => item.stage_id === stageId)
    if (!stage) return
    setBusy(true)
    setError('')
    try {
      await request(`/operations/trips/${encodeURIComponent(trip.trip_id)}/stage`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ stage_id: stageId }),
      })
      setTrip({ ...trip, current_stage_id: stage.stage_id, current_stage_name: stage.name })
      setMessage(`Current stage updated to ${stage.name}.`)
    } catch (stageError) {
      setError(stageError instanceof Error ? stageError.message : 'Could not update the current stage.')
    } finally {
      setBusy(false)
    }
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!trip) return
    setBusy(true)
    setError('')
    setMessage('')
    try {
      const result = await request<{ declared_revenue_kes: number; status: string }>(`/operations/trips/${encodeURIComponent(trip.trip_id)}/declaration`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ cash_kes: Number(cash || 0), mpesa_kes: Number(mpesa || 0), other_kes: Number(other || 0), notes: notes.trim() || null }),
      })
      setTrip({ ...trip, status: result.status, declared_revenue_kes: result.declared_revenue_kes })
      setMessage('Collection submitted and trip closed successfully.')
      await loadTrips()
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : 'Collection was not saved. Please retry.')
    } finally {
      setBusy(false)
    }
  }

  const total = Number(cash || 0) + Number(mpesa || 0) + Number(other || 0)
  const canClose = trip && (trip.status === 'active' || trip.status === 'ended') && trip.declared_revenue_kes == null

  return <main className="conductor-page">
    <header className="conductor-header"><a className="dashboard-brand" href="/"><span className="brand-mark"><span /></span> PSV<span>Radar</span></a><span className="conductor-shift-label"><i /> Conductor portal</span><span className="conductor-avatar" aria-hidden="true">PS</span></header>
    <section className="conductor-content">
      <div className="conductor-greeting"><p className="eyebrow">Conductor · Trip operations</p><h1>{trip?.status === 'active' ? 'Your run is underway.' : trip ? 'Your next run.' : 'Ready for your next run?'}</h1><p className="conductor-lede">Start a trip with a prepared vehicle, track recorded activity, and submit the collection at handover.</p></div>

      {loading && <p role="status">Loading your assigned trip…</p>}
      {!loading && !trip && <>
        {vehicles.length ? <form className="collection-form" onSubmit={(event) => void createTrip(event)}>
          <div className="form-heading"><div><p className="eyebrow">New run</p><h2>Create your trip</h2></div></div>
          <p className="collection-hint">Choose a vehicle prepared by your PSV owner. Your account will be assigned to this trip.</p>
          <label>Vehicle and route<select value={vehicleId} onChange={(event) => setVehicleId(event.target.value)} required><option value="" disabled>Select a vehicle</option>{vehicles.map((vehicle) => <option key={vehicle.vehicle_id} value={vehicle.vehicle_id}>{vehicle.registration} · {vehicle.route_name} ({vehicle.origin} → {vehicle.destination})</option>)}</select></label>
          <label>Direction<select value={direction} onChange={(event) => setDirection(event.target.value as 'outbound' | 'return')}><option value="outbound">Outbound</option><option value="return">Return</option></select></label>
          <button className="submit-collection" type="submit" disabled={busy || !vehicleId}>{busy ? 'Creating trip…' : 'Create trip'} <span>↗</span></button>
        </form> : <article className="current-trip"><div><span className="eyebrow">Fleet setup needed</span><h2>No vehicles ready for a trip</h2><p>Ask your PSV owner to configure a route, assign it to a vehicle, and provision that vehicle’s camera.</p></div><button type="button" className="submit-collection" disabled={busy} onClick={() => void loadTrips()}>Refresh</button></article>}
      </>}
      {trip && <>
        <article className="current-trip"><div><span className="eyebrow">Assigned run · {trip.direction === 'return' ? 'return leg' : 'outbound leg'}</span><h2>{trip.registration}</h2><p><span className="route-arrow">●</span> {trip.route_name}</p></div><span className="trip-live"><i /> {trip.status === 'active' ? 'In progress' : trip.status === 'scheduled' ? 'Scheduled' : 'Ended'}</span></article>

        {trip.status === 'scheduled' && <button type="button" className="submit-collection" disabled={busy} onClick={() => void startTrip()}>{busy ? 'Starting…' : 'Start this trip'}</button>}

        {trip.status === 'active' && <label className="trip-stage-picker">Current route stage<select aria-label="Current route stage" value={trip.current_stage_id ?? ''} onChange={(event) => void changeStage(event.target.value)} disabled={busy || trip.stages.length === 0}><option value="" disabled>Select current stage</option>{trip.stages.map((stage) => <option key={stage.stage_id} value={stage.stage_id}>{stage.name}</option>)}</select><small>The camera uses this stage for new crossing events.</small></label>}

        <div className="camera-control"><div><p className="eyebrow">Camera connection</p><h2>Camera connects automatically</h2><p>The owner provisions the vehicle camera. Once this trip is active, its edge agent authenticates with the device credentials—there is no session token to copy here.</p></div></div>

        <div className="conductor-stats"><div><span>Boardings recorded</span><strong>{trip.boardings_count.toLocaleString('en-KE')}</strong><small>Events received for this trip</small></div><div><span>Expected fares</span><strong>KES {trip.expected_revenue_kes.toLocaleString('en-KE')}</strong><small>From completed journeys</small></div></div>

        {canClose ? <form className="collection-form" onSubmit={(event) => void submit(event)}>
          <div className="form-heading"><div><p className="eyebrow">End-of-run collection</p><h2>What did you collect?</h2></div><span className="total-pill">KES {total.toLocaleString('en-KE')}</span></div>
          <p className="collection-hint">Submitting records the handover and closes this trip together.</p>
          <label>Cash<input inputMode="numeric" type="number" min="0" step="1" value={cash} onChange={(event) => setCash(event.target.value)} placeholder="KES 0" required /></label>
          <label>M-Pesa<input inputMode="numeric" type="number" min="0" step="1" value={mpesa} onChange={(event) => setMpesa(event.target.value)} placeholder="KES 0" required /></label>
          <label>Other payments<input inputMode="numeric" type="number" min="0" step="1" value={other} onChange={(event) => setOther(event.target.value)} placeholder="KES 0" required /></label>
          <label>Handover note <span className="optional">Optional</span><textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Anything to note about this collection?" rows={3} /></label>
          <button className="submit-collection" type="submit" disabled={busy}>{busy ? 'Submitting…' : 'Submit run collection'} <span>↗</span></button>
        </form> : trip.status === 'ended' || trip.status === 'reconciled' ? <p className="conductor-message" role="status">This trip has already been closed out.</p> : null}
      </>}
      {!loading && error && !trip && <p className="conductor-message" role="alert">{error}</p>}
      {trip && error && <p className="conductor-message" role="alert">{error}</p>}
      {message && <p className="conductor-message" role="status">{message}</p>}
      <a className="conductor-help" href="/dashboard">← Back to fleet dashboard</a>
    </section>
  </main>
}
