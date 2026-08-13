PLACE_NAME = "Cau Giay District, Hanoi, Vietnam"
NETWORK_TYPE = "drive"

VEHICLE_SPEC = {
    "battery_kwh": 5.0,
    "consumption_kwh_per_km": 0.18,
    "max_load_kg": 500,
    "min_battery_safety_percent": 0.10,
    "depot_charging_rate_kw": 22.0,
    "station_charging_rate_kw": 22.0
}

DEPOT = {
    "id": "D0",
    "lat": 21.0267,
    "lon": 105.7986,
    "name": "302 Cau Giay - Discovery Complex",
    "tw_open": 480,
    "tw_close": 1020
}

VINFAST_STATIONS = {
    "S1": {
        "name": "Tram sac VinFast - Xuan Thuy",
        "lat": 21.0365,
        "lon": 105.7832,
        "charging_rate_kw": 22.0
    },
    "S2": {
        "name": "Tram sac VinFast - Tran Duy Hung",
        "lat": 21.0264,
        "lon": 105.7971,
        "charging_rate_kw": 22.0
    },
    "S3": {
        "name": "Tram sac VinFast - Cau Giay",
        "lat": 21.0402,
        "lon": 105.7958,
        "charging_rate_kw": 22.0  
    },
    "S4": {
        "name": "Tram sac VinFast - Duong Dinh Nghe",
        "lat": 21.0225,
        "lon": 105.7865,
        "charging_rate_kw": 22.0  
    },
    "S5": {
        "name": "Tram sac VinFast - Cong vien Cau Giay",
        "lat": 21.0301,
        "lon": 105.7922,
        "charging_rate_kw": 22.0
    }
}

SYSTEM_PARAMS = {
    "speed_kmh": 40.0,
    "charging_policy": "full_charge",
    "estimated_charge_sec": 900  
}