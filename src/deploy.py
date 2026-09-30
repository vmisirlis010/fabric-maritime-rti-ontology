"""Deploy the Nereus Tankers maritime Real-Time Intelligence demo into a Microsoft Fabric workspace.

Resumable: every step is idempotent. Run all steps:      python src/deploy.py
Run selected steps:                                      python src/deploy.py dashboard ontology
Configuration comes from config.json at the repo root (see config.example.json).
"""
import base64, json, subprocess, sys, time, pathlib, urllib.request, urllib.error, uuid, random

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
TEMPLATES = HERE / "templates"
sys.path.insert(0, str(HERE))
import model as M

CFG_F = ROOT / "config.json"
if not CFG_F.exists():
    sys.exit("config.json not found - copy config.example.json to config.json and fill in capacityId (and optionally subscription).")
CFG = json.loads(CFG_F.read_text())
SUB = CFG.get("subscription") or None
CAPACITY = CFG["capacityId"]
WS_NAME = CFG.get("workspaceName", "Maritime Fleet RTI Demo")
LH, EH, DB = "FleetLH", "FleetEH", "FleetEH"
ES_NAME = "FleetStream"
API = "https://api.fabric.microsoft.com/v1"
STATE_F = ROOT / ".state.json"
state = json.loads(STATE_F.read_text()) if STATE_F.exists() else {}
def save(): STATE_F.write_text(json.dumps(state, indent=2))

_tok = {}
def token(res="https://api.fabric.microsoft.com"):
    # refresh on the token's real expires_on (az may return a cached token that is close to expiry)
    t = _tok.get(res)
    if not t or time.time() > t[1] - 300:
        cmd = ["az", "account", "get-access-token", "--resource", res, "--query", "[accessToken, expires_on]", "-o", "tsv"]
        if SUB: cmd[3:3] = ["--subscription", SUB]
        v, exp = subprocess.check_output(cmd, shell=True, text=True).split()
        _tok[res] = (v, float(exp))
    return _tok[res][0]

def http(method, url, body=None, res="https://api.fabric.microsoft.com", raw=None, headers=None):
    data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
    h = {"Authorization": f"Bearer {token(res)}"}
    if raw is None: h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url if url.startswith("http") else API + url, data=data, method=method, headers=h)
    try:
        with urllib.request.urlopen(req, timeout=180) as r:
            txt = r.read().decode()
            try: return r.status, dict(r.headers), json.loads(txt) if txt else None
            except json.JSONDecodeError: return r.status, dict(r.headers), txt
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read().decode()

def lro(method, url, body=None, wait=900):
    s, h, b = http(method, url, body)
    if s in (200, 201): return b
    if s != 202: raise RuntimeError(f"{method} {url} -> {s} {str(b)[:1500]}")
    loc = h.get("Location"); t0 = time.time()
    while time.time() - t0 < wait:
        time.sleep(int(h.get("Retry-After", 3)))
        _, _, st = http("GET", loc)
        if isinstance(st, dict) and st.get("status") == "Succeeded":
            s3, _, r = http("GET", loc + "/result")
            return r if s3 == 200 else st
        if isinstance(st, dict) and st.get("status") == "Failed":
            raise RuntimeError(f"LRO failed: {json.dumps(st)[:1500]}")
    raise RuntimeError("LRO timeout")

b64 = lambda s: base64.b64encode(s.encode("utf-8")).decode()
def part(path, content): return {"path": path, "payload": b64(content if isinstance(content, str) else json.dumps(content, indent=2)), "payloadType": "InlineBase64"}
def items(): return {(i["type"], i["displayName"]): i["id"] for i in http("GET", f"/workspaces/{WS}/items")[2]["value"]}

def upsert(item_type, name, parts=None, fmt=None, description=""):
    ex = items().get((item_type, name))
    d = {"parts": parts} if parts else None
    if d and fmt: d["format"] = fmt
    if ex:
        if d: lro("POST", f"/workspaces/{WS}/items/{ex}/updateDefinition", {"definition": d})
        print(f"  updated {item_type:16s} {name}"); return ex
    body = {"displayName": name, "type": item_type, "description": description}
    if d: body["definition"] = d
    r = lro("POST", f"/workspaces/{WS}/items", body)
    iid = (r or {}).get("id") or items()[(item_type, name)]
    print(f"  created {item_type:16s} {name}  {iid}"); return iid

def kql_mgmt(csl):
    s, _, b = http("POST", f"{state['kusto_uri']}/v1/rest/mgmt", {"db": DB, "csl": csl}, res="https://kusto.kusto.windows.net")
    if s != 200: raise RuntimeError(f"KQL {csl[:80]} -> {s} {str(b)[:600]}")

def kql_query(csl):
    s, _, b = http("POST", f"{state['kusto_uri']}/v2/rest/query", {"db": DB, "csl": csl}, res="https://kusto.kusto.windows.net")
    if s != 200: raise RuntimeError(f"KQL query -> {s} {str(b)[:600]}")
    t = next(f for f in b if f.get("TableKind") == "PrimaryResult")
    return [dict(zip([c["ColumnName"] for c in t["Columns"]], r)) for r in t["Rows"]]

# ---------------------------------------------------------------- schema
STREAMS = {
    "VesselPositions": [("timestamp", "datetime"), ("stream_type", "string"), ("vessel_id", "string"), ("vessel_name", "string"), ("vessel_type", "string"),
                        ("latitude", "real"), ("longitude", "real"), ("speed_knots", "real"), ("heading_deg", "real"), ("destination", "string"),
                        ("eta_hours", "real"), ("nav_status", "string"), ("cargo_status", "string"), ("voyage_id", "string")],
    "EngineTelemetry": [("timestamp", "datetime"), ("stream_type", "string"), ("vessel_id", "string"), ("vessel_name", "string"), ("engine_id", "string"),
                        ("engine_load_pct", "real"), ("shaft_rpm", "real"), ("fuel_rate_t_day", "real"), ("exhaust_temp_c", "real"),
                        ("lube_oil_pressure_bar", "real"), ("jacket_cw_temp_c", "real"), ("tc_vibration_mm_s", "real"), ("latitude", "real"),
                        ("longitude", "real"), ("fault_type", "string")],
    "CargoTankTelemetry": [("timestamp", "datetime"), ("stream_type", "string"), ("tank_id", "string"), ("vessel_id", "string"), ("tank_name", "string"),
                           ("cargo_temp_c", "real"), ("tank_pressure_mbar", "real"), ("o2_pct", "real"), ("level_pct", "real"), ("fault_type", "string")],
    "WeatherTelemetry": [("timestamp", "datetime"), ("stream_type", "string"), ("area_id", "string"), ("area_name", "string"), ("latitude", "real"),
                         ("longitude", "real"), ("wind_speed_kn", "real"), ("wave_height_m", "real"), ("beaufort", "real"), ("sea_state", "string")],
    "EmissionsStream": [("timestamp", "datetime"), ("stream_type", "string"), ("vessel_id", "string"), ("vessel_name", "string"), ("voyage_id", "string"),
                        ("fuel_type", "string"), ("fuel_consumed_t", "real"), ("co2_t", "real"), ("distance_nm", "real"), ("cii_attained", "real"),
                        ("cii_required", "real"), ("cii_rating", "string"), ("eu_ets_factor", "real"), ("eua_owed_t", "real"), ("eua_cost_eur", "real")],
}
ports_dt = ", ".join(f"'{p[2]}', '{p[4]}', {M.NODES[p[1]][0]}, {M.NODES[p[1]][1]}" for p in M.PORTS)
KQL_FUNCTIONS = {
    "VesselTracking": "VesselPositions | where timestamp > ago(2m) | summarize arg_max(timestamp, *) by vessel_id | extend marker_size = iff(nav_status startswith 'Diverted' or nav_status startswith 'Restricted', 60, 30) | project vessel_id, vessel_name, vessel_type, latitude, longitude, speed_knots, heading_deg, destination, nav_status, cargo_status, eta_hours, marker_size, timestamp",
    "PortsLayer": f"datatable(port_name:string, port_type:string, latitude:real, longitude:real)[{ports_dt}]",
    "WeatherLive": "WeatherTelemetry | where timestamp > ago(1m) | summarize arg_max(timestamp, *) by area_id | project area_name, latitude, longitude, wind_speed_kn, wave_height_m, beaufort, sea_state, timestamp",
    "VesselNames": "VesselPositions | where timestamp > ago(10m) | summarize vessel_name = take_any(vessel_name) by vessel_id",
}

