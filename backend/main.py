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
SIM_SPEED_KMH = float(os.getenv("SIM_SPEED_KMH", "70"))
GRAPH_PLACE = os.getenv("GRAPH_PLACE", "Karabuk Merkez, Karabuk, Turkiye")

# Working-hours & hub cargo generation
WORKING_HOURS_END_S = float(os.getenv("WORKING_HOURS_END_S", "28800"))   # 8 h → 10:00–18:00
HUB_CARGO_GEN_INTERVAL_S = float(os.getenv("HUB_CARGO_GEN_INTERVAL_S", "120"))  # every 2 sim-min
HUB_CARGO_GEN_MIN = int(os.getenv("HUB_CARGO_GEN_MIN", "1"))
HUB_CARGO_GEN_MAX = int(os.getenv("HUB_CARGO_GEN_MAX", "4"))
EOD_TIME_RATIO = 0.20       # last 20 % of shift = "time short"
MIN_RELOAD_LOAD_RATIO = 0.30  # < 30 % capacity filled = "load small"
SIM_DAY_START_HOUR = 10     # display offset: sim t=0 → 10:00

_hub_rng: random.Random = random.Random()
BACKEND_DIR = Path(__file__).resolve().parent
GRAPH_CACHE_PATH = Path(
    os.getenv("GRAPH_CACHE_PATH", str(BACKEND_DIR / "data" / "karabuk_drive.graphml"))
)

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
    cargos: list[CargoInput] = Field(default_factory=list)
    min_deliveries: int = Field(default=5, ge=1, le=12)
    max_deliveries: int = Field(default=7, ge=1, le=15)
    working_hours_end_s: float = Field(default=WORKING_HOURS_END_S, gt=0, le=86400)


class ReturnRequest(BaseModel):
    desi: int = Field(gt=0, le=500)
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class CargoInput(BaseModel):
    id: str | None = None
    desi: int = Field(gt=0, le=500)
    label: str | None = None
    lat: float | None = Field(default=None, ge=-90, le=90)
    lon: float | None = Field(default=None, ge=-180, le=180)


class SpeedRequest(BaseModel):
    multiplier: float = Field(default=1.0, ge=0.25, le=16.0)


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
    cargo_id: str | None = None


@dataclass
class HubCargo:
    id: str
    desi: int
    label: str
    lat: float
    lon: float
    node: int
    status: Literal["waiting", "assigned"] = "waiting"
    arrived_at: float = 0.0


@dataclass
class ReturnJob:
    id: str
    lat: float
    lon: float
    node: int
    desi: int
    status: Literal["pending", "assigned", "completed", "unassigned"] = "pending"
    assigned_courier_id: str | None = None
    created_at: float = field(default_factory=time.time)
    message: str = "Havuzda bekliyor"
    deferred: bool = False


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
    speed_multiplier: float = 4.0
    unassigned_cargos: list[dict] = field(default_factory=list)
    hub_cargo_pool: list[HubCargo] = field(default_factory=list)
    sim_elapsed_seconds: float = 0.0
    working_hours_end_s: float = WORKING_HOURS_END_S
    last_hub_cargo_gen_at: float = -WORKING_HOURS_END_S  # triggers first gen after one interval


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


def assign_cargos_geographic(
    cargo_nodes: list[tuple[CargoInput, int]],
    vehicles: list[VehicleInput],
    hub_node: int,
) -> tuple[list[list[tuple[CargoInput, int]]], list[tuple[CargoInput, int]]]:
    """
    Geographic-aware, capacity-constrained cargo assignment.

    Algorithm:
    - Sort cargos descending by desi (FFD-style capacity guard so large items
      are placed first, reducing fragmentation).
    - Each vehicle maintains a frontier node that starts at the hub.
    - Each cargo is assigned to the vehicle whose frontier is geographically
      closest (shortest network path), provided capacity allows.
    - After assignment the frontier advances to that cargo's node, so
      subsequent cargos naturally cluster in the same geographic zone.

    Result: vehicles receive geographically cohesive cargo groups rather
    than arbitrary capacity-fill groups, which lowers total travel distance.
    """
    sorted_items = sorted(cargo_nodes, key=lambda x: x[0].desi, reverse=True)
    loads = [0] * len(vehicles)
    assignments: list[list[tuple[CargoInput, int]]] = [[] for _ in vehicles]
    frontiers = [hub_node] * len(vehicles)
    unassigned: list[tuple[CargoInput, int]] = []

    for cargo, node in sorted_items:
        best_i: int | None = None
        best_cost = float("inf")
        for i, vehicle in enumerate(vehicles):
            if loads[i] + cargo.desi > vehicle.capacity_desi:
                continue
            cost = shortest_path_length_m(frontiers[i], node)
            if cost < best_cost:
                best_cost = cost
                best_i = i
        if best_i is None:
            unassigned.append((cargo, node))
        else:
            assignments[best_i].append((cargo, node))
            loads[best_i] += cargo.desi
            frontiers[best_i] = node

    return assignments, unassigned


