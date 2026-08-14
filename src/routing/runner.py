import os
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SRC_DIR = os.path.join(ROOT_DIR, "src")
for path in [ROOT_DIR, SRC_DIR]:
    if path not in sys.path:
        sys.path.append(path)

from routing.solver import ORToolsEVRPTWSolver
from routing.exporter import export_solution

def run_pipeline(instance_name: str):
    instance_path = os.path.join(ROOT_DIR, "data", "instances", f"{instance_name}.json")
    print(f"\n--- RUNNING E-VRPTW PIPELINE FOR {instance_name} ---")
    print(f"Loading instance from: {instance_path}")
    
    if not os.path.exists(instance_path):
        print(f"Error: Instance file {instance_path} not found!")
        return

    start_time = time.time()
    try:
        solver = ORToolsEVRPTWSolver(instance_path)
    except FileNotFoundError as e:
        print(f"Error: Required file not found — {e}")
        return
        
    print("Solving with Google OR-Tools (guided local search)...")
    res = solver.solve(time_limit_sec=30)
    duration = time.time() - start_time
    
    if res:
        print(f"Optimal/Feasible solution found in {duration:.2f} seconds!")
        print("Summary:")
        print(f"  - Vehicles used: {res['summary']['used_vehicles']}")
        print(f"  - Total distance: {res['summary']['total_distance_km']} km")
        print(f"  - Total charging time: {res['summary']['total_charging_time_min']} min")
        print(f"  - Total energy consumed: {res['summary']['total_energy_consumption_kwh']} kWh")
        
        export_solution(res, instance_name, duration_sec=duration)
    else:
        print("Error: Solver could not find any feasible solution!")

if __name__ == "__main__":
    instance_name = sys.argv[1] if len(sys.argv) > 1 else "sample_01"
    run_pipeline(instance_name)
