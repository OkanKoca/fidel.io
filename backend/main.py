from __future__ import annotations

import math
import os
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal
from uuid import uuid4

import networkx as nx
import osmnx as ox
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field


KARABUK_CENTER = {"lat": 41.1956, "lon": 32.6227}
SPATIAL_TRIGGER_KM = float(os.getenv("SPATIAL_TRIGGER_KM", "2.0"))
SIM_SPEED_KMH = float(os.getenv("SIM_SPEED_KMH", "35"))
GRAPH_PLACE = os.getenv("GRAPH_PLACE", "Karabuk Merkez, Karabuk, Turkiye")
GRAPH_CACHE_PATH = Path(os.getenv("GRAPH_CACHE_PATH", "backend/data/karabuk_drive.graphml"))

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

road_graph: nx.MultiDiGraph | None = None
graph_source = "not-loaded"


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
    node: int
    desi: int = 0
    service_seconds: int = 0
    status: Literal["pending", "done"] = "pending"


@dataclass
class ReturnJob:
    id: str
    lat: float
    lon: float
    node: int
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
    node: int
    route: list[Stop]
    color: str
    path_nodes: list[int] = field(default_factory=list)
    path_coords: list[list[float]] = field(default_factory=list)
    stop_arrival_indices: dict[str, int] = field(default_factory=dict)
    path_cursor: int = 0
    segment_progress_m: float = 0.0
    movement_status: Literal[
        "idle",
        "moving",
        "servicing_delivery",
        "servicing_return",
        "done",
    ] = "idle"
    active_stop_id: str | None = None
    service_remaining_seconds: float = 0.0
    route_error: str | None = None


@dataclass
class SimState:
    started: bool = False
    running: bool = False
    seed: int = 42
    tick: int = 0
    last_update_at: float | None = None
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


def get_graph() -> nx.MultiDiGraph:
    global road_graph, graph_source
    if road_graph is not None:
        return road_graph

    GRAPH_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if GRAPH_CACHE_PATH.exists():
        road_graph = ox.load_graphml(GRAPH_CACHE_PATH)
        graph_source = "cache"
        return road_graph

    try:
        road_graph = ox.graph_from_place(GRAPH_PLACE, network_type="drive", simplify=True)
        ox.save_graphml(road_graph, GRAPH_CACHE_PATH)
        graph_source = "osm"
        return road_graph
    except Exception as exc:
        road_graph = build_fallback_graph()
        graph_source = f"fallback: {exc.__class__.__name__}"
        return road_graph


def build_fallback_graph() -> nx.MultiDiGraph:
    graph = nx.MultiDiGraph()
    points = [KARABUK_CENTER] + KARABUK_POINTS
    for index, point in enumerate(points):
        graph.add_node(index, y=point["lat"], x=point["lon"])
    for index, point in enumerate(points):
        distances = sorted(
            (
                haversine_km(point["lat"], point["lon"], other["lat"], other["lon"]) * 1000,
                other_index,
            )
            for other_index, other in enumerate(points)
            if other_index != index
        )
        for length, other_index in distances[:4]:
            graph.add_edge(index, other_index, length=length)
            graph.add_edge(other_index, index, length=length)
    return graph


def node_lat_lon(node: int) -> tuple[float, float]:
    graph = get_graph()
    data = graph.nodes[node]
    return float(data["y"]), float(data["x"])


def nearest_node(lat: float, lon: float) -> int:
    graph = get_graph()
    try:
        return int(ox.distance.nearest_nodes(graph, lon, lat))
    except Exception:
        return min(
            graph.nodes,
            key=lambda node: haversine_km(
                lat,
                lon,
                float(graph.nodes[node]["y"]),
                float(graph.nodes[node]["x"]),
            ),
        )


def edge_length_m(origin: int, destination: int) -> float:
    graph = get_graph()
    edge_data = graph.get_edge_data(origin, destination)
    if not edge_data:
        a_lat, a_lon = node_lat_lon(origin)
        b_lat, b_lon = node_lat_lon(destination)
        return haversine_km(a_lat, a_lon, b_lat, b_lon) * 1000
    return min(float(data.get("length", 1.0)) for data in edge_data.values())