# ---------------------------------------------------------------- lakehouse schemas (spark types)
LH_SCHEMAS = {
    "vessels": [("vessel_id", "string"), ("vessel_name", "string"), ("vessel_type", "string"), ("segment", "string"), ("dwt", "long"), ("built_year", "long"),
                ("flag", "string"), ("class_society", "string"), ("shipyard", "string"), ("technical_superintendent", "string"), ("service_speed_kn", "double"), ("status", "string")],
    "main_engines": [("engine_id", "string"), ("vessel_id", "string"), ("maker", "string"), ("model", "string"), ("mcr_kw", "long"), ("mcr_rpm", "long"),
                     ("fuel_type", "string"), ("running_hours", "long"), ("last_overhaul_date", "string")],
    "ports": [("port_id", "string"), ("port_name", "string"), ("country", "string"), ("port_type", "string"), ("eu_port", "boolean"), ("has_repair_yard", "boolean"),
              ("latitude", "double"), ("longitude", "double")],
    "charterers": [("charterer_id", "string"), ("charterer_name", "string"), ("country", "string"), ("credit_rating", "string")],
    "voyages": [("voyage_id", "string"), ("vessel_id", "string"), ("load_port_id", "string"), ("discharge_port_id", "string"), ("cargo_grade", "string"),
                ("cargo_qty_t", "long"), ("charterer_id", "string"), ("laycan_start", "string"), ("voyage_status", "string"), ("eu_ets_scope", "string"), ("tce_usd_k_day", "double")],
    "cargo_tanks": [("tank_id", "string"), ("vessel_id", "string"), ("tank_name", "string"), ("capacity_m3", "long"), ("coating", "string"), ("heating_coils", "boolean")],
    "maintenance_orders": [("order_id", "string"), ("vessel_id", "string"), ("equipment", "string"), ("order_type", "string"), ("priority", "string"), ("status", "string"),
                           ("superintendent", "string"), ("yard_port_id", "string"), ("created_date", "string"), ("cost_usd", "long")],
    "emissions_ledger": [("record_id", "string"), ("vessel_id", "string"), ("period", "string"), ("distance_nm", "long"), ("fuel_consumed_t", "double"), ("co2_t", "double"),
                         ("cii_attained", "double"), ("cii_required", "double"), ("cii_rating", "string"), ("eu_ets_eua_t", "double"), ("eua_cost_eur", "long")],
}

# ---------------------------------------------------------------- notebooks
def notebook(cells, lakehouse=True):
    dep = {"lakehouse": {"default_lakehouse": state["lh"], "default_lakehouse_name": LH, "default_lakehouse_workspace_id": WS,
                         "known_lakehouses": [{"id": state["lh"]}]}} if lakehouse else {}
    meta = json.dumps({"kernel_info": {"name": "synapse_pyspark"}, "dependencies": dep}, indent=2)
    out = ["# Fabric notebook source\n", "# METADATA ********************\n", "\n".join("# META " + l for l in meta.splitlines()) + "\n"]
    cm = "\n".join("# META " + l for l in json.dumps({"language": "python", "language_group": "synapse_pyspark"}, indent=2).splitlines())
    for kind, src in cells:
        if kind == "md":
            out.append("# MARKDOWN ********************\n")
            out.append("\n".join("# " + l if l else "#" for l in src.strip().splitlines()) + "\n")
        else:
            out.append("# CELL ********************\n")
            out.append(src.strip() + "\n")
            out.append("# METADATA ********************\n")
            out.append(cm + "\n")
    return "\n".join(out)

def spark_schema(cols):
    t = {"string": "StringType()", "long": "LongType()", "double": "DoubleType()", "boolean": "BooleanType()"}
    return "StructType([" + ", ".join(f'StructField("{c}", {t[k]})' for c, k in cols) + "])"

def nb_setup():
    code = ["from pyspark.sql.types import *",
            f'ABFSS = "abfss://{WS}@onelake.dfs.fabric.microsoft.com/{state["lh"]}"', "SCHEMAS = {"]
    for tname, cols in LH_SCHEMAS.items():
        code.append(f'    "{tname}": {spark_schema(cols)},')
    code += ["}", "for t, sch in SCHEMAS.items():",
             "    df = spark.read.option('header', True).schema(sch).csv(f'{ABFSS}/Files/data/{t}.csv')",
             "    df.write.mode('overwrite').option('overwriteSchema', 'true').format('delta').save(f'{ABFSS}/Tables/{t}')",
             "    print(f'ok {t}: {df.count()} rows')"]
    return notebook([("md", "# 00 - Load reference data\nLoads the Nereus Tankers reference CSVs from `Files/data` into Delta tables. Safe to re-run (also resets demo maintenance orders)."),
                     ("code", "\n".join(code))])