def nearest_neighbor_sort(origin_node: int, stops: list[Stop]) -> list[Stop]:
    """Greedy nearest-neighbor ordering starting from origin_node."""
    if len(stops) <= 1:
        return stops
    remaining = list(stops)
    ordered: list[Stop] = []
    current = origin_node
    while remaining:
        closest = min(remaining, key=lambda s: shortest_path_length_m(current, s.node))
        ordered.append(closest)
        remaining.remove(closest)
        current = closest.node
    return ordered


def format_sim_clock(elapsed_s: float) -> str:
    total_m = int(elapsed_s / 60)
    h = SIM_DAY_START_HOUR + total_m // 60
    m = total_m % 60
    return f"{h:02d}:{m:02d}"


def serialize_hub_cargo(cargo: HubCargo) -> dict:
    return {
        "id": cargo.id,
        "desi": cargo.desi,
        "label": cargo.label,
        "lat": cargo.lat,
        "lon": cargo.lon,
        "node": cargo.node,
        "status": cargo.status,
        "arrived_at": cargo.arrived_at,
    }


def auto_generate_hub_cargos() -> None:
    """Spawn a random batch of delivery cargos into the hub pool."""
    occupied = occupied_stop_nodes()
    count = _hub_rng.randint(HUB_CARGO_GEN_MIN, HUB_CARGO_GEN_MAX)
    gen_idx = len(state.hub_cargo_pool)
    new_labels: list[str] = []
    for i in range(count):
        node = random_graph_node(_hub_rng, occupied)
        occupied.add(node)
        lat, lon = node_lat_lon(node)
        desi = _hub_rng.randint(5, 40)
        label = f"Hub Kargo {gen_idx + i + 1}"
        state.hub_cargo_pool.append(
            HubCargo(
                id=str(uuid4()),
                desi=desi,
                label=label,
                lat=lat,
                lon=lon,
                node=node,
                arrived_at=state.sim_elapsed_seconds,
            )
        )
        new_labels.append(f"{label} ({desi} desi)")
    state.messages.append(f"Hub'a {count} yeni kargo geldi: {', '.join(new_labels)}")
    state.last_hub_cargo_gen_at = state.sim_elapsed_seconds


def should_reload(courier: Courier, waiting: list[HubCargo]) -> bool:
    """
    Decide whether a returning vehicle should make another trip.

    Returns False if BOTH conditions hold simultaneously:
      - Time is short  : remaining shift < EOD_TIME_RATIO of total shift
      - Load is small  : assignable desi < MIN_RELOAD_LOAD_RATIO of capacity

    When only one condition holds (plenty of time OR plenty of cargo) the
    vehicle still goes — e.g. end-of-day but a large batch justifies the trip.
    """
    remaining = state.working_hours_end_s - state.sim_elapsed_seconds
    if remaining <= 0 or not waiting:
        return False

    fittable_desi = sum(c.desi for c in waiting if c.desi <= courier.capacity_desi)
    if fittable_desi == 0:
        return False

    load_ratio = min(1.0, fittable_desi / courier.capacity_desi)
    time_ratio = remaining / state.working_hours_end_s   # 1 = start, 0 = EOD

    time_short = time_ratio < EOD_TIME_RATIO
    load_small = load_ratio < MIN_RELOAD_LOAD_RATIO

    if time_short and load_small:
        state.messages.append(
            f"{courier.name}: mesai bitimine yakin ve kargo az — yeni tur yapilmadi"
        )
        return False
    return True


