import { useEffect, useMemo, useState } from 'react';
import { MapContainer, Marker, Polyline, Popup, TileLayer, CircleMarker } from 'react-leaflet';
import L from 'leaflet';
import {
  PackageCheck,
  PackagePlus,
  Pause,
  Play,
  RotateCcw,
  Route,
  StepForward,
  Truck,
  Timer,
  MapPin,
  Wifi,
  WifiOff,
  Building2,
  Clock,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
const CENTER = [41.1956, 32.6227];
const SPEED_OPTIONS = [1, 2, 4, 8, 16];

function markerIcon(color, status) {
  return L.divIcon({
    className: `courier-marker ${status}`,
    html: `<span style="background:${color};color:${color}"></span>`,
    iconSize: [24, 24],
    iconAnchor: [12, 12],
  });
}

async function api(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `HTTP ${response.status}`);
  }
  return response.json();
}

function statusLabel(status) {
  const labels = {
    idle: 'hazir',
    moving: 'yolda',
    servicing_delivery: 'teslimat',
    servicing_return: 'iade alma',
    done: 'tamamlandi',
  };
  return labels[status] ?? status;
}

function loadBreakdown(courier) {
  const deliveryLoad = courier.route
    .filter((s) => s.kind === 'delivery' && s.status === 'pending')
    .reduce((t, s) => t + s.desi, 0);
  return { deliveryLoad, returnLoad: Math.max(0, courier.current_load - deliveryLoad) };
}

