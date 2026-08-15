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

def draw_frame(
    ax_map,
    ax_bat,
    solution,
    ts_data,
    current_time,
    min_t,
    max_t,
    all_nodes,
):
    ax_map.clear()
    ax_bat.clear()

    ax_map.set_facecolor("#F8F9FA")
    ax_map.set_xticks([])
    ax_map.set_yticks([])

    hours = int(current_time)
    minutes = int((current_time - hours) * 60)
    seconds = int(
        (
            (current_time - hours) * 60 - minutes
        ) * 60
    )

    time_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

    ax_map.set_title(
        f"Simulation Time: {time_str}",
        fontsize=14,
        fontweight="bold",
        pad=10,
    )

    lats = [
        n["lat"]
        for n in all_nodes.values()
    ]

    lons = [
        n["lon"]
        for n in all_nodes.values()
    ]

    if lats and lons:
        ax_map.set_xlim(
            min(lons) - 0.005,
            max(lons) + 0.005,
        )

        ax_map.set_ylim(
            min(lats) - 0.005,
            max(lats) + 0.005,
        )

        avg_lat = sum(lats) / len(lats)
        aspect_ratio = 1.0 / math.cos(
            math.radians(avg_lat)
        )

        ax_map.set_aspect(
            aspect_ratio,
            adjustable="box",
        )

    for nid, node in all_nodes.items():
        if node["type"] == "DEPOT":
            ax_map.scatter(
                node["lon"],
                node["lat"],
                marker="s",
                color="black",
                s=120,
                zorder=5,
            )

        elif node["type"] == "CHARGING_STATION":
            ax_map.scatter(
                node["lon"],
                node["lat"],
                marker="P",
                color="#2ECC71",
                s=140,
                zorder=4,
            )

        else:
            ax_map.scatter(
                node["lon"],
                node["lat"],
                marker="o",
                color="#BDC3C7",
                s=30,
                zorder=3,
            )

    for vi, route in enumerate(solution.get("routes", [])):
        vid = route["vehicle_id"]

        color = VEHICLE_COLORS[
            vi % len(VEHICLE_COLORS)
        ]

        events = ts_data.get(vid, [])

        state = interpolate_state(
            events,
            current_time,
        )

        if state is None:
            continue

        lon = state["lon"]
        lat = state["lat"]
        battery = state["battery"]

        history = [
            ev
            for ev in events
            if ev["time"] <= current_time
        ]

        if history:
            hx = [
                ev["lon"]
                for ev in history
            ]

            hy = [
                ev["lat"]
                for ev in history
            ]

            hx.append(lon)
            hy.append(lat)

            ax_map.plot(
                hx,
                hy,
                color=color,
                linewidth=2,
                alpha=0.6,
                zorder=2,
            )

        ax_map.scatter(
            lon,
            lat,
            marker="o",
            color=color,
            s=180,
            edgecolors="white",
            linewidth=1.5,
            zorder=10,
        )

        ax_map.text(
            lon,
            lat + 0.0008,
            f"{vid}: {battery:.1f} kWh",
            fontsize=8,
            fontweight="bold",
            ha="center",
            va="bottom",
            zorder=11,
            bbox=dict(
                facecolor="white",
                alpha=0.85,
                edgecolor=color,
                boxstyle="round,pad=0.2",
            ),
        )

    ax_bat.set_title(
        "Real-time Vehicle Battery",
        fontsize=12,
        fontweight="bold",
    )

    ax_bat.set_xlim(
        min_t - 0.1,
        max_t + 0.1,
    )

    battery_capacity = config.VEHICLE_SPEC[
        "battery_kwh"
    ]

    ax_bat.set_ylim(
        0,
        battery_capacity + 2,
    )

    ax_bat.set_xlabel("Time (Hours)")
    ax_bat.set_ylabel("Battery (kWh)")
    ax_bat.grid(
        True,
        linestyle="--",
        alpha=0.5,
    )

    min_battery = (
        battery_capacity
        * config.VEHICLE_SPEC[
            "min_battery_safety_percent"
        ]
    )

    ax_bat.axhline(
        min_battery,
        color="red",
        linestyle="--",
        linewidth=1,
        alpha=0.7,
        label="Minimum SoC",
    )

    for vi, route in enumerate(
        solution.get("routes", [])
    ):
        vid = route["vehicle_id"]

        color = VEHICLE_COLORS[
            vi % len(VEHICLE_COLORS)
        ]

        events = ts_data.get(vid, [])

        state = interpolate_state(
            events,
            current_time,
        )

        history = [
            ev
            for ev in events
            if ev["time"] <= current_time
        ]

        if not history or state is None:
            continue

        hx = [
            ev["time"]
            for ev in history
        ]

        hy = [
            ev["battery"]
            for ev in history
        ]

        if (
            not hx
            or hx[-1] < current_time - 1e-9
        ):
            hx.append(current_time)
            hy.append(state["battery"])

        ax_bat.plot(
            hx,
            hy,
            color=color,
            linewidth=2,
            label=vid,
        )

        ax_bat.scatter(
            current_time,
            state["battery"],
            color=color,
            s=40,
            zorder=5,
        )

    handles, labels = ax_bat.get_legend_handles_labels()

    if labels:
        ax_bat.legend(
            handles,
            labels,
            loc="lower left",
            fontsize=8,
        )