def nb_simulator(conn):
    params = f'''EVENTHUB_CONNECTION_STRING = "{conn}"
INTERVAL_SECONDS = 2          # real seconds per tick
TIME_FACTOR = 90              # simulated time acceleration (1 tick = 3 sim-minutes)
DIVERT_TIME_BOOST = 5         # extra acceleration for the diverted vessel so the demo lands in minutes
MAX_CYCLES = 0                # 0 = run forever
PORT_STAY_TICKS = 20          # ticks moored at load/discharge port
CONTROL_EVERY_N = 2           # poll Files/control every N ticks
TANK_EVERY_N = 3
WEATHER_EVERY_N = 5
EMISSIONS_EVERY_N = 15
PRINT_EVERY_N_CYCLES = 15
SCRIPTED_DEGRADATION_VESSEL = "NT-KAL"   # turbocharger bearing wear (anomaly story)
DEGRADATION_CYCLE_S = 720
SCRIPTED_TANK = "NT-NEF-3S"              # inert-gas O2 creeping above 8%
ANOMALY_PROBABILITY = 0.08
WEATHER_DIRECT_INGEST = True             # weather rows go straight to the Eventhouse (streaming ingestion)
KUSTO_URI = "{state['kusto_uri']}"
KUSTO_DB = "{DB}"'''
    clear = '''import notebookutils as nu
CTRL = "Files/control"
try:
    for it in nu.fs.ls(CTRL):
        nu.fs.rm(it.path, recurse=True); print("removed", it.name)
except Exception:
    nu.fs.mkdirs(CTRL)
print("control files cleared")'''
    return notebook([
        ("md", "# Nereus Tankers - Fleet Telemetry Simulator\nStreams AIS positions, main-engine, cargo-tank, weather and emissions telemetry for 8 tankers in the Eastern Mediterranean into the **FleetStream** Eventstream.\nStop the cell to end the simulation. Restarting clears all demo control files (resets the scenario)."),
        ("code", "%pip install azure-eventhub --quiet"),
        ("code", clear),
        ("md", "## Parameters"),
        ("code", params),
        ("md", "## Fleet model (vessels, ports, sea-lane graph)"),
        ("code", "from azure.eventhub import EventHubProducerClient, EventData\n" + (HERE / "model.py").read_text(encoding="utf-8")),
        ("md", "## Run simulator"),
        ("code", (HERE / "sim_core.py").read_text(encoding="utf-8")),
    ])

CTRL_PATH = 'f"abfss://{WS}@onelake.dfs.fabric.microsoft.com/{LHID}/Files/control"'
def nb_trigger():
    code = f'''import notebookutils
WS, LHID = "{WS}", "{state['lh']}"
CTRL = {CTRL_PATH}
notebookutils.fs.mkdirs(CTRL)
notebookutils.fs.put(f"{{CTRL}}/failed_vessels.txt", "{M.DEMO_FAILURE_VESSEL}\\n", True)
print("MAIN ENGINE CRITICAL ALARM injected on NT Ariadne ({M.DEMO_FAILURE_VESSEL}).")
print("Watch the Main Engines page: load collapses, exhaust temperature and turbocharger vibration spike within seconds.")'''
    return notebook([("md", "# Demo Trigger Console\n## Scene - Main engine failure on NT Ariadne\nRun this cell to inject a **main engine critical alarm** (turbocharger surge / high exhaust temperature) on **NT Ariadne**.\nFabric Activator (`ME-Critical-Alarm-Activator`) detects it on the live stream and runs `Divert_Vessel_To_Yard` automatically."),
                     ("code", code)], lakehouse=False)

def nb_divert():
    code = f'''import notebookutils, datetime
WS, LHID = "{WS}", "{state['lh']}"
VESSEL = "{M.DEMO_FAILURE_VESSEL}"
CTRL = {CTRL_PATH}
notebookutils.fs.mkdirs(CTRL)
notebookutils.fs.put(f"{{CTRL}}/divert_{{VESSEL}}.txt", "PERAMA", True)
print(f"DIVERTED: {{VESSEL}} -> Perama Ship Repair Zone")

from pyspark.sql.types import *
schema = {spark_schema(LH_SCHEMAS['maintenance_orders'])}
today = datetime.date.today().isoformat()
order_id = "MO-26-" + datetime.datetime.utcnow().strftime("%H%M%S")
row = [(order_id, VESSEL, "Main Engine", "Corrective", "Critical", "Open", "Kostas Andreou", "PERAMA", today, 185000)]
spark.createDataFrame(row, schema).write.mode("append").format("delta").save(f"abfss://{{WS}}@onelake.dfs.fabric.microsoft.com/{{LHID}}/Tables/maintenance_orders")
print(f"Critical maintenance order {{order_id}} created for {{VESSEL}} at Perama")'''
    return notebook([("md", "# Divert Vessel To Yard\nTriggered by **Fabric Activator** when a vessel reports `ME_CRITICAL_ALARM`.\n1. Re-routes the vessel to the Perama Ship Repair Zone (control file read by the simulator).\n2. Opens a **Critical** corrective maintenance order in the `maintenance_orders` Lakehouse table."),
                     ("code", code)])

# ---------------------------------------------------------------- eventstream / reflex
DEST_IDS = {t: str(uuid.uuid5(uuid.NAMESPACE_URL, "nereus-dest-" + t)) for t in STREAMS}
STREAM_IDS = {t: str(uuid.uuid5(uuid.NAMESPACE_URL, "nereus-stream-" + t)) for t in STREAMS}
ACT_DEST_ID = "2d9f070c-348c-5dfd-8731-0a461ca8fbf4"

ES_SKIP = {"WeatherTelemetry"}  # weather is ingested directly into the Eventhouse

def eventstream_def(reflex_id):
    kqt = {"datetime": "Nvarchar(max)", "string": "Nvarchar(max)", "real": "Float"}
    src = {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "nereus-src")), "name": "fleetapp", "type": "CustomEndpoint", "properties": {}}
    streams = [{"id": str(uuid.uuid5(uuid.NAMESPACE_URL, "nereus-default")), "name": "fleetstream", "type": "DefaultStream", "properties": {}, "inputNodes": [{"name": "fleetapp"}]}]
    ops, dests = [], []
    for t, cols in STREAMS.items():
        if t in ES_SKIP: continue
        lo = t.lower()
        ops.append({"name": f"filter{lo}", "type": "Filter", "inputNodes": [{"name": "fleetstream"}], "properties": {"conditions": [
            {"column": {"expressionType": "ColumnReference", "node": None, "columnName": "stream_type", "columnPathSegments": []},
             "operatorType": "Equals", "value": {"expressionType": "Literal", "dataType": "Nvarchar(max)", "value": t}}]}})
        streams.append({"id": STREAM_IDS[t], "name": f"derived{lo}", "type": "DerivedStream",
                        "properties": {"inputSerialization": {"type": "Json", "properties": {"encoding": "UTF8"}}}, "inputNodes": [{"name": f"filter{lo}"}]})
        dests.append({"id": DEST_IDS[t], "name": f"dest{lo}", "type": "Eventhouse",
                      "properties": {"dataIngestionMode": "ProcessedIngestion", "workspaceId": WS, "itemId": state["kqldb"], "databaseName": DB, "tableName": t,
                                     "inputSerialization": {"type": "Json", "properties": {"encoding": "UTF8"}}},
                      "inputNodes": [{"name": f"derived{lo}"}],
                      "inputSchemas": [{"name": f"derived{lo}", "schema": {"columns": [{"name": c, "type": kqt[k], "fields": None, "items": None} for c, k in cols]}}]})
    dests.append({"id": ACT_DEST_ID, "name": "activator-me-alarms", "type": "Activator",
                  "properties": {"workspaceId": WS, "itemId": reflex_id, "inputSerialization": {"type": "Json", "properties": {"encoding": "UTF8"}}},
                  "inputNodes": [{"name": "derivedenginetelemetry"}]})
    return [part("eventstream.json", {"sources": [src], "destinations": dests, "streams": streams, "operators": ops, "compatibilityLevel": "1.1"}),
            part("eventstreamProperties.json", {"retentionTimeInDays": 1, "eventThroughputLevel": "Low"})]

