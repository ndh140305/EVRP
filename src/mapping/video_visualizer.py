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

