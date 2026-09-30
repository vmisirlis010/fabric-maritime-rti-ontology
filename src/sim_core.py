# === Nereus Tankers fleet simulator (appended after model.py inside the notebook) ===
import time, random, json
from datetime import datetime, timezone
import notebookutils

_lh = notebookutils.lakehouse.get("FleetLH")
_ws_id = _lh.get("workspaceId") or notebookutils.runtime.context["currentWorkspaceId"]
CTRL = f"abfss://{_ws_id}@onelake.dfs.fabric.microsoft.com/{_lh['id']}/Files/control"


def _read_ctrl(name):
    try:
        p = f"{CTRL}/{name}"
        if notebookutils.fs.exists(p):
            return notebookutils.fs.head(p, 1024).strip()
    except Exception:
        pass
    return ""


def interp(a, b, f):
    return (a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f)


class Ship:
    def __init__(self, v):
        (self.id, self.name, self.vtype, self.segment, self.dwt, _, _, _, _, route, self.service_kn, start_frac,
         self.sfoc, eng, _, _, self.cii_req) = v
        self.engine_id = f"ME-{self.id}"
        self.mcr_kw, self.mcr_rpm = eng[2], eng[3]
        self.ports = list(route)
        self.leg_from, self.leg_to = route
        self.path = shortest_path(self.leg_from, self.leg_to)
        self.laden = True
        self.seg, self.seg_pos = 0, 0.0
        self.moored = 0
        self.failed = False
        self.diverted = False
        self.speed = self.service_kn
        total = path_length_nm(self.path) * start_frac
        while self.seg < len(self.path) - 1:
            L = haversine_nm(NODES[self.path[self.seg]], NODES[self.path[self.seg + 1]])
            if total <= L:
                self.seg_pos = total; break
            total -= L; self.seg += 1
        self.new_voyage(reset=False)
        self.vib_base = random.uniform(1.8, 3.0)

    def new_voyage(self, reset=True):
        self.voy_nm = random.uniform(40, 120) if not reset else 0.0
        self.voy_fuel = self.voy_nm / self.service_kn * self.fuel_rate(0.62) / 24
        self.voyage_id = f"VOY-{self.id[3:]}-{'L' if self.laden else 'B'}{random.randint(100, 999)}"
        self.ets_factor = eu_ets_factor(self.leg_from, self.leg_to) if self.leg_to in PORT_BY_ID and self.leg_from in PORT_BY_ID else 1.0

    def fuel_rate(self, load):
        return self.mcr_kw * load * 170 * self.sfoc * 24 / 1e6

    @property
    def pos(self):
        if self.seg >= len(self.path) - 1:
            return NODES[self.path[-1]]
        a, b = NODES[self.path[self.seg]], NODES[self.path[self.seg + 1]]
        L = haversine_nm(a, b)
        return interp(a, b, 0 if L == 0 else min(self.seg_pos / L, 1.0))

    @property
    def heading(self):
        if self.seg >= len(self.path) - 1:
            return 0.0
        return bearing_deg(self.pos, NODES[self.path[self.seg + 1]])

    def remaining_nm(self):
        if self.seg >= len(self.path) - 1:
            return 0.0
        rem = haversine_nm(self.pos, NODES[self.path[self.seg + 1]])
        return rem + path_length_nm(self.path[self.seg + 1:])

    @property
    def destination(self):
        if self.diverted:
            return "Perama Ship Repair Zone (diverted)"
        return PORT_BY_ID[self.leg_to][2] if self.leg_to in PORT_BY_ID else self.leg_to

    @property
    def nav_status(self):
        if self.moored > 0:
            return "Moored - Loading" if not self.laden else "Moored - Discharging"
        if self.diverted:
            return "Diverted - Engine Repair"
        if self.failed:
            return "Restricted Manoeuvrability"
        return "Under way using engine"

    def divert_to_yard(self):
        nxt = self.path[min(self.seg + 1, len(self.path) - 1)]
        here = self.pos
        route = shortest_path(nxt, REPAIR_YARD_NODE)
        NODES["_DIVERT_START"] = here
        self.path = ["_DIVERT_START"] + route
        self.seg, self.seg_pos = 0, 0.0
        self.leg_to = REPAIR_YARD_NODE
        self.diverted = True

    def step(self, sim_hours):
        if self.moored > 0:
            self.moored -= 1
            self.speed = 0.0
            if self.moored == 0:
                self.leg_from, self.leg_to = self.leg_to, self.leg_from
                self.path = shortest_path(self.leg_from, self.leg_to)
                self.seg, self.seg_pos = 0, 0.0
                self.new_voyage()
            return
        if self.diverted:
            self.speed = 8.0 + random.uniform(-0.3, 0.3)
            sim_hours *= DIVERT_TIME_BOOST
        elif self.failed:
            self.speed = max(3.5, self.speed - 1.5) + random.uniform(-0.2, 0.2)
        else:
            self.speed = self.service_kn + random.uniform(-0.4, 0.4)
        move = self.speed * sim_hours
        self.voy_nm += move
        while move > 0 and self.seg < len(self.path) - 1:
            L = haversine_nm(NODES[self.path[self.seg]], NODES[self.path[self.seg + 1]])
            left = L - self.seg_pos
            if move < left:
                self.seg_pos += move; move = 0
            else:
                move -= left; self.seg += 1; self.seg_pos = 0.0
        if self.seg >= len(self.path) - 1:
            if self.diverted:
                self.speed = 0.0
                return
            self.laden = not self.laden
            self.moored = PORT_STAY_TICKS

    def engine_state(self, now):
        moving = self.moored == 0 and self.speed > 0.5
        if not moving:
            return dict(load=0.0, rpm=0.0, fuel=round(random.uniform(3.5, 5.0), 2), exh=round(random.uniform(55, 70), 1),
                        lo=round(random.uniform(0.2, 0.4), 2), jcw=round(random.uniform(55, 62), 1), vib=round(random.uniform(0.2, 0.5), 2), fault="NONE")
        load = min(0.95, 0.85 * (self.speed / 15.0) ** 3 + 0.08)
        if self.failed and not self.diverted:
            load = 0.18 + random.uniform(-0.02, 0.02)
        elif self.diverted:
            load = 0.30 + random.uniform(-0.02, 0.02)
        rpm = self.mcr_rpm * load ** (1 / 3)
        exh = 245 + 150 * load + random.uniform(-6, 6)
        lo = random.uniform(2.6, 3.0)
        jcw = random.uniform(82, 86)
        vib = self.vib_base + random.uniform(-0.3, 0.3)
        fault = "NONE"
        if self.id == SCRIPTED_DEGRADATION_VESSEL:
            cyc = (now.timestamp() % DEGRADATION_CYCLE_S) / DEGRADATION_CYCLE_S
            extra = 0.0 if cyc > 0.85 else 6.2 * (cyc / 0.85) ** 1.6
            vib += extra
            exh += extra * 6
            if extra > 3.5:
                fault = "TC_BEARING_WEAR"
        if self.id in anomaly_vessels and random.random() < ANOMALY_PROBABILITY:
            vib *= random.uniform(2.0, 3.2)
            fault = "TC_VIBRATION_SPIKE"
        if self.failed:
            exh = 470 + random.uniform(-10, 10)
            vib = 10.5 + random.uniform(-0.8, 0.8)
            lo = 1.4 + random.uniform(-0.1, 0.1)
            fault = "ME_CRITICAL_ALARM"
        return dict(load=round(load * 100, 1), rpm=round(rpm, 1), fuel=round(self.fuel_rate(load), 2), exh=round(exh, 1),
                    lo=round(lo, 2), jcw=round(jcw, 1), vib=round(vib, 2), fault=fault)


