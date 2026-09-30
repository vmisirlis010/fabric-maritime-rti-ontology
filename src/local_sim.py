"""Run the Nereus Tankers fleet simulator locally (no Fabric Spark capacity used).

Same model/physics as the Fabric notebook; sends to the FleetStream Eventstream custom endpoint and reads
the demo control files (failure / divert) from the FleetLH lakehouse via the OneLake DFS API.
"""
import json, pathlib, subprocess, sys, time, types, urllib.request, urllib.error

HERE = pathlib.Path(__file__).parent
ROOT = HERE.parent
STATE = json.loads((ROOT / ".state.json").read_text())
SUB = json.loads((ROOT / "config.json").read_text()).get("subscription") or None
WS, LH = STATE["ws"], STATE["lh"]
ONELAKE = f"https://onelake.dfs.fabric.microsoft.com/{WS}/{LH}"

_tok = {}
def get_token(resource):
    t = _tok.get(resource)
    if not t or time.time() - t[1] > 1800:
        cmd = ["az", "account", "get-access-token", "--resource", resource, "--query", "accessToken", "-o", "tsv"]
        if SUB: cmd[3:3] = ["--subscription", SUB]
        v = subprocess.check_output(cmd, shell=True, text=True).strip()
        _tok[resource] = (v, time.time())
    return _tok[resource][0]

def dfs(method, path, data=None):
    req = urllib.request.Request(path if path.startswith("http") else f"{ONELAKE}/{path}", data=data, method=method,
                                 headers={"Authorization": f"Bearer {get_token('https://storage.azure.com')}", "x-ms-version": "2021-08-06"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read()

def _rel(p):
    return p.split(f"/{LH}/", 1)[1] if f"/{LH}/" in p else p

def fs_exists(p):
    return dfs("HEAD", _rel(p))[0] == 200

def fs_head(p, n=1024):
    s, b = dfs("GET", _rel(p))
    return b[:n].decode("utf-8", "ignore") if s == 200 else ""

def clear_control():
    s, b = dfs("GET", f"https://onelake.dfs.fabric.microsoft.com/{WS}?resource=filesystem&recursive=false&directory={LH}/Files/control")
    if s == 200:
        for p in json.loads(b).get("paths", []):
            dfs("DELETE", p["name"].split("/", 1)[1])
            print("removed", p["name"].rsplit("/", 1)[-1])
    print("control files cleared")

def put_control(name, text):
    data = text.encode()
    dfs("PUT", f"Files/control/{name}?resource=file")
    dfs("PATCH", f"Files/control/{name}?action=append&position=0", data)
    s, b = dfs("PATCH", f"Files/control/{name}?action=flush&position={len(data)}")
    if s not in (200, 201): raise RuntimeError(f"write control {name}: {s} {b[:200]}")

# notebookutils shim so sim_core.py runs unchanged
nu = types.ModuleType("notebookutils")
nu.lakehouse = types.SimpleNamespace(get=lambda name: {"id": LH, "workspaceId": WS})
nu.runtime = types.SimpleNamespace(context={"currentWorkspaceId": WS})
nu.fs = types.SimpleNamespace(exists=fs_exists, head=fs_head)
nu.credentials = types.SimpleNamespace(getToken=get_token)
sys.modules["notebookutils"] = nu

def eventstream_connection():
    api = "https://api.fabric.microsoft.com/v1"
    h = {"Authorization": f"Bearer {get_token('https://api.fabric.microsoft.com')}"}
    topo = json.loads(urllib.request.urlopen(urllib.request.Request(f"{api}/workspaces/{WS}/eventstreams/{STATE['es']}/topology", headers=h)).read())
    src = next(s for s in topo["sources"] if s["type"] == "CustomEndpoint")
    conn = json.loads(urllib.request.urlopen(urllib.request.Request(f"{api}/workspaces/{WS}/eventstreams/{STATE['es']}/sources/{src['id']}/connection", headers=h)).read())
    return conn["accessKeys"]["primaryConnectionString"]

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "trigger":
        put_control("failed_vessels.txt", "NT-ARI\n")
        print("MAIN ENGINE CRITICAL ALARM injected on NT Ariadne (NT-ARI).")
        sys.exit(0)
    from azure.eventhub import EventHubProducerClient, EventData
    clear_control()
    g = {"EventHubProducerClient": EventHubProducerClient, "EventData": EventData, "__name__": "nereus_sim"}
    g.update(dict(
        EVENTHUB_CONNECTION_STRING=eventstream_connection(),
        INTERVAL_SECONDS=2, TIME_FACTOR=90, DIVERT_TIME_BOOST=5, MAX_CYCLES=0, PORT_STAY_TICKS=20,
        CONTROL_EVERY_N=2, TANK_EVERY_N=3, WEATHER_EVERY_N=5, EMISSIONS_EVERY_N=15, PRINT_EVERY_N_CYCLES=30,
        SCRIPTED_DEGRADATION_VESSEL="NT-KAL", DEGRADATION_CYCLE_S=720, SCRIPTED_TANK="NT-NEF-3S", ANOMALY_PROBABILITY=0.08,
        WEATHER_DIRECT_INGEST=True, KUSTO_URI=STATE["kusto_uri"], KUSTO_DB="FleetEH"))
    exec((HERE / "model.py").read_text(encoding="utf-8"), g)
    exec((HERE / "sim_core.py").read_text(encoding="utf-8"), g)