def try_reload_from_hub(courier: Courier) -> None:
    """
    Greedily assign waiting hub cargos to a vehicle that just returned.
    Uses nearest-to-current-frontier selection (geographic fill) so the
    new route stays geographically cohesive, then applies nearest-neighbor
    sequencing before dispatch.
    """
    waiting = [c for c in state.hub_cargo_pool if c.status == "waiting"]
    if not should_reload(courier, waiting):
        return

    # Geographic greedy fill — frontier starts at hub (courier.node)
    load = 0
    assigned: list[HubCargo] = []
    current_node = courier.node
    remaining = list(waiting)

    while remaining:
        best: tuple[float, HubCargo] | None = None
        for c in remaining:
            if load + c.desi > courier.capacity_desi:
                continue
            cost = shortest_path_length_m(current_node, c.node)
            if best is None or cost < best[0]:
                best = (cost, c)
        if best is None:
            break
        _, chosen = best
        assigned.append(chosen)
        load += chosen.desi
        current_node = chosen.node
        remaining.remove(chosen)

    if not assigned:
        return

    hub_node = courier.node
    hub_lat, hub_lon = node_lat_lon(hub_node)

    route: list[Stop] = []
    for cargo in assigned:
        route.append(
            Stop(
                id=str(uuid4()),
                kind="delivery",
                label=cargo.label,
                lat=cargo.lat,
                lon=cargo.lon,
                node=cargo.node,
                desi=cargo.desi,
                service_seconds=3,
                cargo_id=cargo.id,
            )
        )
        cargo.status = "assigned"

    if len(route) > 1:
        route = nearest_neighbor_sort(hub_node, route)

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

    courier.route = route
    courier.current_load = load
    rebuild_courier_path(courier)

    state.messages.append(
        f"{courier.name} hub'dan {load} desi ({len(assigned)} kargo) ile tekrar yola cikti"
    )


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


def normalize_highways(highway: object) -> set[str]:
    if isinstance(highway, str):
        return {highway}
    if isinstance(highway, list):
        return {str(item) for item in highway}
    return set()


def adjacent_highways(node: int) -> set[str]:
    graph = get_graph()
    highways: set[str] = set()
    for _, _, data in graph.edges(node, data=True):
        highways.update(normalize_highways(data.get("highway")))
    return highways


def node_is_far_enough(node: int, used: set[int], min_distance_km: float) -> bool:
    if node in used:
        return False
    if min_distance_km <= 0 or not used:
        return True

    lat, lon = node_lat_lon(node)
    for used_node in used:
        used_lat, used_lon = node_lat_lon(used_node)
        if haversine_km(lat, lon, used_lat, used_lon) < min_distance_km:
            return False
    return True


def random_graph_node(
    rng: random.Random,
    used: set[int],
    min_distance_km: float = 0.35,
) -> int:
    graph = get_graph()
    preferred_highways = {
        "residential",
        "service",
        "living_street",
        "tertiary",
        "secondary",
        "unclassified",
    }
    excluded_highways = {"motorway", "trunk"}
    candidates: list[int] = []
    fallback_candidates: list[int] = []

    for node, data in graph.nodes(data=True):
        if not node_is_far_enough(node, used, min_distance_km):
            continue
        lat = float(data["y"])
        lon = float(data["x"])
        if haversine_km(KARABUK_CENTER["lat"], KARABUK_CENTER["lon"], lat, lon) > 6.0:
            continue

        highways = adjacent_highways(node)
        if highways and highways.isdisjoint(excluded_highways):
            fallback_candidates.append(node)
        if highways & preferred_highways:
            candidates.append(node)

    pool = candidates or fallback_candidates
    if pool:
        node = rng.choice(pool)
        used.add(node)
        return int(node)

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
        if not any(job.id == stop.id for job in state.completed_returns):
            state.completed_returns.append(
                ReturnJob(
                    id=stop.id,
                    lat=stop.lat,
                    lon=stop.lon,
                    node=stop.node,
                    desi=stop.desi,
                    status="completed",
                    assigned_courier_id=courier.id,
                    message=f"{courier.name} tarafindan tamamlandi",
                )
            )

    courier.active_stop_id = None
    courier.service_remaining_seconds = 0.0
    rebuild_courier_path(courier)

    # Vehicle just returned to hub with no remaining deliveries → attempt reload
    if stop is not None and stop.kind == "hub" and courier.movement_status == "done":
        try_reload_from_hub(courier)


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

    elapsed = min(10.0, max(0.0, now - state.last_update_at)) * state.speed_multiplier
    state.last_update_at = now
    if elapsed <= 0:
        return

    state.tick += 1
    state.sim_elapsed_seconds += elapsed

    # Auto-generate hub cargos on interval, only during working hours
    if (state.sim_elapsed_seconds < state.working_hours_end_s
            and state.sim_elapsed_seconds - state.last_hub_cargo_gen_at >= HUB_CARGO_GEN_INTERVAL_S):
        auto_generate_hub_cargos()

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
        if not job.deferred:
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
    job.deferred = False
    job.message = f"{courier.name} rotasina eklendi (+{extra_cost / 1000:.2f} km)"
    state.messages.append(job.message)
    rebuild_courier_path(courier)
    return True


