# Nereus Tankers S.A. - fictional Greek tanker operator used for the maritime RTI demo.
# Shared by the Fabric simulator notebook (injected verbatim) and the local seed-data generator.
import math, heapq

COMPANY = "Nereus Tankers S.A."

# ---- Sea-lane graph (lat, lon). Edges were chosen to stay at sea. ----
NODES = {
    "CEYHAN": (36.80, 35.80), "ISK_W": (36.35, 35.20), "CYP_NE": (36.00, 34.40), "CYP_N": (35.72, 32.90),
    "ANT_S": (35.85, 30.50), "RHO_SE": (35.80, 28.40), "KAR_E": (35.50, 27.40), "KAS_S": (34.95, 26.80),
    "CRE_S": (34.70, 25.50), "GAV_S": (34.55, 24.20), "CRE_W": (35.30, 22.90), "KYT_STR": (35.97, 23.15),
    "MAL_S": (36.30, 23.40), "MYRT": (36.90, 23.60), "HYD_E": (37.30, 23.85), "SAR": (37.70, 23.65),
    "PIR_APP": (37.88, 23.62), "PIRAEUS": (37.94, 23.62), "PERAMA": (37.955, 23.575), "ASPRO": (38.02, 23.58),
    "ION_S": (36.50, 21.00), "ION_N": (38.30, 20.00), "OTRANTO": (39.90, 19.00), "ADR_C": (42.00, 16.80),
    "ADR_N": (44.00, 13.80), "IST_W": (45.20, 13.30), "GTR": (45.60, 13.55), "TRIESTE": (45.64, 13.75),
    "AUG_OFF": (37.10, 15.60), "AUGUSTA": (37.20, 15.25), "ION_SW": (35.00, 18.50), "LIBYA_OFF": (31.40, 18.50),
    "ESSIDER": (30.65, 18.35), "EMED": (33.20, 30.00), "SIDI_OFF": (31.60, 29.60), "SIDIKERIR": (31.13, 29.62),
    "PS_OFF": (31.70, 32.40), "PORTSAID": (31.30, 32.33), "LIM_OFF": (34.50, 33.25), "LIMASSOL": (34.655, 33.02),
}
EDGES = [
    ("CEYHAN", "ISK_W"), ("ISK_W", "CYP_NE"), ("CYP_NE", "CYP_N"), ("CYP_N", "ANT_S"), ("ANT_S", "RHO_SE"),
    ("RHO_SE", "KAR_E"), ("KAR_E", "KAS_S"), ("KAS_S", "CRE_S"), ("CRE_S", "GAV_S"), ("GAV_S", "CRE_W"),
    ("CRE_W", "KYT_STR"), ("KYT_STR", "MAL_S"), ("MAL_S", "MYRT"), ("MYRT", "HYD_E"), ("HYD_E", "SAR"),
    ("SAR", "PIR_APP"), ("PIR_APP", "PIRAEUS"), ("PIR_APP", "PERAMA"), ("PERAMA", "ASPRO"),
    ("CRE_W", "ION_S"), ("KYT_STR", "ION_S"), ("ION_S", "ION_N"), ("ION_N", "OTRANTO"), ("OTRANTO", "ADR_C"),
    ("ADR_C", "ADR_N"), ("ADR_N", "IST_W"), ("IST_W", "GTR"), ("GTR", "TRIESTE"),
    ("ION_S", "AUG_OFF"), ("AUG_OFF", "AUGUSTA"), ("ION_SW", "AUG_OFF"), ("ION_SW", "ION_S"),
    ("ION_SW", "LIBYA_OFF"), ("LIBYA_OFF", "ESSIDER"), ("EMED", "CRE_S"), ("EMED", "KAS_S"),
    ("EMED", "SIDI_OFF"), ("SIDI_OFF", "SIDIKERIR"), ("EMED", "PS_OFF"), ("PS_OFF", "PORTSAID"),
    ("LIM_OFF", "LIMASSOL"), ("LIM_OFF", "EMED"), ("LIM_OFF", "CRE_S"),
]