fleet = [Ship(v) for v in FLEET]
by_id = {s.id: s for s in fleet}
anomaly_vessels = {"NT-PEN", "NT-ELE"}
tank_state = {f"{s.id}-{t}": dict(o2=random.uniform(2.5, 4.5), p=random.uniform(90, 120)) for s in fleet for t in TANKS}
weather = {a[0]: dict(wind=random.uniform(10, 22)) for a in SEA_AREAS}


def gen_positions(now):
    ev = []
    for s in fleet:
        lat, lon = s.pos
        ev.append(dict(timestamp=now.isoformat(), stream_type="VesselPositions", vessel_id=s.id, vessel_name=s.name,
                       vessel_type=s.vtype, latitude=round(lat, 5), longitude=round(lon, 5), speed_knots=round(s.speed, 1),
                       heading_deg=round(s.heading, 1), destination=s.destination,
                       eta_hours=round(s.remaining_nm() / s.speed, 1) if s.speed > 0.5 else 0.0,
                       nav_status=s.nav_status, cargo_status="Laden" if s.laden else "Ballast", voyage_id=s.voyage_id))
    return ev


def gen_engine(now):
    ev = []
    for s in fleet:
        e = s.engine_state(now)
        s._last_fuel = e["fuel"]
        lat, lon = s.pos
        ev.append(dict(timestamp=now.isoformat(), stream_type="EngineTelemetry", vessel_id=s.id, vessel_name=s.name,
                       engine_id=s.engine_id, engine_load_pct=e["load"], shaft_rpm=e["rpm"], fuel_rate_t_day=e["fuel"],
                       exhaust_temp_c=e["exh"], lube_oil_pressure_bar=e["lo"], jacket_cw_temp_c=e["jcw"],
                       tc_vibration_mm_s=e["vib"], latitude=round(lat, 5), longitude=round(lon, 5), fault_type=e["fault"]))
    return ev