def simulation_finished() -> bool:
    return state.started and bool(state.couriers) and all(
        courier.movement_status == "done" for courier in state.couriers
    )


def defer_pending_returns() -> None:
    if not state.pending_returns or not simulation_finished():
        return

    changed = False
    for job in state.pending_returns:
        if job.status == "pending" and not job.deferred:
            job.deferred = True
            job.message = "Yarina ertelendi - oncelikli"
            changed = True

    state.pending_returns.sort(key=lambda job: (not job.deferred, job.created_at))
    if changed:
        state.running = False
        state.last_update_at = None
        state.messages.append("Atanamayan iadeler yarina ertelendi ve onceliklendirildi")


async def evaluate_return_pool() -> None:
    state.pending_returns.sort(key=lambda job: (not job.deferred, job.created_at))
    assigned_jobs: list[ReturnJob] = []
    for job in list(state.pending_returns):
        if await try_assign_return(job):
            assigned_jobs.append(job)
    if assigned_jobs:
        assigned_ids = {j.id for j in assigned_jobs}
        state.pending_returns = [j for j in state.pending_returns if j.id not in assigned_ids]
    defer_pending_returns()


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
        "cargo_id": stop.cargo_id,
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
        "deferred": job.deferred,
    }


def occupied_stop_nodes() -> set[int]:
    nodes: set[int] = set()
    for courier in state.couriers:
        nodes.add(courier.node)
        nodes.update(stop.node for stop in courier.route)
    nodes.update(job.node for job in state.pending_returns)
    nodes.update(job.node for job in state.completed_returns)
    nodes.update(cargo.node for cargo in state.hub_cargo_pool)
    return nodes


def state_response() -> dict:
    return {
        "started": state.started,
        "running": state.running,
        "seed": state.seed,
        "tick": state.tick,
        "speed_kmh": SIM_SPEED_KMH,
        "speed_multiplier": state.speed_multiplier,
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
        "unassigned_cargos": state.unassigned_cargos,
        "hub_cargo_pool": [serialize_hub_cargo(c) for c in state.hub_cargo_pool],
        "sim_elapsed_seconds": state.sim_elapsed_seconds,
        "working_hours_end_s": state.working_hours_end_s,
        "sim_clock": format_sim_clock(state.sim_elapsed_seconds),
        "end_clock": format_sim_clock(state.working_hours_end_s),
    }


