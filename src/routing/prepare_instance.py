import json
import os
import sys
import csv

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.append(ROOT_DIR)
SRC_DIR = os.path.join(ROOT_DIR, "src")
sys.path.extend([ROOT_DIR, SRC_DIR])

import config
from routing.shortest_path import compute_and_save


def load_instance(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_all_coords(instance: dict) -> dict[str, tuple[float, float]]:
    coords: dict[str, tuple[float, float]] = {}
    coords[config.DEPOT["id"]] = (config.DEPOT["lat"], config.DEPOT["lon"])
    for c in instance["customers"]:
        coords[c["id"]] = (c["lat"], c["lon"])
    for sid, info in config.VINFAST_STATIONS.items():
        coords[sid] = (info["lat"], info["lon"])
    return coords


def export_csv(matrix: dict, out_dir: str, instance_name: str):
    names = matrix["node_names"]
    os.makedirs(out_dir, exist_ok=True)

    for metric, unit in [("distance_km", "km"), ("travel_time_s", "s")]:
        data = matrix[metric]
        filename = os.path.join(out_dir, f"matrix_{instance_name}_{metric}.csv")
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["from \\ to"] + names)
            for a in names:
                row = [a] + [
                    round(data.get((a, b), float("inf")), 4) for b in names
                ]
                writer.writerow(row)
        print(f"  Saved: {os.path.abspath(filename)}")


def print_summary(instance: dict, matrix: dict):
    names = matrix["node_names"]
    dist = matrix["distance_km"]
    time = matrix["travel_time_s"]
    finite_d = [v for v in dist.values() if v != float("inf") and v > 0]
    finite_t = [v for v in time.values() if v != float("inf") and v > 0]
    n = len(names)

    print("=" * 55)
    print(f"  Instance  : {instance['instance_name']}")
    print(f"  Depot     : {config.DEPOT['name']}")
    print(f"  Customers : {len(instance['customers'])}")
    print(f"  Stations  : {len(config.VINFAST_STATIONS)}")
    print(f"  Matrix    : {n}x{n} = {n*n} pairs")
    if finite_d:
        print(f"  Dist avg  : {sum(finite_d)/len(finite_d):.2f} km")
        print(f"  Dist max  : {max(finite_d):.2f} km")
    if finite_t:
        print(f"  Time avg  : {sum(finite_t)/len(finite_t):.1f} s")
        print(f"  Time max  : {max(finite_t):.1f} s")
    print("=" * 55)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--instance", default="sample_01", help="Instance name")
    args = parser.parse_args()
    
    instance_file = os.path.join(ROOT_DIR, "data", "instances", f"{args.instance}.json")
    instance = load_instance(instance_file)

    print(f"Instance : {instance['instance_name']}")
    print(f"Depot    : {config.DEPOT['name']} ({config.DEPOT['lat']}, {config.DEPOT['lon']})")
    print(f"Customers: {len(instance['customers'])}")
    print(f"Stations : {len(config.VINFAST_STATIONS)} (from config)")

    all_coords = build_all_coords(instance)
    print(f"\nTotal nodes: {len(all_coords)} "
          f"(1 depot + {len(instance['customers'])} customers + {len(config.VINFAST_STATIONS)} stations)\n")

    matrix = compute_and_save(
        named_coords=all_coords,
        output_name=f"matrix_{instance['instance_name']}",
        save_paths=True,
    )

    print()
    print_summary(instance, matrix)

    csv_dir = os.path.join(ROOT_DIR, "data", "processed")
    print("\nExporting CSV files...")
    export_csv(matrix, out_dir=csv_dir, instance_name=instance["instance_name"])
    print("Done.")