def gen_tanks(now):
    ev = []
    for s in fleet:
        for t in TANKS:
            tid = f"{s.id}-{t}"
            st = tank_state[tid]
            st["o2"] = min(max(st["o2"] + random.uniform(-0.15, 0.15), 1.5), 6.5)
            st["p"] = min(max(st["p"] + random.uniform(-4, 4), 70), 150)
            o2, fault = st["o2"], "NONE"
            if tid == SCRIPTED_TANK:
                cyc = (now.timestamp() % 900) / 900
                o2 = 4.0 + 5.5 * cyc
                if o2 > 8.0:
                    fault = "IG_O2_HIGH"
            heated = s.segment == "Crude"
            ev.append(dict(timestamp=now.isoformat(), stream_type="CargoTankTelemetry", tank_id=tid, vessel_id=s.id,
                           tank_name=f"COT {t}", cargo_temp_c=round((random.uniform(38, 44) if heated else random.uniform(21, 26)) if s.laden else random.uniform(18, 24), 1),
                           tank_pressure_mbar=round(st["p"], 1), o2_pct=round(o2, 2),
                           level_pct=round(random.uniform(95.5, 97.5) if s.laden else random.uniform(0.3, 1.5), 1), fault_type=fault))
    return ev


def gen_weather(now):
    ev = []
    for aid, name, lat, lon in SEA_AREAS:
        w = weather[aid]
        w["wind"] = min(max(w["wind"] + random.uniform(-1.5, 1.5), 4), 42)
        bft = min(12, int((w["wind"] / 1.625) ** (2 / 3)))
        wave = round(0.0065 * w["wind"] ** 1.9 + random.uniform(-0.1, 0.1), 2)
        ev.append(dict(timestamp=now.isoformat(), stream_type="WeatherTelemetry", area_id=aid, area_name=name, latitude=lat,
                       longitude=lon, wind_speed_kn=round(w["wind"], 1), wave_height_m=max(wave, 0.1), beaufort=float(bft),
                       sea_state=["Calm", "Calm", "Smooth", "Slight", "Moderate", "Rough", "Very rough", "High", "Very high"][min(bft, 8)]))
    return ev


def rating(r):
    return "A" if r < 0.82 else "B" if r < 0.93 else "C" if r < 1.07 else "D" if r < 1.19 else "E"


