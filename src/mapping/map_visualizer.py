import osmnx as ox
import networkx as nx
import matplotlib.pyplot as plt
import matplotlib.lines as mlines
import pickle
import os

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
GRAPH_PATH = os.path.join(ROOT_DIR, "data", "processed", "cau_giay_graph.pkl")
OUTPUT_PATH = os.path.join(ROOT_DIR, "data", "processed", "map_preview.png")


def load_and_visualize():
    with open(GRAPH_PATH, "rb") as f:
        data = pickle.load(f)
    G = data[0] if isinstance(data, tuple) else data

    node_colors = []
    node_sizes = []
    
    for node, data in G.nodes(data=True):
        if data.get('is_charging_station', False):
            node_colors.append('#E63946')  
            node_sizes.append(60)
        else:
            node_colors.append('#ADB5BD')  
            node_sizes.append(5)          

    fig, ax = ox.plot_graph(
        G, 
        node_color=node_colors, 
        node_size=node_sizes,
        edge_color='#6C757D',         
        edge_linewidth=0.6,             
        bgcolor='#FFFFFF',          
        show=False, 
        close=False,
        filepath=OUTPUT_PATH,
        save=True                       
    )
    
    ax.set_title("Bản đồ Cầu Giấy", fontsize=13, fontweight='bold', pad=15)

    plt.tight_layout()
    plt.show()

if __name__ == "__main__":
    load_and_visualize()