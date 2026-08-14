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
            for m in range(self.num_dummies_per_station):
                dummy_id = f"{sid}_d{m}"
                self.nodes.append({
                    "id": dummy_id,
                    "original_id": sid,
                    "type": "CHARGING_STATION",
                    "demand": 0,
                    "tw_open": 0,
                    "tw_close": depot_duration_sec,
                    "service_time": 0,
                    "charging_rate_kw": info["charging_rate_kw"],
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
                self.distance_matrix[i, j] = dist_dict.get(key, float("inf"))
                self.travel_time_matrix[i, j] = time_dict.get(key, float("inf"))

    def solve(self, time_limit_sec: int = 30, enable_log: bool = False):
        manager = pywrapcp.RoutingIndexManager(self.num_nodes, self.num_vehicles, 0)
        routing = pywrapcp.RoutingModel(manager)

        solver = routing.solver()

        _LARGE_INT = 10 ** 8

        def distance_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            val = self.distance_matrix[from_node, to_node]
            if val == float("inf"):
                return _LARGE_INT
            return int(val * 1000)

        transit_distance_index = routing.RegisterTransitCallback(distance_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_distance_index)

        def demand_callback(from_index):
            from_node = manager.IndexToNode(from_index)
            return self.nodes[from_node]["demand"]

        demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
        routing.AddDimension(
            demand_callback_index,
            0,
            self.spec["max_load_kg"],
            True,
            "Capacity",
        )

        def travel_time_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            travel_sec = self.travel_time_matrix[from_node, to_node]
            if travel_sec == float("inf"):
                return _LARGE_INT
            service_sec = self.nodes[from_node]["service_time"]
            return int(travel_sec + service_sec)

        transit_time_index = routing.RegisterTransitCallback(travel_time_callback)

        depot_start_sec = self.depot["tw_open"] * 60
        depot_end_sec = self.depot["tw_close"] * 60
        depot_duration_sec = depot_end_sec - depot_start_sec

        routing.AddDimension(
            transit_time_index,
            depot_duration_sec,
            depot_duration_sec,
            False,
            "Time",
        )
        time_dimension = routing.GetDimensionOrDie("Time")

        for node_idx in range(self.num_nodes):
            index = manager.NodeToIndex(node_idx)
            time_dimension.CumulVar(index).SetRange(
                int(self.nodes[node_idx]["tw_open"]),
                int(self.nodes[node_idx]["tw_close"]),
            )

        battery_kwh = self.spec["battery_kwh"]
        min_battery_kwh = battery_kwh * self.spec["min_battery_safety_percent"]
        battery_units = int(battery_kwh * 1000)
        min_battery_units = int(min_battery_kwh * 1000)

        def soc_callback(from_index, to_index):
            from_node = manager.IndexToNode(from_index)
            to_node = manager.IndexToNode(to_index)
            dist_km = self.distance_matrix[from_node, to_node]
            if dist_km == float("inf"):
                return -_LARGE_INT
            consumed = dist_km * self.spec["consumption_kwh_per_km"]
            return -int(consumed * 1000)

        transit_soc_index = routing.RegisterTransitCallback(soc_callback)
        routing.AddDimension(
            transit_soc_index,
            battery_units,
            battery_units,
            False,
            "SoC",
        )
        soc_dimension = routing.GetDimensionOrDie("SoC")

        for v in range(self.num_vehicles):
            soc_dimension.CumulVar(routing.Start(v)).SetRange(
                battery_units, battery_units
            )
            soc_dimension.CumulVar(routing.End(v)).SetMin(min_battery_units)

        for idx in range(self.num_nodes):
            index = manager.NodeToIndex(idx)
            node = self.nodes[idx]
            if node["type"] != "CHARGING_STATION":
                soc_dimension.SlackVar(index).SetValue(0)
                soc_dimension.CumulVar(index).SetMin(min_battery_units)
            else:
                soc_dimension.SlackVar(index).SetRange(0, battery_units)
                soc_dimension.CumulVar(index).SetMin(min_battery_units)

                solver.Add(
                    soc_dimension.CumulVar(index) + soc_dimension.SlackVar(index)
                    <= battery_units
                )
                routing.AddDisjunction([index], 0)

        fixed_cost = 1_000_000
        for v in range(self.num_vehicles):
            routing.SetFixedCostOfVehicle(fixed_cost, v)

        search_parameters = pywrapcp.DefaultRoutingSearchParameters()
        search_parameters.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        )
        search_parameters.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_parameters.time_limit.seconds = time_limit_sec
        search_parameters.log_search = enable_log

        solution = routing.SolveWithParameters(search_parameters)

        if solution:
            return self.parse_solution(manager, routing, solution)
        return None


    _ROUTING_STATUS = {
        0: "ROUTING_NOT_SOLVED",
        1: "ROUTING_SUCCESS",
        2: "ROUTING_PARTIAL_SUCCESS_LOCAL_OPTIMUM_NOT_REACHED",
        3: "ROUTING_FAIL",
        4: "ROUTING_FAIL_TIMEOUT",
        5: "ROUTING_INVALID",
        6: "ROUTING_OPTIMAL",
    }

    def parse_solution(self, manager, routing, solution):
        time_dimension = routing.GetDimensionOrDie("Time")
        soc_dimension = routing.GetDimensionOrDie("SoC")
        capacity_dimension = routing.GetDimensionOrDie("Capacity")

        routes = []
        total_dist_km = 0.0
        total_charge_time_sec = 0.0
        total_energy_kwh = 0.0
        used_vehicles = 0
        fixed_cost = 1_000_000

        routing_status = self._ROUTING_STATUS.get(routing.status(), "ROUTING_UNKNOWN")

        for vehicle_id in range(self.num_vehicles):
            if not routing.IsVehicleUsed(solution, vehicle_id):
                continue

            used_vehicles += 1
            route_stops = []
            route_dist_km = 0.0
            route_charge_time_sec = 0.0
            route_energy_kwh = 0.0
            route_delivered_kg = 0

            index = routing.Start(vehicle_id)

            while not routing.IsEnd(index):
                node_idx = manager.IndexToNode(index)
                node_data = self.nodes[node_idx]

                time_val = solution.Min(time_dimension.CumulVar(index))

                soc_arrival_kwh = solution.Min(soc_dimension.CumulVar(index)) / 1000.0

                original_id = node_data.get("original_id", node_data["id"])
                delivered_amount = node_data["demand"]
                route_delivered_kg += delivered_amount

                recharged_kwh = 0.0
                charge_sec = 0.0

                if node_data["type"] == "CHARGING_STATION":
                    soc_slack_units = solution.Min(soc_dimension.SlackVar(index))
                    recharged_kwh = soc_slack_units / 1000.0
                    rate_kw = node_data["charging_rate_kw"]
                    charge_sec = (recharged_kwh / rate_kw) * 3600 if recharged_kwh > 0 else 0.0
                    total_charge_time_sec += charge_sec
                    route_charge_time_sec += charge_sec

                actual_service_sec = node_data["service_time"] + charge_sec
                departure_sec = time_val + actual_service_sec
                soc_departure_kwh = min(
                    soc_arrival_kwh + recharged_kwh, self.spec["battery_kwh"]
                )

                stop_info = {
                    "node_id": original_id,
                    "type": node_data["type"],
                    "arrival_time": self.sec_to_hhmmss(time_val),
                    "service_start_time": self.sec_to_hhmmss(time_val),
                    "departure_time": self.sec_to_hhmmss(departure_sec),
                    "battery_arrival_kwh": round(soc_arrival_kwh, 2),
                    "battery_departure_kwh": round(soc_departure_kwh, 2),
                    "remaining_load_kg": int(
                        self.spec["max_load_kg"]
                        - solution.Min(capacity_dimension.CumulVar(index))
                    ),
                    "delivered_amount_kg": delivered_amount,
                    "recharged_amount_kwh": round(recharged_kwh, 2),
                }
                route_stops.append(stop_info)

                next_index = solution.Value(routing.NextVar(index))
                next_node_idx = manager.IndexToNode(next_index)
                dist_km = self.distance_matrix[node_idx, next_node_idx]
                total_dist_km += dist_km
                route_dist_km += dist_km
                leg_energy = dist_km * self.spec["consumption_kwh_per_km"]
                route_energy_kwh += leg_energy
                total_energy_kwh += leg_energy

                index = next_index

            node_idx = manager.IndexToNode(index)
            node_data = self.nodes[node_idx]
            time_val = solution.Min(time_dimension.CumulVar(index))
            soc_final_kwh = solution.Min(soc_dimension.CumulVar(index)) / 1000.0

            route_stops.append({
                "node_id": node_data["id"],
                "type": node_data["type"],
                "arrival_time": self.sec_to_hhmmss(time_val),
                "service_start_time": self.sec_to_hhmmss(time_val),
                "departure_time": self.sec_to_hhmmss(time_val),
                "battery_arrival_kwh": round(soc_final_kwh, 2),
                "battery_departure_kwh": round(soc_final_kwh, 2),
                "remaining_load_kg": 0,
                "delivered_amount_kg": 0,
                "recharged_amount_kwh": 0.0,
            })

            for i in range(1, len(route_stops)):
                p_from = route_stops[i - 1]["node_id"]
                p_to = route_stops[i]["node_id"]
                route_stops[i]["osm_path_from_prev"] = self.matrix_data["paths"].get(
                    (p_from, p_to), []
                )

            routes.append({
                "vehicle_id": f"k{vehicle_id + 1}",
                "route_summary": {
                    "total_distance_km": round(route_dist_km, 2),
                    "total_charging_time_min": round(route_charge_time_sec / 60.0, 2),
                    "total_energy_consumption_kwh": round(route_energy_kwh, 2),
                    "total_load_delivered_kg": route_delivered_kg,
                    "route_cost": float(fixed_cost + route_dist_km * 1000),
                },
                "stops": route_stops,
            })

        summary = {
            "used_vehicles": used_vehicles,
            "total_distance_km": round(total_dist_km, 2),
            "total_charging_time_min": round(total_charge_time_sec / 60.0, 2),
            "total_energy_consumption_kwh": round(total_energy_kwh, 2),
            "total_cost": float(solution.ObjectiveValue()),
            "status": routing_status,
        }

        return {"summary": summary, "routes": routes}

    def sec_to_hhmmss(self, seconds: float) -> str:
        """Convert seconds-since-depot-open to an absolute HH:MM:SS string."""
        start_sec = self.depot["tw_open"] * 60
        total_sec = int(start_sec + seconds)
        h = (total_sec // 3600) % 24
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        return f"{h:02d}:{m:02d}:{s:02d}"

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
