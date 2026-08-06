import os
import json
import sys

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)

def export_solution(solution_data: dict, instance_name: str, duration_sec: float = 0.0):
    output_dir = os.path.join(ROOT_DIR, "data", "output")
    os.makedirs(output_dir, exist_ok=True)

    output_data = {
        "instance_name": instance_name,
        "summary": {
            "used_vehicles": solution_data["summary"]["used_vehicles"],
            "total_distance_km": solution_data["summary"]["total_distance_km"],
            "total_charging_time_min": solution_data["summary"]["total_charging_time_min"],
            "total_energy_consumption_kwh": solution_data["summary"]["total_energy_consumption_kwh"],
            "total_cost": solution_data["summary"].get("total_cost", 0.0),
            "solve_duration_sec": round(duration_sec, 3),
            "status": solution_data["summary"]["status"]
        },
        "routes": []
    }

    for route in solution_data["routes"]:
        route_stops = []
        for stop in route["stops"]:
            stop_info = {
                "node_id": stop["node_id"],
                "type": stop["type"],
                "arrival_time": stop["arrival_time"],
                "service_start_time": stop["service_start_time"],
                "departure_time": stop["departure_time"],
                "battery_arrival_kwh": stop["battery_arrival_kwh"],
                "battery_departure_kwh": stop["battery_departure_kwh"],
                "remaining_load_kg": stop["remaining_load_kg"],
                "delivered_amount_kg": stop.get("delivered_amount_kg", 0),
                "recharged_amount_kwh": stop.get("recharged_amount_kwh", 0.0),
                "osm_path_from_prev": stop.get("osm_path_from_prev", [])
            }
            route_stops.append(stop_info)
        
        output_data["routes"].append({
            "vehicle_id": route["vehicle_id"],
            "route_summary": route.get("route_summary", {}),
            "stops": route_stops
        })

    out_path = os.path.join(output_dir, f"solution_{instance_name}.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output_data, f, indent=2, ensure_ascii=False)
    
    print(f"Exported solution to: {os.path.abspath(out_path)}")
    return out_path