def gen_emissions(now, sim_hours_since_last):
    ev = []
    for s in fleet:
        s.voy_fuel += getattr(s, "_last_fuel", 0) * sim_hours_since_last / 24
        co2 = s.voy_fuel * 3.114
        att = co2 * 1e6 / (s.dwt * max(s.voy_nm, 1))
        ev.append(dict(timestamp=now.isoformat(), stream_type="EmissionsStream", vessel_id=s.id, vessel_name=s.name,
                       voyage_id=s.voyage_id, fuel_type="VLSFO", fuel_consumed_t=round(s.voy_fuel, 2), co2_t=round(co2, 2),
                       distance_nm=round(s.voy_nm, 1), cii_attained=round(att, 3), cii_required=s.cii_req,
                       cii_rating=rating(att / s.cii_req), eu_ets_factor=s.ets_factor, eua_owed_t=round(co2 * s.ets_factor, 2),
                       eua_cost_eur=round(co2 * s.ets_factor * EU_ETS_EUA_PRICE_EUR, 0)))
    return ev


def check_controls():
    failed = {x.strip() for x in _read_ctrl("failed_vessels.txt").splitlines() if x.strip()}
    for s in fleet:
        s.failed = s.id in failed
    for s in fleet:
        if s.failed and not s.diverted and _read_ctrl(f"divert_{s.id}.txt"):
            s.divert_to_yard()
            print(f"[DIVERT] {s.name} -> Perama Ship Repair Zone")


def ingest_direct(table, events):
    import requests
    try:
        tok = notebookutils.credentials.getToken("https://kusto.kusto.windows.net")
        requests.post(f"{KUSTO_URI}/v1/rest/ingest/{KUSTO_DB}/{table}?streamFormat=MultiJSON&mappingName=AutoMapping",
                      data="\n".join(json.dumps(e) for e in events).encode(),
                      headers={"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}, timeout=20)
    except Exception as ex:
        print(f"[WARN] direct ingest {table}: {ex}")


producer = EventHubProducerClient.from_connection_string(EVENTHUB_CONNECTION_STRING)
sim_hours = INTERVAL_SECONDS * TIME_FACTOR / 3600
print(f"Nereus Tankers simulator | {len(fleet)} vessels | tick {INTERVAL_SECONDS}s | time x{TIME_FACTOR}")
tick, sent, failures = 0, 0, 0
try:
    while MAX_CYCLES == 0 or tick < MAX_CYCLES:
        now = datetime.now(timezone.utc)
        if tick % CONTROL_EVERY_N == 0:
            check_controls()
        for s in fleet:
            s.step(sim_hours)
        batch = gen_positions(now) + gen_engine(now)
        if tick % TANK_EVERY_N == 0:
            batch += gen_tanks(now)
        if tick % WEATHER_EVERY_N == 0:
            if WEATHER_DIRECT_INGEST:
                ingest_direct("WeatherTelemetry", gen_weather(now))
            else:
                batch += gen_weather(now)
        if tick % EMISSIONS_EVERY_N == 0:
            batch += gen_emissions(now, sim_hours * EMISSIONS_EVERY_N)
        try:
            eb = producer.create_batch()
            for e in batch:
                try:
                    eb.add(EventData(json.dumps(e)))
                except ValueError:
                    producer.send_batch(eb); eb = producer.create_batch(); eb.add(EventData(json.dumps(e)))
            producer.send_batch(eb)
            sent += len(batch); failures = 0
        except Exception as ex:
            failures += 1
            print(f"[WARN] send failed ({failures}): {ex}")
            if failures % 3 == 0:
                try:
                    producer.close()
                except Exception:
                    pass
                producer = EventHubProducerClient.from_connection_string(EVENTHUB_CONNECTION_STRING)
            if failures >= 20:
                break
            time.sleep(min(failures * 2, 30))
        if PRINT_EVERY_N_CYCLES and tick % PRINT_EVERY_N_CYCLES == 0:
            faults = [f"{e['vessel_id']}:{e['fault_type']}" for e in batch if e.get("stream_type") == "EngineTelemetry" and e["fault_type"] != "NONE"]
            print(f"[{now:%H:%M:%S}] tick={tick} sent={sent} faults={faults}")
        tick += 1
        time.sleep(INTERVAL_SECONDS)
except KeyboardInterrupt:
    print("Stopped by user.")
finally:
    producer.close()
    print(f"Total {tick} ticks, {sent} events.")
