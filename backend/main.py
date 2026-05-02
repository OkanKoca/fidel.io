from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass, field
from typing import Literal
from uuid import uuid4

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "http://127.0.0.1:5000")
OSRM_FALLBACK_ENABLED = os.getenv("OSRM_FALLBACK_ENABLED", "true").lower() == "true"
KARABUK_CENTER = {"lat": 41.1956, "lon": 32.6227}
SPATIAL_TRIGGER_KM = float(os.getenv("SPATIAL_TRIGGER_KM", "2.0"))

KARABUK_POINTS = [
    {"lat": 41.2067, "lon": 32.6271},
    {"lat": 41.2024, "lon": 32.6205},
    {"lat": 41.1937, "lon": 32.6184},
    {"lat": 41.1889, "lon": 32.6249},
    {"lat": 41.1842, "lon": 32.6302},
    {"lat": 41.1979, "lon": 32.6338},
    {"lat": 41.2053, "lon": 32.6389},
    {"lat": 41.1908, "lon": 32.6116},
    {"lat": 41.1992, "lon": 32.6074},
    {"lat": 41.2091, "lon": 32.6157},
    {"lat": 41.1864, "lon": 32.6162},
    {"lat": 41.2015, "lon": 32.6312},
    {"lat": 41.1921, "lon": 32.6357},
    {"lat": 41.1834, "lon": 32.6201},
    {"lat": 41.2114, "lon": 32.6318},
]


class VehicleInput(BaseModel):
    id: str | None = None
    capacity_desi: int = Field(gt=0, le=500)


class StartRequest(BaseModel):
    vehicles: list[VehicleInput] = Field(min_length=1, max_length=12)
    seed: int = 42
    min_deliveries: int = Field(default=5, ge=1, le=12)
    max_deliveries: int = Field(default=7, ge=1, le=15)


class ReturnRequest(BaseModel):
    desi: int = Field(gt=0, le=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


@dataclass
class Stop:
    id: str
    kind: Literal["delivery", "return", "hub"]
    label: str
    lat: float
    lon: float
    desi: int = 0
    service_seconds: int = 0
    status: Literal["pending", "done"] = "pending"


@dataclass
class ReturnJob:
    id: str
    lat: float
    lon: float
    desi: int
    status: Literal["pending", "assigned", "unassigned"] = "pending"
    assigned_courier_id: str | None = None
    created_at: float = field(default_factory=time.time)
    message: str = "Havuzda bekliyor"


@dataclass
class Courier:
    id: str
    name: str
    capacity_desi: int
    current_load: int
    lat: float
    lon: float
    route: list[Stop]
    color: str
    polyline: list[list[float]] = field(default_factory=list)
    route_error: str | None = None


@dataclass
class SimState:
    started: bool = False
    seed: int = 42
    tick: int = 0
    couriers: list[Courier] = field(default_factory=list)
    pending_returns: list[ReturnJob] = field(default_factory=list)
    completed_returns: list[ReturnJob] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)