def best_edge_data(origin: int, destination: int) -> dict | None:
    graph = get_graph()
    edge_data = graph.get_edge_data(origin, destination)
    if not edge_data:
        return None
    return min(edge_data.values(), key=lambda data: float(data.get("length", 1.0)))


def edge_geometry_coords(origin: int, destination: int) -> list[list[float]]:
    data = best_edge_data(origin, destination)
    if data and data.get("geometry") is not None:
        return [[float(lat), float(lon)] for lon, lat in data["geometry"].coords]

    origin_lat, origin_lon = node_lat_lon(origin)
    destination_lat, destination_lon = node_lat_lon(destination)
    return [[origin_lat, origin_lon], [destination_lat, destination_lon]]


def shortest_path_nodes(origin: int, destination: int) -> list[int]:
    if origin == destination:
        return [origin]
    graph = get_graph()
    try:
        return list(nx.shortest_path(graph, origin, destination, weight="length"))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        return [origin, destination]


def shortest_path_length_m(origin: int, destination: int) -> float:
    if origin == destination:
        return 0.0
    graph = get_graph()
    try:
        return float(nx.shortest_path_length(graph, origin, destination, weight="length"))
    except (nx.NetworkXNoPath, nx.NodeNotFound):
        a_lat, a_lon = node_lat_lon(origin)
        b_lat, b_lon = node_lat_lon(destination)
        return haversine_km(a_lat, a_lon, b_lat, b_lon) * 1000


def nodes_to_coords(nodes: list[int]) -> list[list[float]]:
    if not nodes:
        return []
    coords: list[list[float]] = [list(node_lat_lon(nodes[0]))]
    for origin, destination in zip(nodes, nodes[1:]):
        edge_coords = edge_geometry_coords(origin, destination)
        if not edge_coords:
            continue
        if coords and edge_coords[0] == coords[-1]:
            coords.extend(edge_coords[1:])
        else:
            coords.extend(edge_coords)
    return coords


def append_leg_geometry(
    coords: list[list[float]],
    leg_nodes: list[int],
) -> tuple[list[list[float]], int]:
    leg_coords = nodes_to_coords(leg_nodes)
    if not leg_coords:
        return coords, max(0, len(coords) - 1)
    if coords and leg_coords[0] == coords[-1]:
        coords.extend(leg_coords[1:])
    else:
        coords.extend(leg_coords)
    return coords, max(0, len(coords) - 1)


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


def random_graph_node(rng: random.Random, used: set[int]) -> int:
    point = point_from_pool(rng, used)
    return nearest_node(point["lat"], point["lon"])


def split_delivery_load(rng: random.Random, capacity: int, stop_count: int) -> list[int]:
    target = max(stop_count, int(capacity * rng.uniform(0.7, 0.9)))
    weights = [rng.uniform(0.6, 1.4) for _ in range(stop_count)]
    raw = [max(1, int(target * weight / sum(weights))) for weight in weights]
    diff = target - sum(raw)
    raw[-1] = max(1, raw[-1] + diff)
    return raw


def pending_route(courier: Courier) -> list[Stop]:
    return [stop for stop in courier.route if stop.status == "pending"]


def rebuild_courier_path(courier: Courier) -> None:
    stops = pending_route(courier)
    if not stops:
        courier.path_nodes = [courier.node]
        courier.path_coords = [[courier.lat, courier.lon]]
        courier.stop_arrival_indices = {}
        courier.path_cursor = 0
        courier.segment_progress_m = 0.0
        courier.movement_status = "done"
        courier.route_error = None
        return

    origin = nearest_node(courier.lat, courier.lon)
    courier.node = origin
    path_nodes = [origin]
    path_coords = [[courier.lat, courier.lon]]
    stop_arrival_indices: dict[str, int] = {}

    for stop in stops:
        leg = shortest_path_nodes(path_nodes[-1], stop.node)
        if len(leg) > 1:
            path_nodes.extend(leg[1:])
        path_coords, arrival_index = append_leg_geometry(path_coords, leg)
        stop_arrival_indices[stop.id] = arrival_index

    courier.path_nodes = path_nodes
    courier.path_coords = path_coords
    courier.stop_arrival_indices = stop_arrival_indices
    courier.path_cursor = 0
    courier.segment_progress_m = 0.0
    courier.movement_status = "moving"
    courier.active_stop_id = None
    courier.service_remaining_seconds = 0.0
    courier.route_error = None


