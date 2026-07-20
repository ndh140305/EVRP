import osmnx as ox
import networkx as nx
import matplotlib.pyplot as plt
import os
import pickle

def load_and_visualize():
    graph_path = os.path.join("data", "processed", "cau_giay_graph.pkl")
    if not os.path.exists(graph_path):
        graph_path = os.path.join("..", "..", "data", "processed", "cau_giay_graph.pkl")
        
    with open(graph_path, "rb") as f:
        G = pickle.load(f)

    node_colors = []
    node_sizes = []
    
    for node, data in G.nodes(data=True):
        if data.get('is_charging_station', False):
            node_colors.append('#FF0000')
            node_sizes.append(80)
        else:
            node_colors.append('#999999')
            node_sizes.append(15)
            
    fig, ax = ox.plot_graph(
        G, 
        node_color=node_colors, 
        node_size=node_sizes,
        edge_color='#CCCCCC', 
        edge_linewidth=0.8,
        show=False, 
        close=False
    )
    ax.set_title("Bản đồ Cầu Giấy)", fontsize=14)
    plt.show()

if __name__ == "__main__":
    load_and_visualize()