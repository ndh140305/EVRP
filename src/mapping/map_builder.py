import osmnx as ox
import networkx as nx
import sys
import os
import pickle

sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import config

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
    
    _root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    _out_path = os.path.join(_root, "data", "processed", "cau_giay_graph.pkl")
    os.makedirs(os.path.dirname(_out_path), exist_ok=True)
    
    with open(_out_path, "wb") as f:
        pickle.dump((graph, stations), f)
        
    print(f"Graph saved to {_out_path}")