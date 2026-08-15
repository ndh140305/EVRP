import os
import sys
import json
import pickle
import math
import shutil
import argparse
from datetime import datetime

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.extend([ROOT_DIR, SRC_DIR])

import config

import matplotlib.pyplot as plt
import matplotlib.gridspec as gridspec
import cv2

VEHICLE_COLORS = [
    "#E63946",
    "#2196F3",
    "#4CAF50",
    "#FF9800",
    "#9C27B0",
    "#00BCD4",
]

def parse_time(time_str):
    try:
        h, m, s = map(int, time_str.split(":"))
        return h + m / 60.0 + s / 3600.0
    except (ValueError, AttributeError):
        return 0.0

def load_graph(graph_path=None):
    path = graph_path or os.path.join(
        ROOT_DIR,
        "data",
        "processed",
        "cau_giay_graph.pkl",
    )

    with open(path, "rb") as f:
        data = pickle.load(f)

    return data[0] if isinstance(data, tuple) else data

def osm_path_to_latlons(G, osm_ids):
    if not osm_ids:
        return []

    clean_ids = []

    for nid in osm_ids:
        if not clean_ids or nid != clean_ids[-1]:
            clean_ids.append(nid)

    if not clean_ids:
        return []

    if len(clean_ids) == 1:
        if clean_ids[0] in G.nodes:
            n = G.nodes[clean_ids[0]]
            return [(n["y"], n["x"])]
        return []

    coords = []

    for i in range(len(clean_ids) - 1):
        u = clean_ids[i]
        v = clean_ids[i + 1]

        if u not in G.nodes or v not in G.nodes:
            continue

        if G.has_edge(u, v):
            edge_data = G.get_edge_data(u, v)

            if edge_data:
                edge = list(edge_data.values())[0]

                if isinstance(edge, dict) and "geometry" in edge:
                    geom = edge["geometry"]

                    try:
                        geom_pts = [
                            (lat, lon)
                            for lon, lat in geom.coords
                        ]
                    except Exception:
                        geom_pts = []

                    if geom_pts:
                        if coords and coords[-1] == geom_pts[0]:
                            coords.extend(geom_pts[1:])
                        else:
                            coords.extend(geom_pts)

                        continue

        node_u = G.nodes[u]
        pt_u = (node_u["y"], node_u["x"])

        if not coords or coords[-1] != pt_u:
            coords.append(pt_u)

    last_id = clean_ids[-1]

    if last_id in G.nodes:
        node_last = G.nodes[last_id]
        pt_last = (node_last["y"], node_last["x"])

        if not coords or coords[-1] != pt_last:
            coords.append(pt_last)

    return coords

def haversine_dist(lat1, lon1, lat2, lon2):
    R = 6371000.0

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)

    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1)
        * math.cos(phi2)
        * math.sin(dlambda / 2) ** 2
    )

    return 2 * R * math.atan2(
        math.sqrt(a),
        math.sqrt(1 - a),
    )

def build_node_coordinates(instance):
    node_coords = {}

    depot_id = config.DEPOT["id"]

    node_coords[depot_id] = {
        "lat": config.DEPOT["lat"],
        "lon": config.DEPOT["lon"],
        "type": "DEPOT",
    }

    for sid, info in config.VINFAST_STATIONS.items():
        node_coords[sid] = {
            "lat": info["lat"],
            "lon": info["lon"],
            "type": "CHARGING_STATION",
        }

    for customer in instance["customers"]:
        node_coords[customer["id"]] = {
            "lat": customer["lat"],
            "lon": customer["lon"],
            "type": "CUSTOMER",
        }

    return node_coords

def interpolate_segment(coords, start_time, end_time, start_battery, end_battery):
    if not coords:
        return []

    if len(coords) == 1:
        return [
            {
                "time": start_time,
                "lat": coords[0][0],
                "lon": coords[0][1],
                "battery": start_battery,
                "phase": "move",
            }
        ]

    distances = []

    for i in range(len(coords) - 1):
        distances.append(
            haversine_dist(
                coords[i][0],
                coords[i][1],
                coords[i + 1][0],
                coords[i + 1][1],
            )
        )

    total_distance = sum(distances)

    if total_distance <= 1e-9:
        ratios = [
            i / (len(coords) - 1)
            for i in range(len(coords))
        ]
    else:
        ratios = [0.0]
        cumulative = 0.0

        for d in distances:
            cumulative += d
            ratios.append(cumulative / total_distance)

    events = []

    duration = max(0.0, end_time - start_time)

    for i, point in enumerate(coords):
        ratio = ratios[i]

        events.append(
            {
                "time": start_time + duration * ratio,
                "lat": point[0],
                "lon": point[1],
                "battery": (
                    start_battery
                    + (end_battery - start_battery) * ratio
                ),
                "phase": "move",
            }
        )

    return events