@app.post("/api/sim/start")
async def start_simulation(request: StartRequest) -> dict:
    global state
    if request.min_deliveries > request.max_deliveries:
        raise HTTPException(status_code=400, detail="min_deliveries max_deliveries degerinden buyuk olamaz")

    deferred_returns = [
        job for job in state.pending_returns if job.deferred and job.status == "pending"
    ]
    get_graph()
    rng = random.Random(request.seed)
    _hub_rng.seed(request.seed + 9999)  # separate stream so hub gen is independent
    used_points: set[int] = set()
    colors = ["#2563eb", "#f97316", "#16a34a", "#db2777", "#7c3aed", "#0891b2"]
    hub_node = nearest_node(KARABUK_CENTER["lat"], KARABUK_CENTER["lon"])
    hub_lat, hub_lon = node_lat_lon(hub_node)
    couriers: list[Courier] = []
    unassigned_cargo_dicts: list[dict] = []

    if request.cargos:
        # Step 1 — Resolve every cargo to an OSM node before assignment.
        # Known lat/lon (future real-address support) snapped to nearest node;
        # otherwise a random graph node is drawn from the shared pool so
        # cargo locations don't overlap each other or existing stops.
        cargo_nodes: list[tuple[CargoInput, int]] = []
        for cargo in request.cargos:
            if cargo.lat is not None and cargo.lon is not None:
                node = nearest_node(cargo.lat, cargo.lon)
            else:
                node = random_graph_node(rng, used_points)
            cargo_nodes.append((cargo, node))

        # Step 2 — Geographic-aware capacity assignment.
        # Each vehicle's frontier starts at the hub; each cargo goes to the
        # vehicle whose frontier is closest (network distance), capacity permitting.
        # This naturally forms geographic clusters instead of arbitrary desi-fill.
        vehicle_assignments, unassigned_pairs = assign_cargos_geographic(
            cargo_nodes, request.vehicles, hub_node
        )
        unassigned_cargo_dicts = [
            {"id": c.id, "desi": c.desi, "label": c.label or c.id or "?"}
            for c, _ in unassigned_pairs
        ]

        # Step 3 — Build per-vehicle routes and optimise delivery sequence.
        for index, vehicle in enumerate(request.vehicles):
            assigned_pairs = vehicle_assignments[index]
            route: list[Stop] = []

            for cargo, node in assigned_pairs:
                lat, lon = node_lat_lon(node)
                route.append(
                    Stop(
                        id=str(uuid4()),
                        kind="delivery",
                        label=cargo.label or f"Kargo {index + 1}-{len(route) + 1}",
                        lat=lat,
                        lon=lon,
                        node=node,
                        desi=cargo.desi,
                        service_seconds=3,
                        cargo_id=cargo.id,
                    )
                )

            # Nearest-neighbor sort within each vehicle's zone.
            # Geographic assignment clusters cargos per vehicle;
            # this pass then minimises the in-zone travel sequence.
            if len(route) > 1:
                route = nearest_neighbor_sort(hub_node, route)

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

            total_load = sum(c.desi for c, _ in assigned_pairs)
            courier = Courier(
                id=vehicle.id or f"courier-{index + 1}",
                name=f"Arac {index + 1}",
                capacity_desi=vehicle.capacity_desi,
                current_load=total_load,
                lat=hub_lat,
                lon=hub_lon,
                node=hub_node,
                route=route,
                color=colors[index % len(colors)],
            )
            rebuild_courier_path(courier)
            couriers.append(courier)

    else:
        # No explicit cargos: generate random stops then cluster geographically
        # so each vehicle services a contiguous zone instead of criss-crossing.
        all_cargo_nodes: list[tuple[CargoInput, int]] = []
        for v_index, vehicle in enumerate(request.vehicles):
            stop_count = rng.randint(request.min_deliveries, request.max_deliveries)
            for j in range(stop_count):
                node = random_graph_node(rng, used_points)
                desi = rng.randint(5, min(40, vehicle.capacity_desi))
                all_cargo_nodes.append((
                    CargoInput(id=f"auto-{v_index}-{j}", desi=desi),
                    node,
                ))

        vehicle_assignments, _ = assign_cargos_geographic(
            all_cargo_nodes, request.vehicles, hub_node
        )

        for index, vehicle in enumerate(request.vehicles):
            assigned_pairs = vehicle_assignments[index]
            route: list[Stop] = []
            for stop_num, (cargo, node) in enumerate(assigned_pairs):
                lat, lon = node_lat_lon(node)
                route.append(
                    Stop(
                        id=str(uuid4()),
                        kind="delivery",
                        label=f"Teslimat {stop_num + 1}",
                        lat=lat,
                        lon=lon,
                        node=node,
                        desi=cargo.desi,
                        service_seconds=3,
                    )
                )

            if len(route) > 1:
                route = nearest_neighbor_sort(hub_node, route)

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
                current_load=sum(c.desi for c, _ in assigned_pairs),
                lat=hub_lat,
                lon=hub_lon,
                node=hub_node,
                route=route,
                color=colors[index % len(colors)],
            )
            rebuild_courier_path(courier)
            couriers.append(courier)

    messages = [f"Simulasyon {len(couriers)} aracla baslatildi"]
    if unassigned_cargo_dicts:
        messages.append(
            f"{len(unassigned_cargo_dicts)} kargo kapasiteye sigmadi ve atanamadi"
        )

    state = SimState(
        started=True,
        running=False,
        seed=request.seed,
        couriers=couriers,
        pending_returns=deferred_returns,
        speed_multiplier=state.speed_multiplier,
        messages=messages,
        unassigned_cargos=unassigned_cargo_dicts,
        working_hours_end_s=request.working_hours_end_s,
        sim_elapsed_seconds=0.0,
        last_hub_cargo_gen_at=-HUB_CARGO_GEN_INTERVAL_S,  # first gen fires after one interval
    )
    if deferred_returns:
        state.messages.append(f"{len(deferred_returns)} ertelenen iade oncelikli havuza tasindi")
        await evaluate_return_pool()
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


@app.post("/api/sim/speed")
async def set_simulation_speed(request: SpeedRequest) -> dict:
    await advance_running_state()
    state.speed_multiplier = request.multiplier
    if state.running:
        state.last_update_at = time.time()
    state.messages.append(f"Simulasyon hizi {request.multiplier:g}x yapildi")
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
        node = random_graph_node(rng, occupied_stop_nodes())
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
        advance_courier(courier, 5.0 * state.speed_multiplier)
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