state = SimState()
app = FastAPI(title="Dynamic Cargo Routing Demo")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def haversine_km(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    radius = 6371.0
    d_lat = math.radians(b_lat - a_lat)
    d_lon = math.radians(b_lon - a_lon)
    lat1 = math.radians(a_lat)
    lat2 = math.radians(b_lat)
    h = (
        math.sin(d_lat / 2) ** 2
        + math.cos(lat1) * math.cos(lat2) * math.sin(d_lon / 2) ** 2
    )
    return 2 * radius * math.asin(math.sqrt(h))


def point_from_pool(rng: random.Random, used: set[int]) -> dict[str, float]:
    available = [i for i in range(len(KARABUK_POINTS)) if i not in used]
    if not available:
        used.clear()
        available = list(range(len(KARABUK_POINTS)))
    idx = rng.choice(available)
    used.add(idx)
    point = KARABUK_POINTS[idx]
    return {
        "lat": round(point["lat"] + rng.uniform(-0.0012, 0.0012), 6),
        "lon": round(point["lon"] + rng.uniform(-0.0012, 0.0012), 6),
    }


def split_delivery_load(rng: random.Random, capacity: int, stop_count: int) -> list[int]:
    target = max(stop_count, int(capacity * rng.uniform(0.7, 0.9)))
    weights = [rng.uniform(0.6, 1.4) for _ in range(stop_count)]
    raw = [max(1, int(target * weight / sum(weights))) for weight in weights]
    diff = target - sum(raw)
    raw[-1] = max(1, raw[-1] + diff)
    return raw


def serialize_stop(stop: Stop) -> dict:
    return {
        "id": stop.id,
        "kind": stop.kind,
        "label": stop.label,
        "lat": stop.lat,
        "lon": stop.lon,
        "desi": stop.desi,
        "service_seconds": stop.service_seconds,
        "status": stop.status,
    }


def serialize_return(job: ReturnJob) -> dict:
    return {
        "id": job.id,
        "lat": job.lat,
        "lon": job.lon,
        "desi": job.desi,
        "status": job.status,
        "assigned_courier_id": job.assigned_courier_id,
        "message": job.message,
        "created_at": job.created_at,
    }


def state_response() -> dict:
    return {
        "started": state.started,
        "seed": state.seed,
        "tick": state.tick,
        "spatial_trigger_km": SPATIAL_TRIGGER_KM,
        "messages": state.messages[-10:],
        "couriers": [
            {
                "id": courier.id,
                "name": courier.name,
                "capacity_desi": courier.capacity_desi,
                "current_load": courier.current_load,
                "free_desi": courier.capacity_desi - courier.current_load,
                "lat": courier.lat,
                "lon": courier.lon,
                "color": courier.color,
                "route": [serialize_stop(stop) for stop in courier.route],
                "polyline": courier.polyline,
                "route_error": courier.route_error,
            }
            for courier in state.couriers
        ],
        "pending_returns": [serialize_return(job) for job in state.pending_returns],
        "completed_returns": [serialize_return(job) for job in state.completed_returns],
    }


async def osrm_table_distance_matrix(points: list[dict[str, float]]) -> list[list[float | None]]:
    coords = ";".join(f"{point['lon']},{point['lat']}" for point in points)
    url = f"{OSRM_BASE_URL}/table/v1/driving/{coords}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url, params={"annotations": "distance"})
    except httpx.HTTPError as exc:
        if OSRM_FALLBACK_ENABLED:
            return haversine_distance_matrix(points)
        raise HTTPException(status_code=502, detail=f"OSRM Table API connection error: {exc}") from exc
    if response.status_code != 200:
        if OSRM_FALLBACK_ENABLED:
            return haversine_distance_matrix(points)
        raise HTTPException(
            status_code=502,
            detail=f"OSRM Table API error: {response.status_code} {response.text[:180]}",
        )
    payload = response.json()
    distances = payload.get("distances")
    if not distances:
        raise HTTPException(status_code=502, detail="OSRM Table API returned no matrix")
    return distances


def haversine_distance_matrix(points: list[dict[str, float]]) -> list[list[float]]:
    return [
        [
            haversine_km(origin["lat"], origin["lon"], destination["lat"], destination["lon"]) * 1000
            for destination in points
        ]
        for origin in points
    ]


async def refresh_polyline(courier: Courier) -> None:
    pending_route = [stop for stop in courier.route if stop.status == "pending"]
    points = [{"lat": courier.lat, "lon": courier.lon}] + [
        {"lat": stop.lat, "lon": stop.lon} for stop in pending_route
    ]
    if len(points) < 2:
        courier.polyline = [[courier.lat, courier.lon]]
        courier.route_error = None
        return

    coords = ";".join(f"{point['lon']},{point['lat']}" for point in points)
    url = f"{OSRM_BASE_URL}/route/v1/driving/{coords}"
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(
                url,
                params={"overview": "full", "geometries": "geojson", "steps": "false"},
            )
    except httpx.HTTPError as exc:
        if OSRM_FALLBACK_ENABLED:
            courier.route_error = "OSRM kapalı; düz çizgi fallback kullanılıyor"
            courier.polyline = [[point["lat"], point["lon"]] for point in points]
            return
        courier.route_error = f"OSRM Route API connection error: {exc}"
        courier.polyline = []
        return
    if response.status_code != 200:
        if OSRM_FALLBACK_ENABLED:
            courier.route_error = f"OSRM Route API {response.status_code}; düz çizgi fallback kullanılıyor"
            courier.polyline = [[point["lat"], point["lon"]] for point in points]
            return
        courier.route_error = f"OSRM Route API error: {response.status_code}"
        courier.polyline = []
        return

    payload = response.json()
    routes = payload.get("routes") or []
    if not routes:
        courier.route_error = "OSRM Route API returned no route"
        courier.polyline = []
        return

    coordinates = routes[0]["geometry"]["coordinates"]
    courier.polyline = [[lat, lon] for lon, lat in coordinates]
    courier.route_error = None


async def refresh_all_polylines() -> None:
    for courier in state.couriers:
        await refresh_polyline(courier)


def is_spatially_triggered(courier: Courier, job: ReturnJob) -> bool:
    if haversine_km(courier.lat, courier.lon, job.lat, job.lon) <= SPATIAL_TRIGGER_KM:
        return True
    next_stop = next((stop for stop in courier.route if stop.status == "pending"), None)
    return bool(
        next_stop
        and haversine_km(next_stop.lat, next_stop.lon, job.lat, job.lon) <= SPATIAL_TRIGGER_KM
    )


def remaining_route(courier: Courier) -> list[Stop]:
    return [stop for stop in courier.route if stop.status == "pending"]


def projected_load_before_insert(courier: Courier, insertion_index: int) -> int:
    load = courier.current_load
    for stop in remaining_route(courier)[:insertion_index]:
        if stop.kind == "delivery":
            load -= stop.desi
        elif stop.kind == "return":
            load += stop.desi
    return load


async def try_assign_return(job: ReturnJob) -> bool:
    candidates: list[tuple[Courier, int, dict[str, float], dict[str, float]]] = []
    unique_points: list[dict[str, float]] = []
    point_keys: dict[tuple[float, float], int] = {}

    def point_index(point: dict[str, float]) -> int:
        key = (point["lat"], point["lon"])
        if key not in point_keys:
            point_keys[key] = len(unique_points)
            unique_points.append(point)
        return point_keys[key]

    x_point = {"lat": job.lat, "lon": job.lon}
    point_index(x_point)

    for courier in state.couriers:
        if not is_spatially_triggered(courier, job):
            continue
        route = remaining_route(courier)
        if not route:
            continue

        chain = [Stop("current", "hub", "Mevcut Konum", courier.lat, courier.lon)] + route
        for idx in range(len(chain) - 1):
            a_stop = chain[idx]
            b_stop = chain[idx + 1]
            a_point = {"lat": a_stop.lat, "lon": a_stop.lon}
            b_point = {"lat": b_stop.lat, "lon": b_stop.lon}
            insertion_index = idx
            projected_load = projected_load_before_insert(courier, insertion_index)
            if projected_load + job.desi > courier.capacity_desi:
                continue
            point_index(a_point)
            point_index(b_point)
            candidates.append((courier, insertion_index, a_point, b_point))

    if not candidates:
        job.message = "Yakınlık veya kapasite uygunluğu bulunamadı"
        return False

    matrix = await osrm_table_distance_matrix(unique_points)
    x_idx = point_index(x_point)
    best: tuple[float, Courier, int] | None = None

    for courier, insertion_index, a_point, b_point in candidates:
        a_idx = point_index(a_point)
        b_idx = point_index(b_point)
        ax = matrix[a_idx][x_idx]
        xb = matrix[x_idx][b_idx]
        ab = matrix[a_idx][b_idx]
        if ax is None or xb is None or ab is None:
            continue
        extra_cost = ax + xb - ab
        if best is None or extra_cost < best[0]:
            best = (extra_cost, courier, insertion_index)

    if best is None:
        job.message = "OSRM uygun insertion maliyeti döndürmedi"
        return False

    extra_cost, courier, insertion_index = best
    return_stop = Stop(
        id=job.id,
        kind="return",
        label=f"İade {job.desi} desi",
        lat=job.lat,
        lon=job.lon,
        desi=job.desi,
        service_seconds=5,
    )
    pending_ids = [stop.id for stop in courier.route if stop.status == "pending"]
    if insertion_index >= len(pending_ids):
        courier.route.append(return_stop)
    else:
        target_id = pending_ids[insertion_index]
        route_index = next(i for i, stop in enumerate(courier.route) if stop.id == target_id)
        courier.route.insert(route_index, return_stop)

    job.status = "assigned"
    job.assigned_courier_id = courier.id
    job.message = f"{courier.name} rotasına eklendi (+{extra_cost / 1000:.2f} km)"
    state.completed_returns.append(job)
    state.messages.append(job.message)
    await refresh_polyline(courier)
    return True


async def evaluate_return_pool() -> None:
    for job in list(state.pending_returns):
        assigned = await try_assign_return(job)
        if assigned:
            state.pending_returns.remove(job)


@app.post("/api/sim/start")
async def start_simulation(request: StartRequest) -> dict:
    global state
    if request.min_deliveries > request.max_deliveries:
        raise HTTPException(status_code=400, detail="min_deliveries max_deliveries değerinden büyük olamaz")

    rng = random.Random(request.seed)
    used_points: set[int] = set()
    colors = ["#2563eb", "#f97316", "#16a34a", "#db2777", "#7c3aed", "#0891b2"]
    couriers: list[Courier] = []

    for index, vehicle in enumerate(request.vehicles):
        stop_count = rng.randint(request.min_deliveries, request.max_deliveries)
        desi_values = split_delivery_load(rng, vehicle.capacity_desi, stop_count)
        route = []
        for stop_index in range(stop_count):
            point = point_from_pool(rng, used_points)
            route.append(
                Stop(
                    id=str(uuid4()),
                    kind="delivery",
                    label=f"Teslimat {stop_index + 1}",
                    lat=point["lat"],
                    lon=point["lon"],
                    desi=desi_values[stop_index],
                    service_seconds=3,
                )
            )
        route.append(
            Stop(
                id=str(uuid4()),
                kind="hub",
                label="Hub dönüş",
                lat=KARABUK_CENTER["lat"],
                lon=KARABUK_CENTER["lon"],
                service_seconds=0,
            )
        )
        couriers.append(
            Courier(
                id=vehicle.id or f"courier-{index + 1}",
                name=f"Araç {index + 1}",
                capacity_desi=vehicle.capacity_desi,
                current_load=sum(desi_values),
                lat=KARABUK_CENTER["lat"],
                lon=KARABUK_CENTER["lon"],
                route=route,
                color=colors[index % len(colors)],
            )
        )

    state = SimState(
        started=True,
        seed=request.seed,
        couriers=couriers,
        messages=[f"Simülasyon {len(couriers)} araçla başlatıldı"],
    )
    await refresh_all_polylines()
    return state_response()


@app.post("/api/returns")
async def create_return(request: ReturnRequest) -> dict:
    if not state.started:
        raise HTTPException(status_code=400, detail="Önce simülasyonu başlatın")

    rng = random.Random(state.seed + len(state.pending_returns) + len(state.completed_returns) + 1000)
    point = (
        {"lat": request.lat, "lon": request.lon}
        if request.lat is not None and request.lon is not None
        else point_from_pool(rng, set())
    )
    job = ReturnJob(
        id=str(uuid4()),
        lat=round(float(point["lat"]), 6),
        lon=round(float(point["lon"]), 6),
        desi=request.desi,
    )
    state.pending_returns.append(job)
    state.messages.append(f"{request.desi} desi iade havuza eklendi")
    return state_response()


@app.post("/api/sim/tick")
async def tick() -> dict:
    if not state.started:
        raise HTTPException(status_code=400, detail="Önce simülasyonu başlatın")

    state.tick += 1
    for courier in state.couriers:
        next_stop = next((stop for stop in courier.route if stop.status == "pending"), None)
        if next_stop is None:
            continue
        courier.lat = next_stop.lat
        courier.lon = next_stop.lon
        next_stop.status = "done"
        if next_stop.kind == "delivery":
            courier.current_load = max(0, courier.current_load - next_stop.desi)
            state.messages.append(
                f"{courier.name} {next_stop.desi} desi teslimat yaptı ({next_stop.service_seconds} sn)"
            )
        elif next_stop.kind == "return":
            courier.current_load = min(courier.capacity_desi, courier.current_load + next_stop.desi)
            state.messages.append(
                f"{courier.name} {next_stop.desi} desi iade aldı ({next_stop.service_seconds} sn)"
            )

    await evaluate_return_pool()
    await refresh_all_polylines()
    return state_response()


@app.get("/api/sim/state")
async def get_state() -> dict:
    return state_response()


@app.get("/api/health")
async def health() -> dict:
    return {"ok": True, "osrm_base_url": OSRM_BASE_URL}
