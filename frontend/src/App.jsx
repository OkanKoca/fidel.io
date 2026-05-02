import { useEffect, useMemo, useState } from 'react';
import { MapContainer, Marker, Polyline, Popup, TileLayer, CircleMarker } from 'react-leaflet';
import L from 'leaflet';
import { PackagePlus, Play, RotateCcw, Truck, Timer, MapPin } from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
const CENTER = [41.1956, 32.6227];

function markerIcon(color) {
  return L.divIcon({
    className: 'courier-marker',
    html: `<span style="background:${color}"></span>`,
    iconSize: [22, 22],
    iconAnchor: [11, 11],
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
    }, 4000);
    return () => clearInterval(timer);
  }, []);

  const started = Boolean(state?.started);

  return (
    <main className="shell">
      <aside className="panel">
        <header>
          <div>
            <p>Karabük Merkez</p>
            <h1>Dinamik Kargo Rotalama</h1>
          </div>
          <span className="status">{started ? `Tick ${state.tick}` : 'Hazır'}</span>
        </header>

        <section className="controls">
          <label>
            Araç desileri
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
            <RotateCcw size={18} /> Simülasyonu Başlat
          </button>
        </section>

        <section className="controls two">
          <label>
            İade desi
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
            <PackagePlus size={18} /> İade Ekle
          </button>
          <button onClick={() => run(() => api('/api/sim/tick', { method: 'POST' }))} disabled={busy || !started}>
            <Play size={18} /> Tick
          </button>
        </section>

        {error && <div className="error">{error}</div>}

        <section>
          <h2>
            <Truck size={18} /> Araçlar
          </h2>
          <div className="cards">
            {state?.couriers?.map((courier) => {
              const loadPercent = Math.round((courier.current_load / courier.capacity_desi) * 100);
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
                  <p>{courier.route.filter((stop) => stop.status === 'pending').length} bekleyen durak</p>
                  {courier.route_error && <p className="route-error">{courier.route_error}</p>}
                </article>
              );
            })}
          </div>
        </section>

        <section>
          <h2>
            <Timer size={18} /> İade Havuzu
          </h2>
          <div className="pool">
            {(state?.pending_returns?.length ?? 0) === 0 && <p>Bekleyen iade yok.</p>}
            {state?.pending_returns?.map((job) => (
              <article className="pool-item" key={job.id}>
                <strong>{job.desi} desi</strong>
                <span>{job.message}</span>
              </article>
            ))}
          </div>
        </section>

        <section>
          <h2>
            <MapPin size={18} /> Olay Akışı
          </h2>
          <div className="log">
            {(state?.messages ?? []).slice().reverse().map((message, index) => (
              <p key={`${message}-${index}`}>{message}</p>
            ))}
          </div>
        </section>
      </aside>

      <section className="map-wrap">
        <MapContainer center={CENTER} zoom={13} scrollWheelZoom className="map">
          <TileLayer
            attribution="&copy; OpenStreetMap contributors"
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          {state?.couriers?.map((courier) => (
            <Marker key={courier.id} position={[courier.lat, courier.lon]} icon={markerIcon(courier.color)}>
              <Popup>
                <strong>{courier.name}</strong>
                <br />
                {courier.current_load}/{courier.capacity_desi} desi
              </Popup>
            </Marker>
          ))}
          {state?.couriers?.map((courier) =>
            courier.polyline?.length ? (
              <Polyline key={`${courier.id}-line`} positions={courier.polyline} color={courier.color} weight={5} />
            ) : null,
          )}
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
              pathOptions={{ color: '#dc2626', fillColor: '#fca5a5', fillOpacity: 0.95 }}
            >
              <Popup>
                <strong>Havuzdaki iade</strong>
                <br />
                {job.desi} desi
              </Popup>
            </CircleMarker>
          ))}
        </MapContainer>
      </section>
    </main>
  );
}