def active_stop(courier: Courier) -> Stop | None:
    if courier.active_stop_id is None:
        return None
    return next((stop for stop in courier.route if stop.id == courier.active_stop_id), None)


def next_pending_stop(courier: Courier) -> Stop | None:
    return next((stop for stop in courier.route if stop.status == "pending"), None)


def stop_at_current_cursor(courier: Courier) -> Stop | None:
    for stop in pending_route(courier):
        if courier.stop_arrival_indices.get(stop.id) == courier.path_cursor:
            return stop
    return None


def interpolate(a: list[float], b: list[float], ratio: float) -> tuple[float, float]:
    return a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio


def complete_service(courier: Courier) -> None:
    stop = active_stop(courier)
    if stop is None:
        courier.movement_status = "moving"
        return

    stop.status = "done"
    courier.node = stop.node
    courier.lat = stop.lat
    courier.lon = stop.lon
    if stop.kind == "delivery":
        courier.current_load = max(0, courier.current_load - stop.desi)
        state.messages.append(f"{courier.name} {stop.desi} desi teslimat tamamladi")
    elif stop.kind == "return":
        courier.current_load = min(courier.capacity_desi, courier.current_load + stop.desi)
        state.messages.append(f"{courier.name} {stop.desi} desi iade aldi")

    courier.active_stop_id = None
    courier.service_remaining_seconds = 0.0
    rebuild_courier_path(courier)


def start_service(courier: Courier, stop: Stop) -> None:
    courier.active_stop_id = stop.id
    courier.service_remaining_seconds = float(stop.service_seconds)
    courier.movement_status = (
        "servicing_return" if stop.kind == "return" else "servicing_delivery"
    )


def advance_courier(courier: Courier, elapsed_seconds: float) -> None:
    remaining_seconds = max(0.0, elapsed_seconds)
    speed_mps = SIM_SPEED_KMH * 1000 / 3600

    while remaining_seconds > 0:
        if courier.movement_status in {"servicing_delivery", "servicing_return"}:
            consumed = min(remaining_seconds, courier.service_remaining_seconds)
            courier.service_remaining_seconds -= consumed
            remaining_seconds -= consumed
            if courier.service_remaining_seconds > 0:
                break
            complete_service(courier)
            continue

        if courier.movement_status in {"idle", "done"}:
            break

        if courier.path_cursor >= len(courier.path_coords) - 1:
            stop = stop_at_current_cursor(courier)
            if stop:
                start_service(courier, stop)
                continue
            courier.movement_status = "done"
            break

        current = courier.path_coords[courier.path_cursor]
        nxt = courier.path_coords[courier.path_cursor + 1]
        segment_length_m = haversine_km(current[0], current[1], nxt[0], nxt[1]) * 1000
        if segment_length_m <= 0:
            courier.path_cursor += 1
            continue

        distance_budget = speed_mps * remaining_seconds
        segment_remaining = segment_length_m - courier.segment_progress_m

        if distance_budget < segment_remaining:
            courier.segment_progress_m += distance_budget
            ratio = courier.segment_progress_m / segment_length_m
            courier.lat, courier.lon = interpolate(current, nxt, ratio)
            remaining_seconds = 0
            break

        time_used = segment_remaining / speed_mps if speed_mps > 0 else remaining_seconds
        courier.path_cursor += 1
        courier.segment_progress_m = 0.0
        courier.lat, courier.lon = nxt
        remaining_seconds -= time_used

        stop = stop_at_current_cursor(courier)
        if stop:
            courier.node = stop.node
            courier.lat = stop.lat
            courier.lon = stop.lon
            start_service(courier, stop)


async def advance_running_state() -> None:
    if not state.started or not state.running:
        return

    now = time.time()
    if state.last_update_at is None:
        state.last_update_at = now
        return

    elapsed = min(10.0, max(0.0, now - state.last_update_at))
    state.last_update_at = now
    if elapsed <= 0:
        return

    state.tick += 1
    for courier in state.couriers:
        advance_courier(courier, elapsed)

    await evaluate_return_pool()