export default function App() {
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const [seed, setSeed] = useState(42);
  const [capacities, setCapacities] = useState('100,100,100');
  const [returnDesi, setReturnDesi] = useState(15);
  const [busy, setBusy] = useState(false);
  const [connected, setConnected] = useState(false);
  const [endHour, setEndHour] = useState(18);

  const vehicles = useMemo(
    () =>
      capacities
        .split(',')
        .map((v) => Number(v.trim()))
        .filter((v) => Number.isFinite(v) && v > 0)
        .map((capacity, i) => ({ id: `vehicle-${i + 1}`, capacity_desi: capacity })),
    [capacities],
  );

  async function run(action) {
    setBusy(true);
    setError('');
    try {
      setState(await action());
      setConnected(true);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const t = setInterval(async () => {
      try {
        setState(await api('/api/sim/state'));
        setConnected(true);
      } catch {
        setConnected(false);
      }
    }, 1000);
    return () => clearInterval(t);
  }, []);

  const started = Boolean(state?.started);
  const running = Boolean(state?.running);

  const workingHoursEndS = Math.max(1, (endHour - 10) * 3600);
  const totalCapacity = vehicles.reduce((s, v) => s + v.capacity_desi, 0);
  const simElapsed = state?.sim_elapsed_seconds ?? 0;
  const simEnd = state?.working_hours_end_s ?? workingHoursEndS;
  const simProgress = simEnd > 0 ? Math.min(1, simElapsed / simEnd) : 0;
  const nearEod = simProgress > 1 - 0.2;
  const hubWaiting = state?.hub_cargo_pool?.filter((c) => c.status === 'waiting') ?? [];
  const hubAssigned = state?.hub_cargo_pool?.filter((c) => c.status === 'assigned') ?? [];

  return (
    <main className="shell">
      {/* LEFT PANEL */}
      <aside className="panel left-panel">
        <header>
          <div>
            <p>Karabuk Merkez — OSM graph</p>
            <h1>Dinamik Kargo Rotalama</h1>
          </div>
          <div className="header-badges">
            <span className={`status ${running ? 'live' : ''}`}>
              {running ? 'Canli' : started ? 'Duraklatildi' : 'Hazir'}
            </span>
            <span className={`conn-badge ${connected ? 'conn-ok' : 'conn-fail'}`}>
              {connected ? <Wifi size={11} /> : <WifiOff size={11} />}
              {connected ? 'Bagli' : 'Baglanti yok'}
            </span>
          </div>
        </header>

        <section className="meta-row">
          <span>Tick {state?.tick ?? 0}</span>
          <span>{state?.speed_kmh ?? 70} km/s</span>
          <span>Sim {state?.speed_multiplier ?? 2}x</span>
          <span>{totalCapacity} desi toplam kapasite</span>
          <span>{state?.graph_source ?? 'graph bekleniyor'}</span>
        </section>

        {/* Simulated working-hours clock */}
        <section className="work-hours-section">
          <div className="sim-clock-display">
            <Clock size={15} />
            <span className={`sim-clock-now ${nearEod ? 'wh-eod-text' : ''}`}>
              {state?.sim_clock ?? '10:00'}
            </span>
            <span className="sim-clock-sep">—</span>
            <span className="sim-clock-end">{state?.end_clock ?? `${endHour}:00`}</span>
            {running && <span className="sim-running-dot" title="Calisiyor" />}
          </div>
          <div className="work-hours-row">
            <span className="wh-label">10:00</span>
            <div className="work-hours-bar">
              <span
                className={`wh-fill ${nearEod ? 'wh-eod' : ''}`}
                style={{ width: `${Math.max(0, simProgress * 100)}%` }}
              />
            </div>
            <span className="wh-label">{state?.end_clock ?? `${endHour}:00`}</span>
          </div>
          {nearEod && <p className="cap-warning">Mesai bitisine yaklasiliyor.</p>}
        </section>

        {/* Vehicle + seed config */}
        <section className="controls">
          <label>
            Arac desileri
            <input value={capacities} onChange={(e) => setCapacities(e.target.value)} />
          </label>
          <label>
            Seed
            <input type="number" value={seed} onChange={(e) => setSeed(Number(e.target.value))} />
          </label>
          <label>
            Mesai bitis
            <input
              type="number"
              value={endHour}
              min={11}
              max={24}
              onChange={(e) => setEndHour(Number(e.target.value))}
            />
          </label>
        </section>

        {/* Route planning */}
        <section style={{ display: 'grid' }}>
          <button
            className="btn-plan"
            onClick={() =>
              run(() =>
                api('/api/sim/start', {
                  method: 'POST',
                  body: JSON.stringify({ seed, vehicles, working_hours_end_s: workingHoursEndS }),
                }),
              )
            }
            disabled={busy || vehicles.length === 0}
          >
            <Route size={18} /> Rota Planla
          </button>
        </section>

        {/* Playback controls */}
        <section className="controls run-controls">
          <button
            className="btn-start"
            onClick={() => run(() => api('/api/sim/run', { method: 'POST' }))}
            disabled={busy || !started || running}
          >
            <Play size={18} /> Baslat
          </button>
          <button onClick={() => run(() => api('/api/sim/pause', { method: 'POST' }))} disabled={busy || !started || !running}>
            <Pause size={18} /> Duraklat
          </button>
          <button onClick={() => run(() => api('/api/sim/tick', { method: 'POST' }))} disabled={busy || !started || running}>
            <StepForward size={18} /> 5 sn
          </button>
        </section>

        <section className="speed-control">
          {SPEED_OPTIONS.map((m) => (
            <button
              key={m}
              className={state?.speed_multiplier === m ? 'active' : ''}
              onClick={() => run(() => api('/api/sim/speed', { method: 'POST', body: JSON.stringify({ multiplier: m }) }))}
              disabled={busy}
            >
              {m}x
            </button>
          ))}
        </section>

        {error && <div className="error">{error}</div>}

        {/* Vehicle cards */}
        <section>
          <h2>
            <Truck size={18} /> Araclar
          </h2>
          <div className="cards">
            {state?.couriers?.map((courier) => {
              const pct = Math.round((courier.current_load / courier.capacity_desi) * 100);
              const { deliveryLoad, returnLoad } = loadBreakdown(courier);
              const deliveries = courier.route.filter((s) => s.kind === 'delivery');
              const pending = courier.route.filter((s) => s.status === 'pending' && s.kind !== 'hub').length;
              return (
                <article className="card" key={courier.id}>
                  <div className="card-title">
                    <span className="dot" style={{ background: courier.color }} />
                    <strong>{courier.name}</strong>
                    <span>
                      {courier.current_load}/{courier.capacity_desi} desi
                    </span>
                  </div>
                  <div className="bar">
                    <span style={{ width: `${Math.min(100, pct)}%`, background: courier.color }} />
                  </div>
                  <div className="load-split">
                    <span>Teslimat {deliveryLoad} desi</span>
                    <span>Iade {returnLoad} desi</span>
                  </div>
                  <p>{pending} bekleyen durak</p>
                  <p>
                    {statusLabel(courier.movement_status)}
                    {courier.service_remaining_seconds > 0 ? ` — ${courier.service_remaining_seconds} sn` : ''}
                  </p>
                  {courier.route_error && <p className="route-error">{courier.route_error}</p>}

                  {/* Cargo manifest */}
                  {deliveries.length > 0 && (
                    <div className="cargo-manifest">
                      <div className="manifest-header">Yukleme Sirasi</div>
                      {deliveries.map((stop, idx) => (
                        <div key={stop.id} className={`manifest-entry ${stop.status}`}>
                          <span className="manifest-order">{idx + 1}</span>
                          <span className="manifest-label">{stop.label}</span>
                          <span className="manifest-desi">{stop.desi} desi</span>
                          <span className="manifest-check">{stop.status === 'done' ? '✓' : '○'}</span>
                        </div>
                      ))}
                    </div>
                  )}
                </article>
              );
            })}
          </div>
        </section>
      </aside>

      {/* MAP */}
      <section className="map-wrap">
        <MapContainer center={CENTER} zoom={13} scrollWheelZoom className="map">
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {state?.couriers?.map((courier) =>
            courier.polyline?.length ? (
              <Polyline
                key={`${courier.id}-shadow`}
                positions={courier.polyline}
                pathOptions={{ color: courier.color, weight: 12, opacity: 0.18, lineCap: 'round', lineJoin: 'round' }}
              />
            ) : null,
          )}
          {state?.couriers?.map((courier) =>
            courier.polyline?.length ? (
              <Polyline
                key={`${courier.id}-route`}
                positions={courier.polyline}
                pathOptions={{
                  color: courier.color,
                  weight: 5,
                  opacity: 0.92,
                  lineCap: 'round',
                  lineJoin: 'round',
                  className: `route-line ${courier.movement_status === 'moving' ? 'moving' : ''}`,
                }}
              />
            ) : null,
          )}
          {state?.couriers?.map((courier) => (
            <Marker key={courier.id} position={[courier.lat, courier.lon]} icon={markerIcon(courier.color, courier.movement_status)}>
              <Popup>
                <strong>{courier.name}</strong>
                <br />
                {courier.current_load}/{courier.capacity_desi} desi
                <br />
                {statusLabel(courier.movement_status)}
              </Popup>
            </Marker>
          ))}
          {state?.couriers?.flatMap((courier) =>
            courier.route.map((stop) => (
              <CircleMarker
                key={stop.id}
                center={[stop.lat, stop.lon]}
                radius={stop.kind === 'return' ? 8 : 6}
                pathOptions={{
                  color: stop.kind === 'return' ? '#db2777' : stop.kind === 'hub' ? '#111827' : courier.color,
                  fillOpacity: stop.status === 'done' ? 0.25 : 0.8,
                }}
              >
                <Popup>
                  <strong>{stop.label}</strong>
                  <br />
                  {stop.kind} — {stop.desi} desi — {stop.status}
                  {stop.cargo_id && (
                    <>
                      <br />
                      <small>{stop.cargo_id}</small>
                    </>
                  )}
                </Popup>
              </CircleMarker>
            )),
          )}
          {state?.pending_returns?.map((job) => (
            <CircleMarker
              key={job.id}
              center={[job.lat, job.lon]}
              radius={9}
              pathOptions={{
                color: job.deferred ? '#ca8a04' : '#dc2626',
                fillColor: job.deferred ? '#fde68a' : '#fca5a5',
                fillOpacity: 0.95,
              }}
            >
              <Popup>
                <strong>{job.deferred ? 'Oncelikli iade' : 'Havuzdaki iade'}</strong>
                <br />
                {job.desi} desi
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </section>

      {/* RIGHT PANEL */}
      <aside className="panel right-panel">
        <section className="controls two">
          <label>
            Iade desi
            <input type="number" value={returnDesi} onChange={(e) => setReturnDesi(Number(e.target.value))} />
          </label>
          <button
            onClick={() =>
              run(() => api('/api/returns', { method: 'POST', body: JSON.stringify({ desi: returnDesi }) }))
            }
            disabled={busy || !started}
          >
            <PackagePlus size={18} /> Iade Ekle
          </button>
        </section>

        {/* Hub cargo pool */}
        <section>
          <h2>
            <Building2 size={18} /> Hub Kargo Havuzu
          </h2>
          <div className="meta-row" style={{ marginBottom: 8 }}>
            <span>Bekliyor: {hubWaiting.length}</span>
            <span>Atandi: {hubAssigned.length}</span>
          </div>
          <div className="pool">
            {hubWaiting.length === 0 && <p>Hub'da bekleyen kargo yok.</p>}
            {hubWaiting.map((cargo) => (
              <article className="pool-item" key={cargo.id}>
                <div>
                  <strong>{cargo.desi} desi</strong>
                  <small>{cargo.label}</small>
                </div>
                <span>Hub'da bekliyor</span>
              </article>
            ))}
          </div>
        </section>

        <section>
          <h2>
            <Timer size={18} /> Iade Havuzu
          </h2>
          <div className="pool">
            {(state?.pending_returns?.length ?? 0) === 0 && <p>Bekleyen iade yok.</p>}
            {state?.pending_returns?.map((job) => (
              <article className={`pool-item ${job.deferred ? 'deferred' : ''}`} key={job.id}>
                <div>
                  <strong>{job.desi} desi</strong>
                  {job.deferred && <small>Oncelikli</small>}
                </div>
                <span>{job.message}</span>
              </article>
            ))}
          </div>
        </section>

        <section>
          <h2>
            <PackageCheck size={18} /> Tamamlanan Iadeler
          </h2>
          <div className="pool">
            {(state?.completed_returns?.length ?? 0) === 0 && <p>Tamamlanan iade yok.</p>}
            {state?.completed_returns?.map((job) => (
              <article className="pool-item completed" key={job.id}>
                <div>
                  <strong>{job.desi} desi</strong>
                  <small>{job.assigned_courier_id}</small>
                </div>
                <span>{job.message}</span>
              </article>
            ))}
          </div>
        </section>

        <section>
          <h2>
            <MapPin size={18} /> Olay Akisi
          </h2>
          <div className="log">
            {(state?.messages ?? [])
              .slice()
              .reverse()
              .map((msg, i) => (
                <p key={`${msg}-${i}`}>{msg}</p>
              ))}
          </div>
        </section>
      </aside>
    </main>
  );
}