def create_video(
    instance_name,
    fps=15,
    speed_multiplier=300.0,
):
    sol_path = os.path.join(
        ROOT_DIR,
        "data",
        "output",
        f"solution_{instance_name}.json",
    )

    with open(sol_path, "r", encoding="utf-8") as f:
        solution = json.load(f)

    inst_path = os.path.join(
        ROOT_DIR,
        "data",
        "instances",
        f"{instance_name}.json",
    )

    with open(inst_path, "r", encoding="utf-8") as f:
        instance = json.load(f)

    G = load_graph()

    all_nodes = build_node_coordinates(instance)

    ts_data = build_time_series(
        solution,
        G,
        all_nodes,
    )

    min_t = float("inf")
    max_t = float("-inf")

    for events in ts_data.values():
        if not events:
            continue

        min_t = min(
            min_t,
            events[0]["time"],
        )

        max_t = max(
            max_t,
            events[-1]["time"],
        )

    if (
        min_t == float("inf")
        or max_t <= min_t
    ):
        print("Không có dữ liệu thời gian hợp lệ.")
        return

    frames_dir = os.path.join(
        ROOT_DIR,
        "data",
        "output",
        "temp_frames",
    )

    if os.path.exists(frames_dir):
        shutil.rmtree(frames_dir)

    os.makedirs(
        frames_dir,
        exist_ok=True,
    )

    fig = plt.figure(
        figsize=(15, 8)
    )

    gs = gridspec.GridSpec(
        1,
        2,
        width_ratios=[1, 1.8],
    )

    ax_bat = fig.add_subplot(
        gs[0, 0]
    )

    ax_map = fig.add_subplot(
        gs[0, 1]
    )

    time_step_h = (
        speed_multiplier
        / 3600.0
        / fps
    )

    if time_step_h <= 0:
        raise ValueError(
            "speed_multiplier phải > 0"
        )

    current_time = min_t
    frame_idx = 0

    print("Rendering frames...")

    while current_time <= max_t + 1e-9:
        draw_frame(
            ax_map,
            ax_bat,
            solution,
            ts_data,
            current_time,
            min_t,
            max_t,
            all_nodes,
        )

        plt.tight_layout()

        frame_path = os.path.join(
            frames_dir,
            f"frame_{frame_idx:06d}.png",
        )

        plt.savefig(
            frame_path,
            dpi=100,
        )

        current_time += time_step_h
        frame_idx += 1

        if frame_idx % 20 == 0:
            print(
                f"   Rendered {frame_idx} frames "
                f"({current_time:.2f}h / {max_t:.2f}h)"
            )

    plt.close(fig)

    print(
        f"\nStitching {frame_idx} frames into MP4 with OpenCV..."
    )

    video_path = os.path.join(
        ROOT_DIR,
        "data",
        "output",
        f"video_{instance_name}.mp4",
    )

    first_frame_path = os.path.join(
        frames_dir,
        "frame_000000.png",
    )

    frame0 = cv2.imread(
        first_frame_path
    )

    if frame0 is None:
        shutil.rmtree(frames_dir)
        raise RuntimeError(
            "Không đọc được frame đầu tiên."
        )

    height, width = frame0.shape[:2]

    fourcc = cv2.VideoWriter_fourcc(
        *"mp4v"
    )

    video = cv2.VideoWriter(
        video_path,
        fourcc,
        fps,
        (width, height),
    )

    if not video.isOpened():
        shutil.rmtree(frames_dir)
        raise RuntimeError(
            "Không thể tạo file video."
        )

    for i in range(frame_idx):
        img_path = os.path.join(
            frames_dir,
            f"frame_{i:06d}.png",
        )

        frame = cv2.imread(img_path)

        if frame is not None:
            video.write(frame)

    video.release()
    cv2.destroyAllWindows()

    shutil.rmtree(frames_dir)

    print(
        f"\n[OK] Video saved to: {video_path}"
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Create MP4 animation for EVRP solution"
    )

    parser.add_argument(
        "--instance",
        default="sample_01",
    )

    parser.add_argument(
        "--fps",
        type=int,
        default=15,
    )

    parser.add_argument(
        "--speed",
        type=float,
        default=300.0,
    )

    args = parser.parse_args()

    create_video(
        args.instance,
        args.fps,
        args.speed,
    )