def reflex_def(es_id, notebook_id):
    t = (TEMPLATES / "reflex_template.json").read_text(encoding="utf-8")
    for a, b in [("AegeanPowerStream", ES_NAME), ("derivedwindturbinetelemetry", "derivedenginetelemetry"), ("turbine_id", "vessel_id"),
                 ("WT-Failures-Rule", "ME-Critical-Alarm-Rule"), ("DEMO_FORCED_FAILURE", "ME_CRITICAL_ALARM"),
                 ("92e06608-2a32-a20b-49e9-9d31182f8a42", notebook_id), ("00000000-0000-0000-0000-000000000000", WS),
                 ("584b725a-6c4c-4a4d-9e45-4d2c875a86ee", es_id)]:
        t = t.replace(a, b)
    return [part("ReflexEntities.json", t)]

# ---------------------------------------------------------------- dashboard
ANOMALY_VO = json.loads((TEMPLATES / "anomalychart_visual_options.json").read_text(encoding="utf-8"))

def dashboard_def():
    ds_id = str(uuid.uuid4())
    pages, tiles, queries = [], [], []
    def page(name):
        pid = str(uuid.uuid4()); pages.append({"name": name, "id": pid}); return pid
    def tile(pid, title, vt, q, x, y, w, h, vo=None):
        qid = str(uuid.uuid4())
        queries.append({"dataSource": {"kind": "inline", "dataSourceId": ds_id}, "text": q, "id": qid, "usedVariables": []})
        tiles.append({"id": str(uuid.uuid4()), "title": title, "queryRef": {"kind": "query", "queryId": qid}, "pageId": pid,
                      "layout": {"x": x, "y": y, "width": w, "height": h}, "visualType": vt, "visualOptions": vo or {}})
    latest_pos = "VesselPositions | where timestamp > ago(2m) | summarize arg_max(timestamp, *) by vessel_id"
    latest_eng = "EngineTelemetry | where timestamp > ago(2m) | summarize arg_max(timestamp, *) by vessel_id"
    latest_em = "EmissionsStream | where timestamp > ago(3m) | summarize arg_max(timestamp, *) by vessel_id"
    mapvo = lambda label, size: {"map__type": "bubble", "map__latitudeColumn": "latitude", "map__longitudeColumn": "longitude", "map__labelColumn": label, "map__sizeColumn": size}

    p = page("Fleet Overview")
    tile(p, "Vessels at Sea", "card", f"{latest_pos} | summarize Vessels = countif(nav_status !startswith 'Moored')", 0, 0, 4, 4)
    tile(p, "Laden Vessels", "card", f"{latest_pos} | summarize Laden = countif(cargo_status == 'Laden')", 4, 0, 4, 4)
    tile(p, "Fleet Fuel Burn (t/day)", "card", f"{latest_eng} | summarize t_day = round(sum(fuel_rate_t_day), 1)", 8, 0, 4, 4)
    tile(p, "Critical Engine Alarms", "card", "EngineTelemetry | where timestamp > ago(2m) | summarize Alarms = dcountif(vessel_id, fault_type == 'ME_CRITICAL_ALARM')", 12, 0, 4, 4)
    tile(p, "EU ETS Exposure - Current Voyages (EUR)", "card", f"{latest_em} | summarize EUR = round(sum(eua_cost_eur), 0)", 16, 0, 4, 4)
    tile(p, "Worst Sea State (Beaufort)", "card", "WeatherTelemetry | where timestamp > ago(1m) | summarize arg_max(timestamp, *) by area_id | summarize Bft = max(beaufort)", 20, 0, 4, 4)
    tile(p, "Eastern Mediterranean - Live Fleet Positions", "map",
         f"{latest_pos} | extend marker_size = iff(nav_status startswith 'Diverted' or nav_status startswith 'Restricted', 60, 25) | project vessel_name, vessel_type, latitude, longitude, speed_knots, destination, nav_status, marker_size",
         0, 4, 14, 13, mapvo("vessel_name", "marker_size"))
    tile(p, "Fleet Status", "table",
         f"{latest_pos} | project Vessel = vessel_name, Type = vessel_type, Status = nav_status, Cargo = cargo_status, Speed_kn = speed_knots, Heading = heading_deg, Destination = destination, ETA_h = eta_hours | order by Vessel asc",
         14, 4, 10, 13)
    tile(p, "Active Alarms - Main Engines & Cargo Tanks", "table", """let names = VesselNames();
let eng = EngineTelemetry | where timestamp > ago(3m) and fault_type != 'NONE'
    | summarize Last_Seen = max(timestamp), Events = count(), Max_TC_Vib = round(max(tc_vibration_mm_s), 2), Max_Exhaust_C = round(max(exhaust_temp_c), 0) by vessel_id, Alarm = fault_type
    | extend System = 'Main Engine', Severity = case(Alarm == 'ME_CRITICAL_ALARM', '1-CRITICAL', Alarm == 'TC_BEARING_WEAR', '2-WARNING', '3-INFO');
let tank = CargoTankTelemetry | where timestamp > ago(3m) and fault_type != 'NONE'
    | summarize Last_Seen = max(timestamp), Events = count(), Max_O2_pct = round(max(o2_pct), 2) by vessel_id, Tank = tank_name, Alarm = fault_type
    | extend System = strcat('Cargo ', Tank), Severity = '2-WARNING';
union eng, tank | lookup names on vessel_id
| project Severity, Vessel = vessel_name, System, Alarm, Events, Max_TC_Vib, Max_Exhaust_C, Max_O2_pct, Last_Seen
| order by Severity asc, Last_Seen desc""", 0, 17, 24, 8)

    p = page("Main Engines")
    tile(p, "KQL Native ML - Turbocharger Vibration Anomalies on NT Kallisto", "anomalychart",
         "EngineTelemetry\n| where timestamp > ago(20m) and vessel_id == 'NT-KAL'\n| make-series vibration = avg(tc_vibration_mm_s) on timestamp step 5s\n| extend (anomalies, score, baseline) = series_decompose_anomalies(vibration, 1.0)",
         0, 0, 24, 9, ANOMALY_VO)
    tile(p, "NT Kallisto - Turbocharger Bearing Wear in Real Time", "line",
         "EngineTelemetry | where timestamp > ago(15m) and vessel_id == 'NT-KAL' | project timestamp, TC_Vibration_mm_s = tc_vibration_mm_s, Alarm_Limit = 7.0 | order by timestamp asc", 0, 9, 12, 9)
    tile(p, "NT Ariadne - Main Engine Live Status", "line",
         "EngineTelemetry | where timestamp > ago(10m) and vessel_id == 'NT-ARI' | project timestamp, Engine_Load_pct = engine_load_pct, Exhaust_Temp_C_div10 = exhaust_temp_c / 10, TC_Vibration_mm_s = tc_vibration_mm_s | order by timestamp asc", 12, 9, 12, 9)
    tile(p, "Main Engine Health - Right Now", "table",
         f"{latest_eng} | project Vessel = vessel_name, Load_pct = engine_load_pct, Shaft_RPM = shaft_rpm, Fuel_t_day = fuel_rate_t_day, Exhaust_C = exhaust_temp_c, LO_Press_bar = lube_oil_pressure_bar, JCW_C = jacket_cw_temp_c, TC_Vib_mm_s = tc_vibration_mm_s, Status = case(fault_type != 'NONE', fault_type, tc_vibration_mm_s > 5, 'WATCH', 'OK') | order by Vessel asc",
         0, 18, 14, 9)
    tile(p, "Fuel Consumption by Vessel (t/day)", "column", f"{latest_eng} | project Vessel = vessel_name, Fuel_t_day = fuel_rate_t_day | order by Fuel_t_day desc", 14, 18, 10, 9)
    tile(p, "Vibration Leaderboard - Last 30 min", "table",
         "EngineTelemetry | where timestamp > ago(30m) and engine_load_pct > 0 | summarize Avg_mm_s = round(avg(tc_vibration_mm_s), 2), P95_mm_s = round(percentile(tc_vibration_mm_s, 95), 2), Max_mm_s = round(max(tc_vibration_mm_s), 2), Spikes_over_6 = countif(tc_vibration_mm_s > 6) by Vessel = vessel_name | order by P95_mm_s desc",
         0, 27, 24, 8)

    p = page("Cargo & Safety")
    tile(p, "Inert Gas O2 by Cargo Tank - Right Now (limit 8%)", "table",
         "CargoTankTelemetry | where timestamp > ago(1m) | summarize arg_max(timestamp, *) by tank_id | lookup VesselNames() on vessel_id | project Vessel = vessel_name, Tank = tank_name, O2_pct = o2_pct, Pressure_mbar = tank_pressure_mbar, Cargo_Temp_C = cargo_temp_c, Level_pct = level_pct, Status = case(o2_pct > 8, 'ALARM O2 > 8%', o2_pct > 6, 'WATCH', 'OK') | order by O2_pct desc",
         0, 0, 12, 14)
    tile(p, "NT Nefeli COT 3S - Inert Gas O2 Trend", "line",
         "CargoTankTelemetry | where timestamp > ago(20m) and tank_id == 'NT-NEF-3S' | project timestamp, O2_pct = o2_pct, SOLAS_Limit = 8.0 | order by timestamp asc", 12, 0, 12, 7)
    tile(p, "Max Cargo Tank Pressure by Vessel (mbar)", "line",
         "CargoTankTelemetry | where timestamp > ago(15m) | lookup VesselNames() on vessel_id | summarize Max_mbar = max(tank_pressure_mbar) by bin(timestamp, 30s), vessel_name | order by timestamp asc", 12, 7, 12, 7)

    p = page("Emissions & Compliance")
    tile(p, "CII & EU ETS - Current Voyage", "table",
         f"{latest_em} | project Vessel = vessel_name, Voyage = voyage_id, Distance_nm = distance_nm, Fuel_t = fuel_consumed_t, CO2_t = co2_t, CII_Attained = cii_attained, CII_Required = cii_required, CII_Rating = cii_rating, EU_ETS_Scope = strcat(tostring(toint(eu_ets_factor * 100)), '%'), EUA_t = eua_owed_t, EUA_Cost_EUR = eua_cost_eur | order by CII_Rating desc",
         0, 0, 24, 9)
    tile(p, "EU ETS Cost by Vessel - Current Voyage (EUR)", "column", f"{latest_em} | project Vessel = vessel_name, EUA_Cost_EUR = eua_cost_eur | order by EUA_Cost_EUR desc", 0, 9, 12, 9)
    tile(p, "CII Attained vs Required", "column", f"{latest_em} | project Vessel = vessel_name, CII_Attained = cii_attained, CII_Required = cii_required", 12, 9, 12, 9)
    tile(p, "Fleet CO2 - Current Voyages (t)", "line",
         "EmissionsStream | where timestamp > ago(30m) | summarize CO2_t = sum(co2_t) by bin(timestamp, 30s) | order by timestamp asc", 0, 18, 24, 8)

    p = page("Weather & Sea State")
    tile(p, "Sea Areas - Wind Speed (kn)", "map", "WeatherLive() | extend size = toint(wind_speed_kn)", 0, 0, 12, 12, mapvo("area_name", "size"))
    tile(p, "Sea State - Right Now", "table", "WeatherLive() | project Area = area_name, Wind_kn = wind_speed_kn, Beaufort = beaufort, Wave_m = wave_height_m, Sea_State = sea_state | order by Beaufort desc", 12, 0, 12, 12)
    tile(p, "Significant Wave Height by Sea Area (m)", "line",
         "WeatherTelemetry | where timestamp > ago(15m) | project timestamp, area_name, wave_height_m | order by timestamp asc", 0, 12, 24, 9)

    return [part("RealTimeDashboard.json", {"schema_version": 74, "autoRefresh": {"enabled": True, "defaultInterval": "10s", "minInterval": "1s"},
                                            "tiles": tiles, "baseQueries": [], "parameters": [],
                                            "dataSources": [{"id": ds_id, "name": DB, "clusterUri": state["kusto_uri"], "database": DB, "kind": "manual-kusto"}],
                                            "pages": pages, "queries": queries})]

