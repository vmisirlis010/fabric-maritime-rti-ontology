"""Generate seed CSVs for the Nereus Tankers maritime demo lakehouse."""
import csv, random, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).parent))
from model import *

random.seed(7)
OUT = pathlib.Path(__file__).parent.parent / "data"
OUT.mkdir(exist_ok=True)


def write(name, header, rows):
    with open(OUT / f"{name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(header); w.writerows(rows)
    print(f"{name}.csv  {len(rows)} rows")


write("vessels",
      ["vessel_id", "vessel_name", "vessel_type", "segment", "dwt", "built_year", "flag", "class_society", "shipyard",
       "technical_superintendent", "service_speed_kn", "status"],
      [[v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[15], v[10], "In Service"] for v in FLEET])

write("main_engines",
      ["engine_id", "vessel_id", "maker", "model", "mcr_kw", "mcr_rpm", "fuel_type", "running_hours", "last_overhaul_date"],
      [[f"ME-{v[0]}", v[0], v[13][0], v[13][1], v[13][2], v[13][3], "VLSFO",
        (2026 - v[5]) * 6200 + random.randint(0, 3000), f"202{random.randint(4, 6)}-0{random.randint(1, 9)}-{random.randint(10, 28)}"]
       for v in FLEET])

write("ports",
      ["port_id", "port_name", "country", "port_type", "eu_port", "has_repair_yard", "latitude", "longitude"],
      [[p[0], p[2], p[3], p[4], str(p[5]).lower(), str(p[6]).lower(), NODES[p[1]][0], NODES[p[1]][1]] for p in PORTS])

write("charterers", ["charterer_id", "charterer_name", "country", "credit_rating"], [list(c) for c in CHARTERERS])

grades = {"Crude": ["CPC Blend", "Azeri Light", "Es Sider", "Kirkuk", "Iranian Heavy"], "Product": ["ULSD 10ppm", "Jet A-1", "Gasoline 95 RON", "Naphtha"]}
voy = []
for i, v in enumerate(FLEET):
    a, b = v[9]
    qty = int(v[4] * random.uniform(0.9, 0.95))
    voy.append([f"VOY-{v[0][3:]}-2609", v[0], a, b, random.choice(grades[v[3]]), qty, v[14], "2026-09-12", "Laden passage",
                {1.0: "Intra-EU (100%)", 0.5: "Extra-EU (50%)", 0.0: "Non-EU (0%)"}[eu_ets_factor(a, b)], 42.5 + i * 1.75])
    voy.append([f"VOY-{v[0][3:]}-2608", v[0], b, a, "Ballast", 0, v[14], "2026-08-20", "Completed",
                {1.0: "Intra-EU (100%)", 0.5: "Extra-EU (50%)", 0.0: "Non-EU (0%)"}[eu_ets_factor(b, a)], 0.0])
write("voyages", ["voyage_id", "vessel_id", "load_port_id", "discharge_port_id", "cargo_grade", "cargo_qty_t", "charterer_id",
                  "laycan_start", "voyage_status", "eu_ets_scope", "tce_usd_k_day"], voy)

coat = {"Crude": "Epoxy", "Product": "Phenolic Epoxy"}
write("cargo_tanks", ["tank_id", "vessel_id", "tank_name", "capacity_m3", "coating", "heating_coils"],
      [[f"{v[0]}-{t}", v[0], f"COT {t}", round(v[4] * 1.17 / 12 * (1.2 if t.startswith('3') else 1.0)), coat[v[3]], str(v[3] == "Crude").lower()]
       for v in FLEET for t in TANKS])

equip = [("Main Engine", "Corrective"), ("Turbocharger", "Inspection"), ("Cargo Pump", "Preventive"), ("Inert Gas System", "Preventive"),
         ("Fuel Oil Purifier", "Preventive"), ("Ballast Water Treatment", "Inspection"), ("Steering Gear", "Inspection")]
mo = []
n = 1
for v in FLEET:
    for _ in range(random.randint(2, 3)):
        e, t = random.choice(equip)
        st = random.choice(["Completed", "Completed", "Open", "Scheduled", "In Progress"])
        pr = random.choice(["Low", "Medium", "Medium", "High"])
        mo.append([f"MO-26-{n:04d}", v[0], e, t, pr, st, v[15], random.choice(["PIRAEUS", "PERAMA", "AUGUSTA", "LIMASSOL"]),
                   f"2026-0{random.randint(3, 9)}-{random.randint(10, 28)}", random.randint(4, 95) * 1000])
        n += 1
mo.append([f"MO-26-{n:04d}", "NT-KAL", "Turbocharger", "Inspection", "High", "Open", "Eleni Georgiou", "PERAMA", "2026-09-22", 38000])
write("maintenance_orders", ["order_id", "vessel_id", "equipment", "order_type", "priority", "status", "superintendent",
                             "yard_port_id", "created_date", "cost_usd"], mo)

rat = lambda r: "A" if r < 0.82 else "B" if r < 0.93 else "C" if r < 1.07 else "D" if r < 1.19 else "E"
em = []
for v in FLEET:
    for m in range(1, 9):
        dist = random.randint(5200, 7400)
        fuel = round(v[13][2] * 0.62 * 170 * v[12] * (dist / v[10]) / 1e6 * random.uniform(0.95, 1.05), 1)
        co2 = round(fuel * 3.114, 1)
        att = round(co2 * 1e6 / (v[4] * dist), 2)
        f = eu_ets_factor(*v[9])
        em.append([f"EM-{v[0]}-2026{m:02d}", v[0], f"2026-{m:02d}", dist, fuel, co2, att, v[16], rat(att / v[16]),
                   round(co2 * f, 1), round(co2 * f * EU_ETS_EUA_PRICE_EUR)])
write("emissions_ledger", ["record_id", "vessel_id", "period", "distance_nm", "fuel_consumed_t", "co2_t", "cii_attained",
                           "cii_required", "cii_rating", "eu_ets_eua_t", "eua_cost_eur"], em)

for v in FLEET:
    p = shortest_path(*v[9])
    print(f"  route {v[0]}: {' > '.join(p)}  ({path_length_nm(p):.0f} nm)")