# ---- Ports / terminals / yards ----
PORTS = [
    # port_id, node, name, country, port_type, eu_port, has_repair_yard
    ("CEYHAN", "CEYHAN", "Ceyhan Marine Terminal", "Turkey", "Crude Loading Terminal", False, False),
    ("SIDIKERIR", "SIDIKERIR", "Sidi Kerir (SUMED)", "Egypt", "Crude Loading Terminal", False, False),
    ("ESSIDER", "ESSIDER", "Es Sider Oil Terminal", "Libya", "Crude Loading Terminal", False, False),
    ("PORTSAID", "PORTSAID", "Port Said (Suez Canal North)", "Egypt", "Canal Transit / Bunkering", False, False),
    ("TRIESTE", "TRIESTE", "Trieste SIOT Terminal", "Italy", "Refinery Terminal", True, False),
    ("AUGUSTA", "AUGUSTA", "Augusta Refinery Terminal", "Italy", "Refinery Terminal", True, False),
    ("ASPRO", "ASPRO", "Aspropyrgos Refinery Terminal", "Greece", "Refinery Terminal", True, False),
    ("PIRAEUS", "PIRAEUS", "Piraeus Anchorage", "Greece", "Bunkering Hub", True, False),
    ("LIMASSOL", "LIMASSOL", "Limassol Vassiliko Terminal", "Cyprus", "Product Terminal", True, False),
    ("PERAMA", "PERAMA", "Perama Ship Repair Zone", "Greece", "Repair Yard", True, True),
]
PORT_BY_ID = {p[0]: p for p in PORTS}

CHARTERERS = [
    ("CH-HEL", "Helios Energy Trading", "Switzerland", "A"),
    ("CH-MIS", "Mistral Petroleum", "France", "A-"),
    ("CH-ADR", "Adriatic Refining SpA", "Italy", "BBB+"),
    ("CH-LEV", "Levant Oil Marketing", "Cyprus", "BBB"),
    ("CH-AEG", "Aegean Refineries S.A.", "Greece", "BBB+"),
]

