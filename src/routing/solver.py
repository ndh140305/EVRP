import pickle
import os
import sys
import json
import numpy as np
from ortools.constraint_solver import routing_enums_pb2
from ortools.constraint_solver import pywrapcp

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
import config


class ORToolsEVRPTWSolver:
    def __init__(self, instance_path: str, matrix_path: str = None):
        with open(instance_path, "r", encoding="utf-8") as f:
            self.instance = json.load(f)
        self.instance_name = self.instance["instance_name"]

        if not matrix_path:
            matrix_path = os.path.join(
                ROOT_DIR, "data", "processed", f"matrix_{self.instance_name}.pkl"
            )
        with open(matrix_path, "rb") as f:
            self.matrix_data = pickle.load(f)

        self.depot = config.DEPOT
        self.spec = config.VEHICLE_SPEC
        self.params = config.SYSTEM_PARAMS
        self.stations = config.VINFAST_STATIONS

        self.setup_data_model()

    def setup_data_model(self):
        self.customers = self.instance["customers"]
        self.num_vehicles = self.instance.get("num_vehicles", 5)

        self.nodes = []
        self.node_id_to_index = {}

        depot_start_sec = self.depot["tw_open"] * 60
        depot_end_sec = self.depot["tw_close"] * 60
        depot_duration_sec = depot_end_sec - depot_start_sec

        self.nodes.append({
            "id": self.depot["id"],
            "type": "DEPOT",
            "demand": 0,
            "tw_open": 0,
            "tw_close": depot_duration_sec,
            "service_time": 0,
        })
        self.node_id_to_index[self.depot["id"]] = 0

        for c in self.customers:
            self.nodes.append({
                "id": c["id"],
                "type": "CUSTOMER",
                "demand": c["demand_kg"],
                "tw_open": max(0, c["tw_open"] * 60 - depot_start_sec),
                "tw_close": max(0, c["tw_close"] * 60 - depot_start_sec),
                "service_time": c["service_time_min"] * 60,
            })
            self.node_id_to_index[c["id"]] = len(self.nodes) - 1

        self.num_dummies_per_station = max(self.num_vehicles, 3)
        self.station_indices = []

        battery_usable_kwh = self.spec["battery_kwh"] * (
            1.0 - self.spec["min_battery_safety_percent"]
        )

        for sid, info in self.stations.items():
            charge_time_sec = int(
                (battery_usable_kwh / info["charging_rate_kw"]) * 3600
            )
            for m in range(self.num_dummies_per_station):
                dummy_id = f"{sid}_d{m}"
                self.nodes.append({
                    "id": dummy_id,
                    "original_id": sid,
                    "type": "CHARGING_STATION",
                    "demand": 0,
                    "tw_open": 0,
                    "tw_close": depot_duration_sec,
                    "service_time": charge_time_sec,
                })
                idx = len(self.nodes) - 1
                self.node_id_to_index[dummy_id] = idx
                self.station_indices.append(idx)

        self.num_nodes = len(self.nodes)

        physical_ids = [
            node.get("original_id", node["id"]) for node in self.nodes
        ]
        dist_dict = self.matrix_data["distance_km"]
        time_dict = self.matrix_data["travel_time_s"]

        self.distance_matrix = np.zeros((self.num_nodes, self.num_nodes))
        self.travel_time_matrix = np.zeros((self.num_nodes, self.num_nodes))

        for i in range(self.num_nodes):
            for j in range(self.num_nodes):
                key = (physical_ids[i], physical_ids[j])
                self.distance_matrix[i, j] = dist_dict.get(key, 0.0)
                self.travel_time_matrix[i, j] = time_dict.get(key, 0.0)

if __name__ == "__main__":
    instance_path = os.path.join(ROOT_DIR, "data", "instances", "sample_01.json")
    if os.path.exists(instance_path):
        solver = ORToolsEVRPTWSolver(instance_path)
        res = solver.solve(enable_log=True)
        if res:
            print("Summary:", res["summary"])
            for r in res["routes"]:
                print(
                    f"Route {r['vehicle_id']}: "
                    f"{[stop['node_id'] for stop in r['stops']]}"
                )
        else:
            print("No solution found!")
