import osmnx as ox
import networkx as nx
import sys
import os
import pickle

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
import config

GRAPH_PATH = os.path.join(ROOT_DIR, "data", "processed", "cau_giay_graph.pkl")

def build_cau_giay_graph():
    G = ox.graph_from_place(config.PLACE_NAME, network_type=config.NETWORK_TYPE)
    print(f"Download map success with {len(G.nodes)} nodes and {len(G.edges)} edges.")
    
    G = ox.add_edge_speeds(G, fallback=config.DEFAULT_SPEED_KMH)
    G = ox.add_edge_travel_times(G)

    largest_scc = max(nx.strongly_connected_components(G), key=len)
    G = G.subgraph(largest_scc).copy()
    print(f"After SCC filter: {len(G.nodes)} nodes, {len(G.edges)} edges.")
    
    station_nodes = {}
    for name, coords in config.VINFAST_STATIONS.items():
        nearest_node = ox.nearest_nodes(G, X=coords[1], Y=coords[0])
        station_nodes[name] = nearest_node
        
        G.nodes[nearest_node]['is_charging_station'] = True
        G.nodes[nearest_node]['station_name'] = name
    
    return G, station_nodes

if __name__ == "__main__":
    graph, stations = build_cau_giay_graph()

    os.makedirs(os.path.dirname(GRAPH_PATH), exist_ok=True)

    with open(GRAPH_PATH, "wb") as f:
        pickle.dump((graph, stations), f)

    print(f"Graph saved to {GRAPH_PATH}")