def build_time_series(solution, G, node_coords):
    ts_data = {}

    for route in solution.get("routes", []):
        vid = route["vehicle_id"]
        stops = route.get("stops", [])

        events = []

        if not stops:
            ts_data[vid] = []
            continue

        for i, stop in enumerate(stops):
            node_id = stop["node_id"]

            arrival = parse_time(stop.get("arrival_time", "00:00:00"))
            departure = parse_time(
                stop.get("departure_time", stop.get("arrival_time", "00:00:00"))
            )

            battery_arrival = float(
                stop.get("battery_arrival_kwh", 0.0)
            )

            battery_departure = float(
                stop.get("battery_departure_kwh", battery_arrival)
            )

            if i == 0:
                if node_id in node_coords:
                    lat = node_coords[node_id]["lat"]
                    lon = node_coords[node_id]["lon"]
                else:
                    lat = config.DEPOT["lat"]
                    lon = config.DEPOT["lon"]

                events.append(
                    {
                        "time": arrival,
                        "lat": lat,
                        "lon": lon,
                        "battery": battery_arrival,
                        "phase": "arrive",
                    }
                )

                if departure > arrival + 1e-9:
                    events.append(
                        {
                            "time": departure,
                            "lat": lat,
                            "lon": lon,
                            "battery": battery_departure,
                            "phase": "depart",
                        }
                    )

                continue

            prev_stop = stops[i - 1]

            prev_departure = parse_time(
                prev_stop.get("departure_time", prev_stop.get("arrival_time"))
            )

            prev_battery = float(
                prev_stop.get("battery_departure_kwh", 0.0)
            )

            osm_path = stop.get("osm_path_from_prev", [])

            coords = osm_path_to_latlons(G, osm_path)

            if len(coords) < 2:
                prev_id = prev_stop["node_id"]

                if prev_id in node_coords:
                    prev_lat = node_coords[prev_id]["lat"]
                    prev_lon = node_coords[prev_id]["lon"]
                else:
                    prev_lat = config.DEPOT["lat"]
                    prev_lon = config.DEPOT["lon"]

                if node_id in node_coords:
                    cur_lat = node_coords[node_id]["lat"]
                    cur_lon = node_coords[node_id]["lon"]
                else:
                    cur_lat = prev_lat
                    cur_lon = prev_lon

                coords = [
                    (prev_lat, prev_lon),
                    (cur_lat, cur_lon),
                ]

            move_start = prev_departure
            move_end = max(arrival, move_start)

            move_events = interpolate_segment(
                coords,
                move_start,
                move_end,
                prev_battery,
                battery_arrival,
            )

            if events:
                last_time = events[-1]["time"]

                for event in move_events:
                    if event["time"] > last_time + 1e-9:
                        events.append(event)

            else:
                events.extend(move_events)

            if node_id in node_coords:
                lat = node_coords[node_id]["lat"]
                lon = node_coords[node_id]["lon"]
            elif coords:
                lat = coords[-1][0]
                lon = coords[-1][1]
            else:
                lat = config.DEPOT["lat"]
                lon = config.DEPOT["lon"]

            if not events or arrival > events[-1]["time"] + 1e-9:
                events.append(
                    {
                        "time": arrival,
                        "lat": lat,
                        "lon": lon,
                        "battery": battery_arrival,
                        "phase": "arrive",
                    }
                )
            else:
                events.append(
                    {
                        "time": arrival,
                        "lat": lat,
                        "lon": lon,
                        "battery": battery_arrival,
                        "phase": "arrive",
                    }
                )

            if departure > arrival + 1e-9:
                events.append(
                    {
                        "time": departure,
                        "lat": lat,
                        "lon": lon,
                        "battery": battery_departure,
                        "phase": (
                            "charge"
                            if battery_departure > battery_arrival + 1e-6
                            else "service"
                        ),
                    }
                )

        events.sort(key=lambda x: x["time"])

        cleaned = []

        for event in events:
            if not cleaned:
                cleaned.append(event)
                continue

            previous = cleaned[-1]

            if abs(event["time"] - previous["time"]) < 1e-9:
                if event["phase"] in ("arrive", "charge", "service", "depart"):
                    cleaned[-1] = event
                continue

            cleaned.append(event)

        ts_data[vid] = cleaned

    return ts_data

def interpolate_state(events, target_time):
    if not events:
        return None

    if target_time <= events[0]["time"]:
        return dict(events[0])

    if target_time >= events[-1]["time"]:
        return dict(events[-1])

    left = None
    right = None

    for i in range(len(events) - 1):
        e1 = events[i]
        e2 = events[i + 1]

        if e1["time"] <= target_time <= e2["time"]:
            left = e1
            right = e2
            break

    if left is None or right is None:
        return dict(events[-1])

    dt = right["time"] - left["time"]

    if dt <= 1e-9:
        return {
            "time": target_time,
            "lat": right["lat"],
            "lon": right["lon"],
            "battery": right["battery"],
            "phase": right["phase"],
        }

    ratio = (
        target_time - left["time"]
    ) / dt

    ratio = max(0.0, min(1.0, ratio))

    return {
        "time": target_time,
        "lat": left["lat"]
        + ratio * (right["lat"] - left["lat"]),
        "lon": left["lon"]
        + ratio * (right["lon"] - left["lon"]),
        "battery": left["battery"]
        + ratio * (right["battery"] - left["battery"]),
        "phase": left["phase"],
    }