def projected_load_before_insert(courier: Courier, insertion_index: int) -> int:
    load = courier.current_load
    for stop in pending_route(courier)[:insertion_index]:
        if stop.kind == "delivery":
            load -= stop.desi
        elif stop.kind == "return":
            load += stop.desi
    return load


def is_spatially_triggered(courier: Courier, job: ReturnJob) -> bool:
    if haversine_km(courier.lat, courier.lon, job.lat, job.lon) <= SPATIAL_TRIGGER_KM:
        return True
    stop = next_pending_stop(courier)
    return bool(
        stop and haversine_km(stop.lat, stop.lon, job.lat, job.lon) <= SPATIAL_TRIGGER_KM
    )


async def try_assign_return(job: ReturnJob) -> bool:
    best: tuple[float, Courier, int] | None = None
    distance_cache: dict[tuple[int, int], float] = {}

    def distance(a: int, b: int) -> float:
        key = (a, b)
        if key not in distance_cache:
            distance_cache[key] = shortest_path_length_m(a, b)
        return distance_cache[key]

    for courier in state.couriers:
        if not is_spatially_triggered(courier, job):
            continue

        route = pending_route(courier)
        if not route:
            continue

        chain_nodes = [nearest_node(courier.lat, courier.lon)] + [stop.node for stop in route]
        for idx in range(len(chain_nodes) - 1):
            projected_load = projected_load_before_insert(courier, idx)
            if projected_load + job.desi > courier.capacity_desi:
                continue

            a_node = chain_nodes[idx]
            b_node = chain_nodes[idx + 1]
            extra_cost = (
                distance(a_node, job.node)
                + distance(job.node, b_node)
                - distance(a_node, b_node)
            )
            if best is None or extra_cost < best[0]:
                best = (extra_cost, courier, idx)

    if best is None:
        job.message = "Yakinlik veya kapasite uygunlugu bulunamadi"
        return False

    extra_cost, courier, insertion_index = best
    return_stop = Stop(
        id=job.id,
        kind="return",
        label=f"Iade {job.desi} desi",
        lat=job.lat,
        lon=job.lon,
        node=job.node,
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
    job.message = f"{courier.name} rotasina eklendi (+{extra_cost / 1000:.2f} km)"
    state.completed_returns.append(job)
    state.messages.append(job.message)
    rebuild_courier_path(courier)
    return True


async def evaluate_return_pool() -> None:
    for job in list(state.pending_returns):
        assigned = await try_assign_return(job)
        if assigned:
            state.pending_returns.remove(job)


def remaining_polyline(courier: Courier) -> list[list[float]]:
    if not courier.path_coords:
        return [[courier.lat, courier.lon]]
    tail = courier.path_coords[courier.path_cursor + 1 :]
    return [[courier.lat, courier.lon]] + tail


def serialize_stop(stop: Stop) -> dict:
    return {
        "id": stop.id,
        "kind": stop.kind,
        "label": stop.label,
        "lat": stop.lat,
        "lon": stop.lon,
        "node": stop.node,
        "desi": stop.desi,
        "service_seconds": stop.service_seconds,
        "status": stop.status,
    }


def serialize_return(job: ReturnJob) -> dict:
    return {
        "id": job.id,
        "lat": job.lat,
        "lon": job.lon,
        "node": job.node,
        "desi": job.desi,
        "status": job.status,
        "assigned_courier_id": job.assigned_courier_id,
        "message": job.message,
        "created_at": job.created_at,
    }


def state_response() -> dict:
    return {
        "started": state.started,
        "running": state.running,
        "seed": state.seed,
        "tick": state.tick,
        "speed_kmh": SIM_SPEED_KMH,
        "graph_source": graph_source,
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
                "node": courier.node,
                "color": courier.color,
                "movement_status": courier.movement_status,
                "service_remaining_seconds": round(courier.service_remaining_seconds, 1),
                "route": [serialize_stop(stop) for stop in courier.route],
                "polyline": remaining_polyline(courier),
                "route_error": courier.route_error,
            }
            for courier in state.couriers
        ],
        "pending_returns": [serialize_return(job) for job in state.pending_returns],
        "completed_returns": [serialize_return(job) for job in state.completed_returns],
    }