# ---------------------------------------------------------------- map
def map_def():
    src = [("Fleet (live AIS)", "VesselTracking()", 5000, "#0B5CAD", ["vessel_name", "nav_status"]),
           ("Ports & Repair Yards", "PortsLayer()", 3600000, "#CA5010", ["port_name"]),
           ("Sea State", "WeatherLive()", 30000, "#1ABC9C", ["area_name", "sea_state"])]
    layer_sources, layer_settings, parts = [], [], []
    for name, q, refresh, color, labels in src:
        sid, lid = str(uuid.uuid4()), str(uuid.uuid4())
        layer_sources.append({"id": sid, "name": name, "type": "kusto", "options": {"cluster": False}, "itemId": state["kqldb"], "refreshIntervalMs": refresh})
        layer_settings.append({"id": lid, "name": name, "sourceId": sid, "latitudeColumnName": "latitude", "longitudeColumnName": "longitude",
                               "options": {"color": color, "type": "vector", "visible": True, "bubbleOptions": {"color": color}, "markerOptions": {"fillColor": color},
                                           "lineOptions": {"strokeColor": color}, "polygonOptions": {"fillColor": color}, "polygonExtrusionOptions": {"fillColor": color},
                                           "dataLabelOptions": {"enabled": True, "placement": "point"}, "dataLabelKeys": labels}})
        parts.append(part(f"queries/layerSource-{sid}.kql", q))
    m = {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/map/definition/2.0.0/schema.json",
         "basemap": {"options": {"renderWorldCopies": False, "style": "road"}, "controls": {"zoom": True, "pitch": True, "compass": True, "scale": True, "traffic": False}},
         "dataSources": [{"itemType": "KqlDatabase", "workspaceId": WS, "itemId": state["kqldb"]}], "iconSources": [],
         "layerSources": layer_sources, "layerSettings": layer_settings}
    return [part("map.json", m)] + parts

