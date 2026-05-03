import { useEffect, useMemo, useState } from 'react';
import {
  CircleMarker,
  MapContainer,
  Marker,
  Polyline,
  Popup,
  TileLayer,
  ZoomControl,
} from 'react-leaflet';
import L from 'leaflet';
import {
  Activity,
  Boxes,
  Layers,
  PackageCheck,
  PackagePlus,
  Pause,
  Play,
  Plus,
  RotateCcw,
  Route,
  StepForward,
  Timer,
  Truck,
  Wifi,
  WifiOff,
} from 'lucide-react';

const API_BASE = import.meta.env.VITE_API_BASE ?? 'http://127.0.0.1:8000';
const CENTER = [41.1956, 32.6227];
const SPEED_OPTIONS = [1, 2, 4, 8, 16];

const STATUS_META = {
  idle: { label: 'Hazir' },
  moving: { label: 'Yolda' },
  servicing_delivery: { label: 'Teslimat' },
  servicing_return: { label: 'Iade' },
  loading: { label: 'Yukleniyor' },
  done: { label: 'Tamam' },
};

function markerIcon(color, status) {
  return L.divIcon({
    className: `courier-marker ${status}`,
    html: `<span style="background:${color};color:${color}"></span>`,
    iconSize: [34, 34],
    iconAnchor: [17, 17],
  });
}

