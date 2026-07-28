import pickle
import os
import sys
import networkx as nx
import osmnx as ox

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.extend([ROOT_DIR, SRC_DIR])

GRAPH_PATH = os.path.join(ROOT_DIR, "data", "processed", "cau_giay_graph.pkl")
DATA_DIR = os.path.join(ROOT_DIR, "data", "processed")


def build_graph_pickle(path: str = GRAPH_PATH):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    try:
        from mapping import map_builder
    except ImportError as exc:
        raise ImportError(f"Cannot build graph: {exc}") from exc
    print("Graph pickle not found. Building from OpenStreetMap...")
    G, station_nodes = map_builder.build_cau_giay_graph()
    with open(path, "wb") as f:
        pickle.dump((G, station_nodes), f)
    print(f"Graph saved: {os.path.abspath(path)}")
    return G, station_nodes


def load_graph(path: str = GRAPH_PATH):
    resolved = os.path.abspath(path)
    if not os.path.exists(resolved):
        return build_graph_pickle(resolved)
    with open(resolved, "rb") as f:
        data = pickle.load(f)
    return data if isinstance(data, tuple) else (data, {})


def snap_to_graph(G: nx.MultiDiGraph, named_coords: dict[str, tuple[float, float]]) -> dict[str, int]:
    # Snap tọa độ của từng điểm về OSM node gần nhất trên graph.
    return {
        name: ox.nearest_nodes(G, X=lon, Y=lat)
        for name, (lat, lon) in named_coords.items()
    }


def build_distance_matrix(
    G: nx.MultiDiGraph,
    named_nodes: dict[str, int],
    save_paths: bool = True,
) -> dict:
    
    # tính khoảng cách và thời gian ngắn nhất giữa 2 node bất kỳ
    
    names = list(named_nodes.keys())
    n = len(names)

    dist_m: dict[tuple, float] = {}
    time_s: dict[tuple, float] = {}
    paths: dict[tuple, list] = {}

    for i, name_a in enumerate(names):
        osm_a = named_nodes[name_a]

        len_map = nx.single_source_dijkstra_path_length(G, osm_a, weight="length")
        time_map = nx.single_source_dijkstra_path_length(G, osm_a, weight="travel_time")
        path_map = nx.single_source_dijkstra_path(G, osm_a, weight="travel_time") if save_paths else {}

        for name_b in names:
            osm_b = named_nodes[name_b]
            key = (name_a, name_b)
            dist_m[key] = len_map.get(osm_b, float("inf"))
            time_s[key] = time_map.get(osm_b, float("inf"))
            if save_paths:
                paths[key] = path_map.get(osm_b, [])

        print(f"  [{i + 1}/{n}] {name_a}")

    return {
        "node_names": names,
        "osm_ids": named_nodes,
        "distance_m": dist_m,
        "distance_km": {k: v / 1000.0 for k, v in dist_m.items()},
        "travel_time_s": time_s,
        "paths": paths,
    }


def compute_and_save(
    named_coords: dict[str, tuple[float, float]],
    output_name: str = "distance_matrix",
    graph_path: str = GRAPH_PATH,
    save_paths: bool = True,
) -> dict:
    
    # nhận tọa độ khách và trạm sạc rồi dựng ma trận khoảng cách
    G, _ = load_graph(graph_path)
    print(f"Graph loaded: {len(G.nodes)} nodes, {len(G.edges)} edges")

    named_nodes = snap_to_graph(G, named_coords)
    print(f"Snapped {len(named_nodes)} points to OSM graph")

    print("Computing shortest paths...")
    matrix = build_distance_matrix(G, named_nodes, save_paths=save_paths)

    out_path = os.path.join(DATA_DIR, f"{output_name}.pkl")
    os.makedirs(DATA_DIR, exist_ok=True)
    with open(out_path, "wb") as f:
        pickle.dump(matrix, f)
    print(f"Saved: {os.path.abspath(out_path)}")

    return matrix


def load_distance_matrix(name: str = "distance_matrix") -> dict:
    path = os.path.join(DATA_DIR, f"{name}.pkl")
    with open(os.path.abspath(path), "rb") as f:
        return pickle.load(f)


def print_matrix(matrix: dict, metric: str = "distance_km"):
    names = matrix["node_names"]
    data = matrix[metric]
    unit = {"distance_km": "km", "distance_m": "m", "travel_time_s": "s"}.get(metric, "")

    col_w = max(12, max(len(n) for n in names) + 2)
    header = f"{'':>{col_w}}" + "".join(f"{n:>{col_w}}" for n in names)
    print(header)
    print("-" * len(header))
    for a in names:
        row = f"{a:>{col_w}}" + "".join(
            f"{data.get((a, b), float('inf')):>{col_w}.2f}" for b in names
        )
        print(row)
    print(f"\n(unit: {unit})\n")


if __name__ == "__main__":
    import config

    all_points: dict[str, tuple[float, float]] = {}

    all_points["Depot"] = (21.0365, 105.7832)

    for name, (lat, lon) in config.VINFAST_STATIONS.items():
        all_points[name] = (lat, lon)

    matrix = compute_and_save(
        named_coords=all_points,
        output_name="distance_matrix",
        save_paths=True,
    )

    print("\nDistance matrix (km):")
    print_matrix(matrix, metric="distance_km")

    print("Travel time matrix (s):")
    print_matrix(matrix, metric="travel_time_s")