# ---------------------------------------------------------------- anomaly detector
def anomaly_def():
    c = json.loads((TEMPLATES / "anomaly_detector_template.json").read_text(encoding="utf-8"))
    u = c["univariateConfigurations"][0]
    u["configurationId"] = str(uuid.uuid4()); u["configurationName"] = "EngineVibrationDetector"; u["analysisRequestId"] = str(uuid.uuid4())
    u["fabricDataSource"].update({"tableName": "EngineTelemetry", "instanceIDColumnName": "vessel_id", "attributeColumnName": "tc_vibration_mm_s",
                                  "workspaceId": WS, "artifactId": state["kqldb"]})
    return [part("Configurations.json", c)]

# ---------------------------------------------------------------- ontology
_rng = random.Random(4242)
def nid(d): return str(_rng.randint(10 ** (d - 1), 10 ** d - 1))
VT = {"string": "String", "long": "BigInt", "double": "Double", "boolean": "Boolean", "real": "Double"}
ENTITIES = [
    # name, table, key, display, timeseries (table, key column, [cols])
    ("Vessel", "vessels", "vessel_id", "vessel_name", ("VesselPositions", "vessel_id", ["latitude", "longitude", "speed_knots", "heading_deg", "destination", "eta_hours", "nav_status", "cargo_status"])),
    ("MainEngine", "main_engines", "engine_id", "model", ("EngineTelemetry", "engine_id", ["engine_load_pct", "shaft_rpm", "fuel_rate_t_day", "exhaust_temp_c", "lube_oil_pressure_bar", "jacket_cw_temp_c", "tc_vibration_mm_s", "fault_type"])),
    ("CargoTank", "cargo_tanks", "tank_id", "tank_name", ("CargoTankTelemetry", "tank_id", ["cargo_temp_c", "tank_pressure_mbar", "o2_pct", "level_pct", "fault_type"])),
    ("Port", "ports", "port_id", "port_name", None),
    ("Voyage", "voyages", "voyage_id", "voyage_id", None),
    ("Charterer", "charterers", "charterer_id", "charterer_name", None),
    ("MaintenanceOrder", "maintenance_orders", "order_id", "order_id", None),
    ("EmissionsRecord", "emissions_ledger", "record_id", "record_id", None),
]
RELS = [  # name, source entity, target entity, table, source key col, fk col
    ("installed_on", "MainEngine", "Vessel", "main_engines", "engine_id", "vessel_id"),
    ("tank_of", "CargoTank", "Vessel", "cargo_tanks", "tank_id", "vessel_id"),
    ("performed_by", "Voyage", "Vessel", "voyages", "voyage_id", "vessel_id"),
    ("loads_at", "Voyage", "Port", "voyages", "voyage_id", "load_port_id"),
    ("discharges_at", "Voyage", "Port", "voyages", "voyage_id", "discharge_port_id"),
    ("chartered_by", "Voyage", "Charterer", "voyages", "voyage_id", "charterer_id"),
    ("order_for", "MaintenanceOrder", "Vessel", "maintenance_orders", "order_id", "vessel_id"),
    ("repaired_at", "MaintenanceOrder", "Port", "maintenance_orders", "order_id", "yard_port_id"),
    ("emissions_of", "EmissionsRecord", "Vessel", "emissions_ledger", "record_id", "vessel_id"),
]

def ontology_def(display_names=True):
    parts, ent = [part("definition.json", {"_syncBump": "nereus-1"})], {}
    ts_types = {t: dict(cols) for t, cols in STREAMS.items()}
    for name, table, key, disp, ts in ENTITIES:
        eid = nid(15)
        props = [{"id": nid(19), "name": c, "redefines": None, "baseTypeNamespaceType": None, "valueType": VT[k]} for c, k in LH_SCHEMAS[table]]
        pid = {p["name"]: p["id"] for p in props}
        tsp = []
        if ts:
            tsp = [{"id": nid(19), "name": c, "redefines": None, "baseTypeNamespaceType": None, "valueType": VT[ts_types[ts[0]][c]]} for c in ts[2]]
        ent[name] = (eid, pid, table, key)
        parts.append(part(f"EntityTypes/{eid}/definition.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/ontology/entityType/1.0.0/schema.json",
            "id": eid, "namespace": "usertypes", "baseEntityTypeId": None, "name": name, "entityIdParts": [pid[key]],
            "displayNamePropertyId": pid[disp] if display_names else None, "namespaceType": "Custom", "visibility": "Visible",
            "properties": props, "timeseriesProperties": tsp, "untypedProperties": []}))
        bid = str(uuid.uuid4())
        parts.append(part(f"EntityTypes/{eid}/DataBindings/{bid}.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/ontology/dataBinding/1.0.0/schema.json", "id": bid,
            "dataBindingConfiguration": {"dataBindingType": "NonTimeSeries",
                                         "propertyBindings": [{"sourceColumnName": c, "targetPropertyId": pid[c]} for c, _ in LH_SCHEMAS[table]],
                                         "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": WS, "itemId": state["lh"], "sourceTableName": table, "sourceSchema": None}}}))
        if ts:
            bid = str(uuid.uuid4())
            tpid = {p["name"]: p["id"] for p in tsp}
            parts.append(part(f"EntityTypes/{eid}/DataBindings/{bid}.json", {
                "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/ontology/dataBinding/1.0.0/schema.json", "id": bid,
                "dataBindingConfiguration": {"dataBindingType": "TimeSeries", "timestampColumnName": "timestamp",
                                             "propertyBindings": [{"sourceColumnName": ts[1], "targetPropertyId": pid[key]}] + [{"sourceColumnName": c, "targetPropertyId": tpid[c]} for c in ts[2]],
                                             "sourceTableProperties": {"sourceType": "KustoTable", "workspaceId": WS, "itemId": state["kqldb"], "clusterUri": state["kusto_uri"],
                                                                       "databaseName": DB, "sourceTableName": ts[0]}}}))
    for rname, s, t, table, skey, fk in RELS:
        rid = nid(19)
        parts.append(part(f"RelationshipTypes/{rid}/definition.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/ontology/relationshipType/1.0.0/schema.json",
            "namespace": "usertypes", "id": rid, "name": rname, "namespaceType": "Custom", "source": {"entityTypeId": ent[s][0]}, "target": {"entityTypeId": ent[t][0]}}))
        cid = str(uuid.uuid4())
        parts.append(part(f"RelationshipTypes/{rid}/Contextualizations/{cid}.json", {
            "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/ontology/contextualization/1.0.0/schema.json", "id": cid,
            "dataBindingTable": {"workspaceId": WS, "itemId": state["lh"], "sourceTableName": table, "sourceSchema": None, "sourceType": "LakehouseTable"},
            "sourceKeyRefBindings": [{"sourceColumnName": skey, "targetPropertyId": ent[s][1][skey]}],
            "targetKeyRefBindings": [{"sourceColumnName": fk, "targetPropertyId": ent[t][1][ent[t][3]]}]}))
    return parts