function hubIcon() {
  return L.divIcon({
    className: 'hub-marker',
    html: '<div class="hub-pulse"></div><div class="hub-core">HUB</div>',
    iconSize: [44, 44],
    iconAnchor: [22, 22],
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
  return STATUS_META[status]?.label ?? status;
}

function loadBreakdown(courier) {
  const deliveryLoad = courier.route
    .filter((s) => s.kind === 'delivery' && s.status === 'pending')
    .reduce((t, s) => t + s.desi, 0);
  const returnLoad = courier.route
    .filter((s) => s.kind === 'return' && s.status === 'pending')
    .reduce((t, s) => t + s.desi, 0);
  return { deliveryLoad, returnLoad };
}

function kmValue(value = 0) {
  return `${Number(value || 0).toFixed(2)} km`;
}

function tl(value = 0) {
  return `${Number(value || 0).toFixed(2)} TL`;
}

function CommandBar({
  state,
  started,
  running,
  connected,
  busy,
  totalCapacity,
  simProgress,
  endHour,
  onPlan,
  onRun,
  onPause,
  onStep,
  onSpeed,
}) {
  const couriers = state?.couriers ?? [];
  const usedCap = couriers.reduce((s, c) => s + c.current_load, 0);
  const pendingStops = couriers
    .flatMap((c) => c.route)
    .filter((s) => s.kind !== 'hub' && s.status === 'pending').length;
  const doneStops = couriers
    .flatMap((c) => c.route)
    .filter((s) => s.kind !== 'hub' && s.status === 'done').length;
  const hubWaiting = state?.hub_cargo_pool?.filter((c) => c.status === 'waiting').length ?? 0;
  const returnsPending = state?.pending_returns?.length ?? 0;
  const metrics = state?.owner_metrics ?? {};
  const activeVehicles = couriers.filter((c) => c.movement_status === 'moving').length;
  const nearEod = simProgress > 0.8;

  return (
    <header className="cmdbar">
      <div className="cmd-brand">
        <div className="logo">
          <Route size={21} />
        </div>
        <div className="brand-text">
          <span className="brand-eyebrow">FIDEL.IO · KARABUK MERKEZ</span>
          <span className="brand-title">Dinamik Rotalama Operasyon Merkezi</span>
        </div>
      </div>

      <div className="cmd-clock">
        <div className="clock-face">
          <span className="clock-now mono">{state?.sim_clock ?? '10:00'}</span>
          <span className="clock-sep">/</span>
          <span className="clock-end mono">{state?.end_clock ?? `${endHour}:00`}</span>
          {running && <span className="live-dot" />}
          <span className={`conn ${connected ? 'ok' : 'fail'}`}>
            {connected ? <Wifi size={12} /> : <WifiOff size={12} />}
            {connected ? 'Bagli' : 'Baglanti yok'}
          </span>
        </div>
        <div className="clock-bar">
          <div className={`clock-fill ${nearEod ? 'eod' : ''}`} style={{ width: `${simProgress * 100}%` }} />
          <div className="clock-tick" style={{ left: '0%' }}>
            <span>10:00</span>
          </div>
          <div className="clock-tick" style={{ left: '25%' }}>
            <span>12:00</span>
          </div>
          <div className="clock-tick" style={{ left: '50%' }}>
            <span>14:00</span>
          </div>
          <div className="clock-tick" style={{ left: '75%' }}>
            <span>16:00</span>
          </div>
          <div className="clock-tick clock-tick-end">
            <span>{state?.end_clock ?? `${endHour}:00`}</span>
          </div>
        </div>
      </div>

      <div className="cmd-kpis">
        <KPI label="Arac" value={`${activeVehicles}/${couriers.length || 0}`} sub="hareketli" />
        <KPI
          label="Doluluk"
          value={`${totalCapacity ? Math.round((usedCap / totalCapacity) * 100) : 0}%`}
          sub={`${usedCap}/${totalCapacity} desi`}
          tone={totalCapacity && usedCap / totalCapacity > 0.85 ? 'warn' : ''}
        />
        <KPI label="Durak" value={pendingStops} sub={`${doneStops} tamam`} />
        <KPI label="Hub" value={hubWaiting} sub="bekliyor" tone={hubWaiting > 3 ? 'warn' : ''} />
        <KPI label="Iade" value={returnsPending} sub="havuzda" tone={returnsPending > 0 ? 'warn' : ''} />
        <KPI label="Kazanc" value={tl(metrics.saved_tl ?? 0)} sub={kmValue(metrics.saved_km ?? 0)} tone={(metrics.saved_tl ?? 0) > 0 ? 'good' : ''} />
      </div>

      <div className="cmd-controls">
        <button className="ic-btn" onClick={onStep} disabled={busy || !started || running} title="5 sn ileri">
          <StepForward size={14} />
        </button>
        <button
          className={`run-btn ${running ? 'is-running' : ''}`}
          onClick={running ? onPause : onRun}
          disabled={busy || !started}
        >
          {running ? <Pause size={13} /> : <Play size={13} />}
          {running ? 'Duraklat' : 'Baslat'}
        </button>
        <div className="speed-pills" aria-label="Simulasyon hizi">
          {SPEED_OPTIONS.map((m) => (
            <button
              key={m}
              className={state?.speed_multiplier === m ? 'active' : ''}
              onClick={() => onSpeed(m)}
              disabled={busy || !started}
            >
              {m}x
            </button>
          ))}
        </div>
        <button className="ic-btn replan" onClick={onPlan} disabled={busy}>
          <RotateCcw size={14} />
          <span>Yeniden Planla</span>
        </button>
      </div>
    </header>
  );
}

function KPI({ label, value, sub, tone }) {
  return (
    <div className={`kpi ${tone || ''}`}>
      <div className="kpi-label">{label}</div>
      <div className="kpi-value mono">{value}</div>
      <div className="kpi-sub">{sub}</div>
    </div>
  );
}

function PlanPanel({ capacities, setCapacities, seed, setSeed, endHour, setEndHour, onPlan, busy, vehicles }) {
  return (
    <section className="plan-panel">
      <div className="plan-title">
        <Layers size={15} />
        <span>Planlama</span>
      </div>
      <label>
        Arac desileri
        <input value={capacities} onChange={(e) => setCapacities(e.target.value)} />
      </label>
      <div className="plan-grid">
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
      </div>
      <button className="plan-btn" onClick={onPlan} disabled={busy || vehicles.length === 0}>
        <Route size={16} />
        Rota Planla
      </button>
    </section>
  );
}

function FleetRail({ state, selected, setSelected, planPanel, onAddVehicle, newVehicleCapacity, setNewVehicleCapacity, busy, started }) {
  const couriers = state?.couriers ?? [];

  return (
    <aside className="rail rail-left">
      <div className="rail-head">
        <div>
          <div className="rail-title">Filo</div>
          <div className="rail-sub">{couriers.length} arac · canli operasyon</div>
        </div>
        <span className="rail-chip">
          <Truck size={13} />
          {state?.speed_kmh ?? 70} km/s
        </span>
      </div>

      {planPanel}

      {started && (
        <div className="ret-add">
          <div className="ret-add-label">Filoya arac ekle</div>
          <div className="ret-add-row">
            <input
              type="number"
              min="10"
              max="2000"
              value={newVehicleCapacity}
              onChange={(e) => setNewVehicleCapacity(Number(e.target.value))}
            />
            <span className="ret-add-unit">desi</span>
            <button className="ret-add-btn" onClick={onAddVehicle} disabled={busy}>
              <Plus size={14} />
              Ekle
            </button>
          </div>
        </div>
      )}

      <div className="fleet-list">
        {couriers.length === 0 && <p className="empty-state">Rota planlaninca araclar burada gorunur.</p>}
        {couriers.map((courier) => {
          const pct = Math.min(100, Math.round((courier.current_load / courier.capacity_desi) * 100));
          const pending = courier.route.filter((s) => s.status === 'pending' && s.kind !== 'hub').length;
          const next = courier.route.find((s) => s.status === 'pending' && s.kind !== 'hub');
          const { deliveryLoad, returnLoad } = loadBreakdown(courier);
          const isSel = selected === courier.id;

          return (
            <article
              className={`fleet-card ${isSel ? 'selected' : ''}`}
              key={courier.id}
              onClick={() => setSelected(isSel ? null : courier.id)}
            >
              <div className="fc-head">
                <div className="fc-id">
                  <span className="fc-dot" style={{ background: courier.color }} />
                  <strong>{courier.name}</strong>
                </div>
                <span className={`fc-status status-${courier.movement_status}`}>
                  <span className="status-pip" />
                  {statusLabel(courier.movement_status)}
                </span>
              </div>

              <div className="fc-loadrow">
                <div className="fc-loadbar">
                  <div className="fc-load-fill" style={{ width: `${pct}%`, background: courier.color }} />
                  {[25, 50, 75].map((tick) => (
                    <span key={tick} className="fc-tick" style={{ left: `${tick}%` }} />
                  ))}
                </div>
                <div className="fc-loadnum mono">
                  {courier.current_load}
                  <small>/{courier.capacity_desi}</small>
                </div>
              </div>

              <div className="fc-meta">
                <span>
                  <b>{pending}</b> durak
                </span>
                <span className="dot-sep">·</span>
                <span>Teslimat {deliveryLoad}d</span>
                <span className="dot-sep">·</span>
                <span>Iade {returnLoad}d</span>
                {courier.service_remaining_seconds > 0 && (
                  <>
                    <span className="dot-sep">·</span>
                    <span className="warn-text">{Math.ceil(courier.service_remaining_seconds)}s servis</span>
                  </>
                )}
              </div>

              {next && (
                <div className="fc-next">
                  <span className="next-arrow">→</span>
                  <span className="next-label">{next.label}</span>
                  <span className="next-desi mono">{next.desi}d</span>
                </div>
              )}

              {courier.route_error && <p className="route-error">{courier.route_error}</p>}

              {isSel && (
                <div className="fc-manifest">
                  <div className="manifest-hd">Yukleme sirasi</div>
                  {courier.route
                    .filter((s) => s.kind !== 'hub')
                    .map((stop, index) => (
                      <div key={stop.id} className={`mf-row ${stop.status} ${stop.kind}`}>
                        <span className="mf-idx mono">{String(index + 1).padStart(2, '0')}</span>
                        <span className="mf-pin" />
                        <span className="mf-label">{stop.label}</span>
                        <span className="mf-desi mono">{stop.desi}d</span>
                        <span className="mf-check">{stop.status === 'done' ? '✓' : '○'}</span>
                      </div>
                    ))}
                </div>
              )}
            </article>
          );
        })}
      </div>
    </aside>
  );
}

function LiveMap({ state }) {
  const couriers = state?.couriers ?? [];
  const pendingReturns = state?.pending_returns ?? [];

  return (
    <div className="map-stage">
      <MapContainer center={CENTER} zoom={13} scrollWheelZoom zoomControl={false} className="map">
        <ZoomControl position="bottomright" />
        <TileLayer
          attribution="&copy; OpenStreetMap contributors &copy; CARTO"
          url="https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png"
        />
        <Marker position={CENTER} icon={hubIcon()} interactive={false} />
        {couriers.map((courier) =>
          courier.polyline?.length ? (
            <Polyline
              key={`${courier.id}-shadow`}
              positions={courier.polyline}
              pathOptions={{ color: courier.color, weight: 14, opacity: 0.1, lineCap: 'round', lineJoin: 'round' }}
            />
          ) : null,
        )}
        {couriers.map((courier) =>
          courier.polyline?.length ? (
            <Polyline
              key={`${courier.id}-route`}
              positions={courier.polyline}
              pathOptions={{
                color: courier.color,
                weight: 4,
                opacity: 0.92,
                dashArray: courier.movement_status === 'moving' ? '10 8' : undefined,
                lineCap: 'round',
                lineJoin: 'round',
                className: courier.movement_status === 'moving' ? 'route-flow' : '',
              }}
            />
          ) : null,
        )}
        {couriers.flatMap((courier) =>
          courier.route
            .filter((stop) => stop.kind !== 'hub')
            .map((stop) => (
              <CircleMarker
                key={stop.id}
                center={[stop.lat, stop.lon]}
                radius={stop.kind === 'return' ? 8 : 6}
                pathOptions={{
                  color: stop.kind === 'return' ? '#b91c1c' : courier.color,
                  fillColor: stop.kind === 'return' ? '#ef4444' : courier.color,
                  fillOpacity: stop.status === 'done' ? 0.28 : 0.88,
                  weight: 2,
                }}
              >
                <Popup>
                  <strong>{stop.label}</strong>
                  <br />
                  {stop.kind} · {stop.desi} desi · {stop.status}
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
        {pendingReturns.map((job) => (
          <CircleMarker
            key={job.id}
            center={[job.lat, job.lon]}
            radius={9}
            pathOptions={{
              color: job.deferred ? '#b45309' : '#b91c1c',
              fillColor: job.deferred ? '#f59e0b' : '#ef4444',
              fillOpacity: 0.9,
              weight: 2,
            }}
          >
            <Popup>
              <strong>{job.deferred ? 'Oncelikli iade' : 'Havuzdaki iade'}</strong>
              <br />
              {job.desi} desi
              <br />
              {job.message}
            </Popup>
          </CircleMarker>
        ))}
        {couriers.map((courier) => (
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
      </MapContainer>

      <div className="map-legend">
        <div className="legend-row">
          <span className="lg-pin lg-deliver" /> Teslimat
        </div>
        <div className="legend-row">
          <span className="lg-pin lg-return" /> Iade
        </div>
        <div className="legend-row">
          <span className="lg-pin lg-hub" /> Hub
        </div>
        <div className="legend-row">
          <span className="lg-line" /> Aktif rota
        </div>
      </div>
      <div className="map-zoom-meta">
        <span className="mono">41.196N · 32.623E</span>
        <span className="dot-sep">·</span>
        <span>OSM · Karabuk drive graph</span>
      </div>
    </div>
  );
}

function EventsRail({ state, tab, setTab, returnDesi, setReturnDesi, onAddReturn, busy, started }) {
  const hubWaiting = state?.hub_cargo_pool?.filter((c) => c.status === 'waiting') ?? [];
  const hubAssigned = state?.hub_cargo_pool?.filter((c) => c.status === 'assigned') ?? [];
  const pendingReturns = state?.pending_returns ?? [];
  const completedReturns = state?.completed_returns ?? [];
  const messages = (state?.messages ?? []).slice().reverse();
  const events = state?.owner_events ?? [];
  const metrics = state?.owner_metrics ?? {};
  const costPerKm = metrics.cost_per_km_tl ?? 35;

  return (
    <aside className="rail rail-right">
      <div className="rail-tabs">
        <button className={tab === 'events' ? 'active' : ''} onClick={() => setTab('events')}>
          Akis
        </button>
        <button className={tab === 'hub' ? 'active' : ''} onClick={() => setTab('hub')}>
          Hub <span className="tab-badge">{hubWaiting.length}</span>
        </button>
        <button className={tab === 'returns' ? 'active' : ''} onClick={() => setTab('returns')}>
          Iade <span className="tab-badge">{pendingReturns.length}</span>
        </button>
        <button className={tab === 'proof' ? 'active' : ''} onClick={() => setTab('proof')}>
          Kazanc <span className="tab-badge">{events.length}</span>
        </button>
      </div>

      {tab === 'events' && (
        <div className="events-pane">
          <div className="rail-head plain">
            <div>
              <div className="rail-title">Olay Akisi</div>
              <div className="rail-sub">son olaylar · tick {state?.tick ?? 0}</div>
            </div>
            <span className="live-pill">CANLI</span>
          </div>
          <ol className="evlist">
            {messages.length === 0 && <li className="ev-info empty">Henüz olay yok.</li>}
            {messages.map((message, index) => {
              const cls = message.includes('eklendi')
                ? 'ev-route'
                : message.includes('tamam')
                  ? 'ev-done'
                  : message.includes('Hub')
                    ? 'ev-hub'
                    : message.includes('yuklen') || message.includes('yüklen')
                      ? 'ev-load'
                      : message.includes('ertelendi')
                        ? 'ev-warn'
                        : 'ev-info';
              return (
                <li key={`${message}-${index}`} className={cls}>
                  <span className="ev-time mono">{state?.sim_clock ?? '10:00'}</span>
                  <span className="ev-pip" />
                  <span className="ev-msg">{message}</span>
                </li>
              );
            })}
          </ol>
        </div>
      )}

      {tab === 'hub' && (
        <div className="hub-pane">
          <div className="rail-head plain">
            <div>
              <div className="rail-title">Hub Kargo Havuzu</div>
              <div className="rail-sub">bekleyen ve atanmis kargolar</div>
            </div>
          </div>
          <div className="hub-stats">
            <div>
              <span className="mono">{hubWaiting.length}</span>
              <small>bekliyor</small>
            </div>
            <div>
              <span className="mono">{hubAssigned.length}</span>
              <small>atandi</small>
            </div>
            <div>
              <span className="mono">{state?.hub_cargo_pool?.reduce((s, c) => s + c.desi, 0) ?? 0}</span>
              <small>desi</small>
            </div>
          </div>
          <div className="hub-list">
            {hubWaiting.length === 0 && <p className="empty-state">Hub'da bekleyen kargo yok.</p>}
            {hubWaiting.map((cargo) => (
              <article key={cargo.id} className="hub-row">
                <div className="hub-row-icon">
                  <Boxes size={15} />
                </div>
                <div className="hub-row-body">
                  <strong>{cargo.label}</strong>
                  <small>Hub'da bekliyor</small>
                </div>
                <div className="hub-row-desi mono">
                  {cargo.desi}
                  <small>d</small>
                </div>
              </article>
            ))}
          </div>
        </div>
      )}

      {tab === 'returns' && (
        <div className="returns-pane">
          <div className="rail-head plain">
            <div>
              <div className="rail-title">Iade Yonetimi</div>
              <div className="rail-sub">Best Insertion · kapasite kontrollu</div>
            </div>
          </div>

          <div className="ret-add">
            <div className="ret-add-label">Yeni iade ekle</div>
            <div className="ret-add-row">
              <input type="number" min="1" max="100" value={returnDesi} onChange={(e) => setReturnDesi(Number(e.target.value))} />
              <span className="ret-add-unit">desi</span>
              <button className="ret-add-btn" onClick={onAddReturn} disabled={busy || !started}>
                <PackagePlus size={14} />
                Havuza ekle
              </button>
            </div>
          </div>

          <ReturnSection title={`Bekleyen (${pendingReturns.length})`} jobs={pendingReturns} />
          <ReturnSection title={`Tamamlanan (${completedReturns.length})`} jobs={completedReturns} completed />
        </div>
      )}

      {tab === 'proof' && (
        <div className="proof-pane">
          <div className="rail-head plain">
            <div>
              <div className="rail-title">Klasik vs Dinamik</div>
              <div className="rail-sub">{costPerKm} TL/km · Best Insertion</div>
            </div>
          </div>

          <ComparisonPanel metrics={metrics} costPerKm={costPerKm} />

          <div className="decision-section-title">Atama Detayları</div>
          <div className="decision-list">
            {events.length === 0 && <p className="empty-state">Henuz dinamik iade ataması olmadi.</p>}
            {events
              .slice()
              .reverse()
              .map((event) => {
                const baselineKm = (event.baseline_distance_m ?? 0) / 1000;
                const extraKm = (event.extra_cost_m ?? 0) / 1000;
                const savedKm = (event.saved_distance_m ?? 0) / 1000;
                return (
                  <article className="decision-card" key={event.id}>
                    <div className="decision-title">
                      <strong>{event.return_desi ?? 0} desi iade</strong>
                      <span>{event.courier_id}</span>
                    </div>
                    <div className="decision-metrics">
                      <span>
                        <b>{kmValue(baselineKm)}</b>
                        Klasik pickup
                      </span>
                      <span>
                        <b>{kmValue(extraKm)}</b>
                        Dinamik ek
                      </span>
                      <span>
                        <b>{tl(savedKm * costPerKm)}</b>
                        Kazanc
                      </span>
                    </div>
                    <p>{event.message}</p>
                  </article>
                );
              })}
          </div>
        </div>
      )}
    </aside>
  );
}

function ComparisonPanel({ metrics, costPerKm }) {
  const classicKm = metrics.classic_km ?? 0;
  const classicTl = metrics.classic_tl ?? 0;
  const classicVehicles = metrics.classic_vehicles ?? 0;
  const dynamicExtraKm = metrics.dynamic_extra_km ?? 0;
  const dynamicExtraTl = metrics.dynamic_extra_tl ?? 0;
  const savedKm = metrics.saved_km ?? 0;
  const savedTl = metrics.saved_tl ?? 0;
  const assignedCount = metrics.assigned_returns ?? 0;
  const savingsPct = classicKm > 0 ? Math.min(100, Math.round((savedKm / classicKm) * 100)) : 0;

  if (assignedCount === 0) {
    return (
      <div className="cmp-empty">
        <div className="cmp-empty-icon">⚖️</div>
        <div>İade eklenince karşılaştırma görünür</div>
        <small>İade sekmesinden havuza ekleyin</small>
      </div>
    );
  }

  return (
    <div className="cmp-wrapper">
      <div className="cmp-grid">
        <div className="cmp-col cmp-classic">
          <div className="cmp-col-tag">KLASİK SİSTEM</div>
          <div className="cmp-col-algo">
            Akşam toplu tur · NN sıralaması
          </div>
          <div className="cmp-col-km mono">{classicKm.toFixed(1)} km</div>
          <div className="cmp-col-tl">{classicTl.toFixed(0)} TL</div>
          <div className="cmp-col-note">
            {classicVehicles} araç · {assignedCount} iade
          </div>
        </div>

        <div className="cmp-vs">VS</div>

        <div className="cmp-col cmp-dynamic">
          <div className="cmp-col-tag">DİNAMİK SİSTEM</div>
          <div className="cmp-col-algo">Best Insertion · rotaya ekleme</div>
          <div className="cmp-col-km mono">{dynamicExtraKm.toFixed(1)} km</div>
          <div className="cmp-col-tl">{dynamicExtraTl.toFixed(0)} TL</div>
          <div className="cmp-col-note">
            0 ekstra araç · {assignedCount} iade mevcut rotaya
          </div>
        </div>
      </div>

      <div className="cmp-savings">
        <div className="cmp-savings-pct">{savingsPct}%</div>
        <div className="cmp-savings-body">
          <div className="cmp-savings-main">
            <span className="mono">{savedKm.toFixed(1)} km</span> tasarruf ·{' '}
            <span className="mono">{savedTl.toFixed(0)} TL</span> net kazanç
          </div>
          <div className="cmp-savings-sub">
            Klasik akşam turuna göre {savingsPct}% daha az km ·{' '}
            {classicVehicles > 1 ? `${classicVehicles} araç yerine 0 ekstra araç` : 'ekstra araç gerekmedi'}
          </div>
        </div>
      </div>
    </div>
  );
}

function ReturnSection({ title, jobs, completed = false }) {
  return (
    <section className="ret-section">
      <div className="ret-section-hd">{title}</div>
      {jobs.length === 0 && <p className="empty-state">Kayit yok.</p>}
      {jobs.map((job) => (
        <article key={job.id} className={`ret-row ${completed ? 'done' : ''} ${job.deferred ? 'deferred' : ''}`}>
          <div className="ret-row-top">
            <span className="ret-icon">{completed ? <PackageCheck size={11} /> : <Timer size={11} />}</span>
            <strong className="mono">{job.desi} desi</strong>
            {job.deferred && <span className="ret-badge warn">ONCELIKLI</span>}
            {job.assigned_courier_id && <span className="ret-badge ok">{job.assigned_courier_id}</span>}
            {job.assigned && <span className="ret-badge ok">{job.assigned}</span>}
          </div>
          <div className="ret-row-msg">{job.message}</div>
        </article>
      ))}
    </section>
  );
}

function TelemetryStrip({ state, connected }) {
  const couriers = state?.couriers ?? [];
  const routeStops = couriers.flatMap((c) => c.route).filter((s) => s.kind !== 'hub').length;
  const routePoints = couriers.reduce((sum, c) => sum + (c.polyline?.length ?? 0), 0);
  const insertions = (state?.completed_returns?.length ?? 0) + (state?.pending_returns?.filter((r) => r.assigned_courier_id).length ?? 0);
  const metrics = state?.owner_metrics ?? {};

  return (
    <footer className="telemetry">
      <div className="tel-cell">
        <span className="tel-eye">ALGORITMA</span>
        <strong className="mono">Geographic-aware FFD · Best Insertion</strong>
      </div>
      <div className="tel-divider" />
      <div className="tel-cell">
        <span className="tel-eye">YOL GRAFI</span>
        <strong>OSMnx · {state?.graph_source ?? 'bekleniyor'} · NetworkX shortest path</strong>
      </div>
      <div className="tel-divider" />
      <div className="tel-cell">
        <span className="tel-eye">ROTA</span>
        <strong className="mono">{routeStops} durak · {routePoints} nokta</strong>
      </div>
      <div className="tel-divider" />
      <div className="tel-cell">
        <span className="tel-eye">BEST INSERTION</span>
        <strong className="mono">{insertions} basarili</strong>
      </div>
      <div className="tel-divider" />
      <div className="tel-cell">
        <span className="tel-eye">KLASİK TUR</span>
        <strong className="mono">{kmValue(metrics.classic_km ?? 0)}</strong>
      </div>
      <div className="tel-divider" />
      <div className="tel-cell">
        <span className="tel-eye">NET KAZANC</span>
        <strong className="mono">{tl(metrics.saved_tl ?? 0)}</strong>
      </div>
      <div className="tel-divider" />
      <div className="tel-cell">
        <span className="tel-eye">ORT. HIZ</span>
        <strong className="mono">{state?.speed_kmh ?? 70} km/s · sim {state?.speed_multiplier ?? 1}x</strong>
      </div>
      <div className="tel-spacer" />
      <div className={`tel-cell tel-status ${connected ? 'ok' : 'fail'}`}>
        <span className="tel-pip" />
        <strong>{connected ? `Backend bagli · tick ${state?.tick ?? 0}` : 'Backend baglantisi yok'}</strong>
      </div>
    </footer>
  );
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
  const [selected, setSelected] = useState(null);
  const [rightTab, setRightTab] = useState('proof');
  const [newVehicleCapacity, setNewVehicleCapacity] = useState(100);

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
      const nextState = await action();
      setState(nextState);
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
  const workingHoursEndS = Math.max(3600, (Math.max(11, endHour) - 10) * 3600);
  const totalCapacity = state?.couriers?.reduce((s, c) => s + c.capacity_desi, 0) ?? vehicles.reduce((s, v) => s + v.capacity_desi, 0);
  const simElapsed = state?.sim_elapsed_seconds ?? 0;
  const simEnd = state?.working_hours_end_s ?? workingHoursEndS;
  const simProgress = simEnd > 0 ? Math.min(1, Math.max(0, simElapsed / simEnd)) : 0;

  const onPlan = () =>
    run(() =>
      api('/api/sim/start', {
        method: 'POST',
        body: JSON.stringify({ seed, vehicles, working_hours_end_s: workingHoursEndS }),
      }),
    );
  const onRun = () => run(() => api('/api/sim/run', { method: 'POST' }));
  const onPause = () => run(() => api('/api/sim/pause', { method: 'POST' }));
  const onStep = () => run(() => api('/api/sim/tick', { method: 'POST' }));
  const onSpeed = (multiplier) => run(() => api('/api/sim/speed', { method: 'POST', body: JSON.stringify({ multiplier }) }));
  const onAddReturn = () =>
    run(() =>
      api('/api/returns', {
        method: 'POST',
        body: JSON.stringify({ desi: returnDesi }),
      }),
    );
  const onAddVehicle = () =>
    run(() =>
      api('/api/sim/add_vehicle', {
        method: 'POST',
        body: JSON.stringify({ capacity_desi: newVehicleCapacity }),
      }),
    );

  const planPanel = (
    <PlanPanel
      capacities={capacities}
      setCapacities={setCapacities}
      seed={seed}
      setSeed={setSeed}
      endHour={endHour}
      setEndHour={setEndHour}
      onPlan={onPlan}
      busy={busy}
      vehicles={vehicles}
    />
  );

  return (
    <main className="ops-root">
      <CommandBar
        state={state}
        started={started}
        running={running}
        connected={connected}
        busy={busy}
        totalCapacity={totalCapacity}
        simProgress={simProgress}
        endHour={endHour}
        onPlan={onPlan}
        onRun={onRun}
        onPause={onPause}
        onStep={onStep}
        onSpeed={onSpeed}
      />

      <section className="ops-grid">
        <FleetRail
          state={state}
          selected={selected}
          setSelected={setSelected}
          planPanel={planPanel}
          onAddVehicle={onAddVehicle}
          newVehicleCapacity={newVehicleCapacity}
          setNewVehicleCapacity={setNewVehicleCapacity}
          busy={busy}
          started={started}
        />
        <LiveMap state={state} />
        <EventsRail
          state={state}
          tab={rightTab}
          setTab={setRightTab}
          returnDesi={returnDesi}
          setReturnDesi={setReturnDesi}
          onAddReturn={onAddReturn}
          busy={busy}
          started={started}
        />
      </section>

      {error && (
        <div className="toast-error">
          <Activity size={14} />
          {error}
        </div>
      )}

      <TelemetryStrip state={state} connected={connected} />
    </main>
  );
}