@app.post("/api/sim/start")
async def start_simulation(request: StartRequest) -> dict:
    global state
    if request.min_deliveries > request.max_deliveries:
        raise HTTPException(status_code=400, detail="min_deliveries max_deliveries degerinden buyuk olamaz")

    get_graph()
    rng = random.Random(request.seed)
    used_points: set[int] = set()
    colors = ["#2563eb", "#f97316", "#16a34a", "#db2777", "#7c3aed", "#0891b2"]
    hub_node = nearest_node(KARABUK_CENTER["lat"], KARABUK_CENTER["lon"])
    hub_lat, hub_lon = node_lat_lon(hub_node)
    couriers: list[Courier] = []

    for index, vehicle in enumerate(request.vehicles):
        stop_count = rng.randint(request.min_deliveries, request.max_deliveries)
        desi_values = split_delivery_load(rng, vehicle.capacity_desi, stop_count)
        route = []
        for stop_index in range(stop_count):
            node = random_graph_node(rng, used_points)
            lat, lon = node_lat_lon(node)
            route.append(
                Stop(
                    id=str(uuid4()),
                    kind="delivery",
                    label=f"Teslimat {stop_index + 1}",
                    lat=lat,
                    lon=lon,
                    node=node,
                    desi=desi_values[stop_index],
                    service_seconds=3,
                )
            )
        route.append(
            Stop(
                id=str(uuid4()),
                kind="hub",
                label="Hub donus",
                lat=hub_lat,
                lon=hub_lon,
                node=hub_node,
                service_seconds=0,
            )
        )
        courier = Courier(
            id=vehicle.id or f"courier-{index + 1}",
            name=f"Arac {index + 1}",
            capacity_desi=vehicle.capacity_desi,
            current_load=sum(desi_values),
            lat=hub_lat,
            lon=hub_lon,
            node=hub_node,
            route=route,
            color=colors[index % len(colors)],
        )
        rebuild_courier_path(courier)
        couriers.append(courier)

    state = SimState(
        started=True,
        running=False,
        seed=request.seed,
        couriers=couriers,
        messages=[f"Simulasyon {len(couriers)} aracla baslatildi"],
    )
    return state_response()


@app.post("/api/sim/run")
async def run_simulation() -> dict:
    if not state.started:
        raise HTTPException(status_code=400, detail="Once simulasyonu baslatin")
    state.running = True
    state.last_update_at = time.time()
    state.messages.append("Canli izleme baslatildi")
    return state_response()


@app.post("/api/sim/pause")
async def pause_simulation() -> dict:
    await advance_running_state()
    state.running = False
    state.last_update_at = None
    state.messages.append("Canli izleme duraklatildi")
    return state_response()


@app.post("/api/returns")
async def create_return(request: ReturnRequest) -> dict:
    await advance_running_state()
    if not state.started:
        raise HTTPException(status_code=400, detail="Once simulasyonu baslatin")

    rng = random.Random(state.seed + len(state.pending_returns) + len(state.completed_returns) + 1000)
    if request.lat is not None and request.lon is not None:
        node = nearest_node(request.lat, request.lon)
    else:
        node = random_graph_node(rng, set())
    lat, lon = node_lat_lon(node)
    job = ReturnJob(
        id=str(uuid4()),
        lat=lat,
        lon=lon,
        node=node,
        desi=request.desi,
    )
    state.pending_returns.append(job)
    state.messages.append(f"{request.desi} desi iade havuza eklendi")
    await evaluate_return_pool()
    return state_response()


@app.post("/api/sim/tick")
async def tick() -> dict:
    if not state.started:
        raise HTTPException(status_code=400, detail="Once simulasyonu baslatin")
    for courier in state.couriers:
        advance_courier(courier, 5.0)
    state.tick += 1
    await evaluate_return_pool()
    return state_response()


@app.get("/api/sim/state")
async def get_state() -> dict:
    await advance_running_state()
    return state_response()


@app.get("/api/health")
async def health() -> dict:
    get_graph()
    return {
        "ok": True,
        "graph_source": graph_source,
        "graph_nodes": get_graph().number_of_nodes(),
        "graph_edges": get_graph().number_of_edges(),
        "speed_kmh": SIM_SPEED_KMH,
    }