AGENT_INSTRUCTIONS = """## Grounding rule
Answer factual questions only from the rows of an executed ontology query. Never invent vessel names, voyage ids, order ids, dates or numbers. If a query fails or returns zero rows, say so and suggest the most likely cause (wrong case, wrong vessel id format, period format) - do not substitute a plausible-looking answer.

## Engine hint
Support group by in GQL

## Tone and style
Clear, concise, professional. Sound like a fleet operations / technical superintendent analyst in a Greek tanker company. Lead with the numbers, then one line of interpretation.

## General knowledge
You are the **Nereus Tankers Fleet Operations** data agent. Nereus Tankers S.A. is a (fictional) Athens-based crude and product tanker operator with 8 vessels trading in the Eastern Mediterranean and Adriatic. The current year is **2026**.

## Data source (only one)
**NereusFleetOntology** - a graph (GQL) view with entities `Vessel`, `MainEngine`, `CargoTank`, `Voyage`, `Port`, `Charterer`, `MaintenanceOrder`, `EmissionsRecord` and relationships `installed_on` (MainEngine->Vessel), `tank_of` (CargoTank->Vessel), `performed_by` (Voyage->Vessel), `loads_at` / `discharges_at` (Voyage->Port), `chartered_by` (Voyage->Charterer), `order_for` (MaintenanceOrder->Vessel), `repaired_at` (MaintenanceOrder->Port), `emissions_of` (EmissionsRecord->Vessel).
Static `properties` come from the Lakehouse; `timeseriesProperties` are live telemetry resolved from the Eventhouse (latest value). Do not write raw KQL or SQL - traverse the ontology.

## When asked about
- **Where is / position / speed / destination / ETA / status of a vessel** -> Vessel timeseries properties (latitude, longitude, speed_knots, heading_deg, destination, eta_hours, nav_status, cargo_status).
- **Main engine load, rpm, fuel consumption, exhaust temperature, turbocharger vibration, alarms** -> MainEngine timeseries properties, joined to Vessel via installed_on.
- **Cargo tank O2 / inert gas / pressure / temperature / level** -> CargoTank timeseries properties, joined via tank_of.
- **Charterer, cargo grade, load / discharge port, TCE** -> Voyage + Charterer + Port.
- **Maintenance, repairs, work orders, superintendent** -> MaintenanceOrder (+ Vessel, + Port for the yard).
- **CII, CO2, fuel, EU ETS, EUAs, emissions per month** -> EmissionsRecord. `period` is a STRING "YYYY-MM" (e.g. "2026-03").

## Business terms and synonyms
- "ship" / "tanker" / "vessel" -> Vessel. Vessel names always start with "NT " (e.g. "NT Ariadne"). vessel_id format is "NT-XXX" (e.g. "NT-ARI").
- "ME" / "main engine" -> MainEngine. "TC" -> turbocharger (tc_vibration_mm_s).
- "open work order" / "open MO" -> MaintenanceOrder.status IN ("Open","Scheduled","In Progress").
- "diverted" -> Vessel.nav_status = "Diverted - Engine Repair". "at sea" -> nav_status does not start with "Moored".
- "laden" / "ballast" -> Vessel.cargo_status.
- "super" / "superintendent" -> Vessel.technical_superintendent or MaintenanceOrder.superintendent.

## Enum cheat sheet (exact strings, case-sensitive)
- Vessel.vessel_type: "Suezmax", "Aframax", "LR2", "MR"; segment: "Crude", "Product"; flag: "Greece", "Malta"; class_society: "LR", "DNV", "ABS", "BV"
- Vessel.technical_superintendent: "Kostas Andreou", "Eleni Georgiou", "Maria Papadaki", "Nikos Stavrou"
- MainEngine.maker: "MAN B&W", "WinGD"; fault_type (live): "NONE", "TC_BEARING_WEAR", "TC_VIBRATION_SPIKE", "ME_CRITICAL_ALARM"
- CargoTank.fault_type (live): "NONE", "IG_O2_HIGH" (O2 above the 8% SOLAS limit)
- Port.port_type: "Crude Loading Terminal", "Refinery Terminal", "Product Terminal", "Bunkering Hub", "Canal Transit / Bunkering", "Repair Yard"
- Voyage.voyage_status: "Laden passage", "Completed"; eu_ets_scope: "Intra-EU (100%)", "Extra-EU (50%)", "Non-EU (0%)"
- MaintenanceOrder.priority: "Critical", "High", "Medium", "Low"; status: "Open", "Scheduled", "In Progress", "Completed"; equipment: "Main Engine", "Turbocharger", "Cargo Pump", "Inert Gas System", "Fuel Oil Purifier", "Ballast Water Treatment", "Steering Gear"
- EmissionsRecord.cii_rating: "A", "B", "C", "D", "E"; period: "2026-01" ... "2026-08"

## Fallback behavior
If the information is not in the ontology, say so plainly and name the closest available data.
"""

def agent_def():
    return [part("Files/Config/data_agent.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/dataAgent/2.1.0/schema.json"}),
            part("Files/Config/draft/stage_config.json", {"$schema": "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition/stageConfiguration/1.0.0/schema.json",
                                                          "aiInstructions": AGENT_INSTRUCTIONS})]

# ---------------------------------------------------------------- main
def run_notebook(nb_id, params=None, wait=True, timeout=900):
    body = {"executionData": {"parameters": params}} if params else {}
    s, h, b = http("POST", f"/workspaces/{WS}/items/{nb_id}/jobs/instances?jobType=RunNotebook", body)
    if s != 202: raise RuntimeError(f"run notebook -> {s} {b}")
    loc = h["Location"]
    if not wait: return loc
    t0 = time.time()
    while time.time() - t0 < timeout:
        time.sleep(15)
        st = http("GET", loc)[2]
        if st.get("status") in ("Completed", "Failed", "Cancelled"):
            return st
    raise RuntimeError("notebook timeout")