# vessel_id, name, type, segment, dwt, built, flag, class, yard, route(a,b), service_kn, start_frac, sfoc_factor,
# engine(maker, model, mcr_kw, mcr_rpm), charterer, superintendent, cii_required
FLEET = [
    ("NT-ARI", "NT Ariadne", "Suezmax", "Crude", 158000, 2019, "Greece", "LR", "Hyundai Heavy Industries", ("AUGUSTA", "CEYHAN"), 13.5, 0.35, 1.05, ("MAN B&W", "6G70ME-C9.5", 16350, 72), "CH-ADR", "Kostas Andreou", 3.10),
    ("NT-KAL", "NT Kallisto", "Aframax", "Crude", 115000, 2011, "Malta", "DNV", "Samsung Heavy Industries", ("SIDIKERIR", "TRIESTE"), 12.8, 0.50, 1.38, ("MAN B&W", "6S60MC-C8", 14280, 105), "CH-ADR", "Eleni Georgiou", 4.05),
    ("NT-THA", "NT Thalassa", "Suezmax", "Crude", 157500, 2016, "Greece", "ABS", "Hyundai Samho", ("PORTSAID", "ASPRO"), 13.0, 0.60, 1.12, ("MAN B&W", "6G70ME-C9.2", 15800, 72), "CH-AEG", "Kostas Andreou", 3.10),
    ("NT-NEF", "NT Nefeli", "LR2", "Product", 109900, 2021, "Greece", "LR", "Daehan Shipbuilding", ("ASPRO", "LIMASSOL"), 13.8, 0.30, 1.00, ("WinGD", "6X62-S2.0", 12900, 97), "CH-LEV", "Maria Papadaki", 4.40),
    ("NT-ELE", "NT Electra", "Aframax", "Crude", 113000, 2014, "Malta", "BV", "Sumitomo Heavy Industries", ("ESSIDER", "TRIESTE"), 12.5, 0.25, 1.22, ("MAN B&W", "6G60ME-C9.2", 13400, 97), "CH-MIS", "Eleni Georgiou", 4.05),
    ("NT-AND", "NT Andromeda", "Suezmax", "Crude", 159000, 2020, "Greece", "DNV", "Hyundai Heavy Industries", ("CEYHAN", "TRIESTE"), 13.2, 0.70, 1.02, ("MAN B&W", "6G70ME-C10.5", 16300, 72), "CH-HEL", "Nikos Stavrou", 3.10),
    ("NT-DAN", "NT Danae", "MR", "Product", 50000, 2017, "Greece", "ABS", "Hyundai Mipo", ("PIRAEUS", "AUGUSTA"), 14.0, 0.45, 1.10, ("MAN B&W", "6G50ME-C9.6", 8900, 100), "CH-AEG", "Maria Papadaki", 6.80),
    ("NT-PEN", "NT Penelope", "Aframax", "Crude", 114500, 2009, "Malta", "LR", "Tsuneishi", ("PORTSAID", "AUGUSTA"), 12.9, 0.15, 1.45, ("MAN B&W", "6S60MC-C", 13560, 105), "CH-HEL", "Nikos Stavrou", 4.05),
]
FLEET_BY_ID = {v[0]: v for v in FLEET}
TANKS = ["1P", "1S", "3P", "3S", "5P", "5S"]
EU_ETS_EUA_PRICE_EUR = 72.0
REPAIR_YARD_NODE = "PERAMA"
DEMO_FAILURE_VESSEL = "NT-ARI"

SEA_AREAS = [
    ("IONIAN", "Ionian Sea", 37.5, 19.5), ("S_CRETE", "South of Crete", 34.6, 24.8), ("LEVANT", "Levantine Sea", 34.0, 31.0),
    ("AEGEAN_S", "South Aegean", 36.6, 24.5), ("ADRIATIC", "Adriatic Sea", 42.5, 16.0), ("LIBYAN", "Libyan Sea", 32.5, 20.5),
]


def haversine_nm(a, b):
    lat1, lon1 = map(math.radians, a); lat2, lon2 = map(math.radians, b)
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 3440.065 * math.asin(math.sqrt(d))


def bearing_deg(a, b):
    lat1, lon1 = map(math.radians, a); lat2, lon2 = map(math.radians, b)
    y = math.sin(lon2 - lon1) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(lon2 - lon1)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


_ADJ = {}
for _a, _b in EDGES:
    _d = haversine_nm(NODES[_a], NODES[_b])
    _ADJ.setdefault(_a, []).append((_b, _d)); _ADJ.setdefault(_b, []).append((_a, _d))


def shortest_path(src, dst):
    dist, prev, pq = {src: 0.0}, {}, [(0.0, src)]
    while pq:
        d, u = heapq.heappop(pq)
        if u == dst:
            break
        if d > dist.get(u, 1e18):
            continue
        for v, w in _ADJ.get(u, []):
            nd = d + w
            if nd < dist.get(v, 1e18):
                dist[v], prev[v] = nd, u
                heapq.heappush(pq, (nd, v))
    path, n = [dst], dst
    while n != src:
        n = prev[n]; path.append(n)
    return list(reversed(path))


def path_length_nm(nodes):
    return sum(haversine_nm(NODES[a], NODES[b]) for a, b in zip(nodes, nodes[1:]))


def eu_ets_factor(a_port, b_port):
    ea, eb = PORT_BY_ID[a_port][5], PORT_BY_ID[b_port][5]
    return 1.0 if (ea and eb) else (0.5 if (ea or eb) else 0.0)
