import { useEffect, useMemo, useState } from 'react';
import { MapContainer, Marker, Polyline, Popup, TileLayer, CircleMarker } from 'react-leaflet';
import L from 'leaflet';
import { PackageCheck, PackagePlus, Pause, Play, RotateCcw, StepForward, Truck, Timer, MapPin } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
const CENTER = [41.1956, 32.6227];
const SPEED_OPTIONS = [1, 2, 4, 8];

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
    servicing_delivery: 'teslimat bekleme',
    servicing_return: 'iade bekleme',
    done: 'tamamlandi',
  };
  return labels[status] ?? status;
}

function loadBreakdown(courier) {
  const deliveryLoad = courier.route
    .filter((stop) => stop.kind === 'delivery' && stop.status === 'pending')
    .reduce((total, stop) => total + stop.desi, 0);
  return {
    deliveryLoad,
    returnLoad: Math.max(0, courier.current_load - deliveryLoad),
  };
}

export default function App() {
  const [state, setState] = useState(null);
  const [error, setError] = useState('');
  const [seed, setSeed] = useState(42);
  const [capacities, setCapacities] = useState('100,100,100');
  const [returnDesi, setReturnDesi] = useState(15);
  const [busy, setBusy] = useState(false);

  const vehicles = useMemo(
    () =>
      capacities
        .split(',')
        .map((item) => Number(item.trim()))
        .filter((item) => Number.isFinite(item) && item > 0)
        .map((capacity, index) => ({ id: `vehicle-${index + 1}`, capacity_desi: capacity })),
    [capacities],
  );

  async function run(action) {
    setBusy(true);
    setError('');
    try {
      setState(await action());
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  useEffect(() => {
    const timer = setInterval(async () => {
      try {
        setState(await api('/api/sim/state'));
      } catch {
        // Backend may not be running yet; keep the current screen stable.
      }
    }, 1000);
    return () => clearInterval(timer);
  }, []);

  const started = Boolean(state?.started);
  const running = Boolean(state?.running);

  return (
    <main className="shell">
      <aside className="panel left-panel">
        <header>
          <div>
            <p>Karabuk Merkez - OSM graph</p>
            <h1>Dinamik Kargo Rotalama</h1>
          </div>
          <span className={`status ${running ? 'live' : ''}`}>{running ? 'Canli' : started ? 'Duraklatildi' : 'Hazir'}</span>
        </header>

        <section className="meta-row">
          <span>Tick {state?.tick ?? 0}</span>
          <span>Arac hizi {state?.speed_kmh ?? 70} km/s</span>
          <span>Sim {state?.speed_multiplier ?? 2}x</span>
          <span>{state?.graph_source ?? 'graph bekleniyor'}</span>
        </section>

        <section className="controls">
          <label>
            Arac desileri
            <input value={capacities} onChange={(event) => setCapacities(event.target.value)} />
          </label>
          <label>
            Seed
            <input type="number" value={seed} onChange={(event) => setSeed(Number(event.target.value))} />
          </label>
          <button
            onClick={() =>
              run(() =>
                api('/api/sim/start', {
                  method: 'POST',
                  body: JSON.stringify({ seed, vehicles }),
                }),
              )
            }
            disabled={busy || vehicles.length === 0}
          >
            <RotateCcw size={18} /> Baslat
          </button>
        </section>

        <section className="controls run-controls">
          <button onClick={() => run(() => api('/api/sim/run', { method: 'POST' }))} disabled={busy || !started || running}>
            <Play size={18} /> Calistir
          </button>
          <button onClick={() => run(() => api('/api/sim/pause', { method: 'POST' }))} disabled={busy || !started || !running}>
            <Pause size={18} /> Duraklat
          </button>
          <button onClick={() => run(() => api('/api/sim/tick', { method: 'POST' }))} disabled={busy || !started || running}>
            <StepForward size={18} /> 5 sn
          </button>
        </section>

        <section className="speed-control">
          {SPEED_OPTIONS.map((multiplier) => (
            <button
              key={multiplier}
              className={state?.speed_multiplier === multiplier ? 'active' : ''}
              onClick={() =>
                run(() =>
                  api('/api/sim/speed', {
                    method: 'POST',
                    body: JSON.stringify({ multiplier }),
                  }),
                )
              }
              disabled={busy}
            >
              {multiplier}x
            </button>
          ))}
        </section>

        {error && <div className="error">{error}</div>}

        <section>
          <h2>
            <Truck size={18} /> Araclar
          </h2>
          <div className="cards">
            {state?.couriers?.map((courier) => {
              const loadPercent = Math.round((courier.current_load / courier.capacity_desi) * 100);
              const { deliveryLoad, returnLoad } = loadBreakdown(courier);
              return (
                <article className="card" key={courier.id}>
                  <div className="card-title">
                    <span className="dot" style={{ background: courier.color }} />
                    <strong>{courier.name}</strong>
                    <span>{courier.current_load}/{courier.capacity_desi} desi</span>
                  </div>
                  <div className="bar">
                    <span style={{ width: `${Math.min(100, loadPercent)}%`, background: courier.color }} />
                  </div>
                  <div className="load-split">
                    <span>Teslimat {deliveryLoad} desi</span>
                    <span>Iade {returnLoad} desi</span>
                  </div>
                  <p>{courier.route.filter((stop) => stop.status === 'pending').length} bekleyen durak</p>
                  <p>
                    {statusLabel(courier.movement_status)}
                    {courier.service_remaining_seconds > 0 ? ` - ${courier.service_remaining_seconds} sn` : ''}
                  </p>
                  {courier.route_error && <p className="route-error">{courier.route_error}</p>}
                </article>
              );
            })}
          </div>
        </section>

      </aside>

      <section className="map-wrap">
        <MapContainer center={CENTER} zoom={13} scrollWheelZoom className="map">
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {state?.couriers?.map((courier) =>
            courier.polyline?.length ? (
              <Polyline
                key={`${courier.id}-route-shadow`}
                positions={courier.polyline}
                pathOptions={{
                  color: courier.color,
                  weight: 12,
                  opacity: 0.18,
                  lineCap: 'round',
                  lineJoin: 'round',
                }}
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
            <Marker
              key={courier.id}
              position={[courier.lat, courier.lon]}
              icon={markerIcon(courier.color, courier.movement_status)}
            >
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
                  {stop.kind} - {stop.desi} desi - {stop.status}
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

      <aside className="panel right-panel">
        <section className="controls two">
          <label>
            Iade desi
            <input type="number" value={returnDesi} onChange={(event) => setReturnDesi(Number(event.target.value))} />
          </label>
          <button
            onClick={() =>
              run(() =>
                api('/api/returns', {
                  method: 'POST',
                  body: JSON.stringify({ desi: returnDesi }),
                }),
              )
            }
            disabled={busy || !started}
          >
            <PackagePlus size={18} /> Iade Ekle
          </button>
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
            {(state?.messages ?? []).slice().reverse().map((message, index) => (
              <p key={`${message}-${index}`}>{message}</p>
            ))}
          </div>
        </section>
      </aside>
    </main>
  );
}