STEPS = sys.argv[1:] or ["infra", "kql", "data", "notebooks", "stream", "sim", "setup", "dashboard", "map", "anomaly", "ontology", "agent"]

s, _, b = http("GET", "/workspaces")
WS = next((w["id"] for w in b["value"] if w["displayName"] == WS_NAME), None)
if not WS:
    WS = http("POST", "/workspaces", {"displayName": WS_NAME, "capacityId": CAPACITY,
                                      "description": "Nereus Tankers (fictional) - maritime Real-Time Intelligence + Ontology + Data Agent demo"})[2]["id"]
    print("workspace created", WS)
state["ws"] = WS; save()

if "infra" in STEPS:
    state["lh"] = upsert("Lakehouse", LH, description="Fleet reference data (vessels, engines, ports, voyages, charterers, tanks, maintenance, emissions)")
    state["eh"] = upsert("Eventhouse", EH, [part("EventhouseProperties.json", {})])
    ex = items().get(("KQLDatabase", DB))
    if not ex:
        ex = upsert("KQLDatabase", DB, [part("DatabaseProperties.json", {"databaseType": "ReadWrite", "parentEventhouseItemId": state["eh"],
                                                                         "oneLakeCachingPeriod": "P36500D", "oneLakeStandardStoragePeriod": "P36500D"}),
                                        part("DatabaseSchema.kql", "// schema applied via management commands\n")])
    state["kqldb"] = ex
    state["kusto_uri"] = http("GET", f"/workspaces/{WS}/eventhouses/{state['eh']}")[2]["properties"]["queryServiceUri"]
    save(); print("  kusto", state["kusto_uri"])

if "kql" in STEPS:
    for t, cols in STREAMS.items():
        kql_mgmt(f".create-merge table {t} (" + ", ".join(f"{c}:{k}" for c, k in cols) + ")")
        kql_mgmt(f".create-or-alter table {t} ingestion json mapping 'AutoMapping' '" + json.dumps([{"column": c, "path": f"$.{c}"} for c, _ in cols]) + "'")
        kql_mgmt(f".alter table {t} policy streamingingestion enable")
    for fn, body in KQL_FUNCTIONS.items():
        kql_mgmt(f'.create-or-alter function with (folder="Demo", skipvalidation="true") {fn}() {{ {body} }}')
    print("  KQL tables, mappings, policies, functions ok")

if "data" in STEPS:
    for f in sorted((ROOT / "data").glob("*.csv")):
        raw = f.read_bytes()
        base = f"https://onelake.dfs.fabric.microsoft.com/{WS}/{state['lh']}/Files/data/{f.name}"
        st = "https://storage.azure.com"
        for m, u, data, hdr in [("PUT", f"{base}?resource=file", b"", {}),
                                ("PATCH", f"{base}?action=append&position=0", raw, {"Content-Type": "application/octet-stream"}),
                                ("PATCH", f"{base}?action=flush&position={len(raw)}", b"", {})]:
            s, _, b = http(m, u, res=st, raw=data, headers={"x-ms-version": "2021-08-06", **hdr})
            if s not in (200, 201, 202): raise RuntimeError(f"onelake {m} {f.name} -> {s} {b}")
        print(f"  uploaded {f.name}")

if "notebooks" in STEPS:
    state["nb_setup"] = upsert("Notebook", "00_Load_Reference_Data", [part("notebook-content.py", nb_setup())], "fabricGitSource")
    state["nb_trigger"] = upsert("Notebook", "Demo_Trigger_Console", [part("notebook-content.py", nb_trigger())], "fabricGitSource")
    state["nb_divert"] = upsert("Notebook", "Divert_Vessel_To_Yard", [part("notebook-content.py", nb_divert())], "fabricGitSource")
    save()

if "stream" in STEPS:
    placeholder_es = state.get("es", "00000000-0000-0000-0000-000000000001")
    state["reflex"] = upsert("Reflex", "ME-Critical-Alarm-Activator", reflex_def(placeholder_es, state["nb_divert"]))
    state["es"] = upsert("Eventstream", ES_NAME, eventstream_def(state["reflex"]))
    upsert("Reflex", "ME-Critical-Alarm-Activator", reflex_def(state["es"], state["nb_divert"]))
    save()

if "sim" in STEPS:
    conn = None
    for _ in range(40):
        topo = http("GET", f"/workspaces/{WS}/eventstreams/{state['es']}/topology")[2]
        srcs = [x for x in topo.get("sources", []) if x["type"] == "CustomEndpoint"] if isinstance(topo, dict) else []
        if srcs:
            r = http("GET", f"/workspaces/{WS}/eventstreams/{state['es']}/sources/{srcs[0]['id']}/connection")[2]
            if isinstance(r, dict) and "accessKeys" in r:
                conn = r["accessKeys"]["primaryConnectionString"]; break
        time.sleep(10)
    if not conn: raise RuntimeError("eventstream connection string not available")
    state["nb_sim"] = upsert("Notebook", "Fleet_Simulator", [part("notebook-content.py", nb_simulator(conn))], "fabricGitSource")
    save()
    print("  topology:", [(d["name"], d.get("status")) for d in topo.get("destinations", [])])

if "setup" in STEPS:
    st = run_notebook(state["nb_setup"])
    print("  setup notebook:", st.get("status"), st.get("failureReason"))

if "dashboard" in STEPS:
    state["dash"] = upsert("KQLDashboard", "Fleet_Live_Operations", dashboard_def()); save()
if "map" in STEPS:
    try: state["map"] = upsert("Map", "FleetMap", map_def()); save()
    except Exception as e: print("  MAP FAILED", e)
if "anomaly" in STEPS:
    try: state["ad"] = upsert("AnomalyDetector", "AnomalyDetector_MainEngines", anomaly_def()); save()
    except Exception as e: print("  ANOMALY FAILED", e)
if "ontology" in STEPS:
    try:
        state["onto"] = upsert("Ontology", "NereusFleetOntology", ontology_def(True))
    except Exception as e:
        print("  ontology with display names failed, retrying without:", str(e)[:300])
        state["onto"] = upsert("Ontology", "NereusFleetOntology", ontology_def(False))
    save()
if "agent" in STEPS:
    state["agent"] = upsert("DataAgent", "NereusFleetAgent", agent_def()); save()
if "start-spark" in STEPS:
    # Optional: run the simulator inside Fabric Spark. It holds a Spark session for as long as it runs, which can
    # saturate small capacities (F2-F8) - the local runner (demo-control.ps1 start) is recommended instead.
    state["sim_job"] = run_notebook(state["nb_sim"], {"_inlineInstallationEnabled": {"value": "True", "type": "bool"}}, wait=False); save()
    print("  Spark simulator started")
print("done:", json.dumps({k: v for k, v in state.items() if k != 'sim_job'}, indent=1))
print("\nNext: finish the two portal steps in README.md (Data Agent source + Eventhouse Python plugin), then run ./demo-control.ps1 start")
