# Presenter talk track (≈ 60 min)

Goal of the session: not to "sell Fabric", but to leave with **one scoped proof of concept, an owner on each side and a date**.
Everything in the demo should map back to what the customer told you in discovery (how vessel data reaches shore, who uses it, what hurts).

## Pre-flight (15 min before)

1. `./demo-control.ps1 start`, then `./demo-control.ps1 status` – all 8 vessels "Under way".
2. Open tabs: **Fleet_Live_Operations**, **FleetStream**, **ME-Critical-Alarm-Activator**, **NereusFleetOntology_graph**, **NereusFleetAgent**, plus a terminal for `trigger`.
3. Ask the Data Agent one prompt to confirm it answers (see [PROMPTS.md](PROMPTS.md)).
4. Dashboard on **Fleet Overview**.

## 0–7 min · Open with the customer's own words

> "Last time you told us your main pain is the vessel data – many ships reporting every few seconds, aggregated before anyone sees it – and that you want to validate the architecture before any migration discussion. So today is not slides: one working fleet, end to end, and then we decide together what a small proof of concept looks like."

Set expectations: *"The company is fictional – Nereus Tankers, 8 tankers in the Eastern Med. The data is simulated, the pipeline is real Fabric."*
Invite the technical lead to interrupt whenever something doesn't match how their data really flows.

One-line architecture: **Ship → shore → Eventstream → Eventhouse → dashboards, alerts & AI → OneLake** (one copy, Power BI and ERP data alongside).

## 7–12 min · Act 1 – One live picture of the fleet

**Fleet Overview** – map, Fleet Status, KPI cards.
> "Every ship reports position, main engine, cargo tanks and emissions every couple of seconds. No nightly batch, no aggregation step – operations and technical see the same live picture."

**Main Engines → Main Engine Health – Right Now**: load, rpm, exhaust temperature, turbocharger vibration per ship, now.

Bridge question: *"Today, how long from a reading on board to someone ashore seeing it?"*

## 12–22 min · Act 2 – Alarm to action, no human watching

> "Nobody watches a fleet 24/7. Let's break an engine."

`./demo-control.ps1 trigger` → within ~20 s: **Critical Engine Alarms = 1**, *NT Ariadne* in **Active Alarms**, load collapse + exhaust spike on the *Main Engines* page.

Open **ME-Critical-Alarm-Activator**:
> "One rule on the live stream. When a main engine reports a critical alarm it starts an action by itself – here a notebook that diverts the ship to the repair yard and opens a Critical maintenance order. It could equally be a Teams message to the superintendent, an e-mail, or a call into the maintenance system."

Pre-empt the wait: *"The diversion takes ~3 minutes to show – that's the platform starting the job – so meanwhile…"*

## 16–20 min · Act 3 – Emissions & compliance (fills the wait)

**Emissions & Compliance** page.
> "The same stream computes CII and EU ETS exposure per voyage, live – you see a ship drifting towards a D rating, or a voyage getting expensive in EUAs, while you can still act, not a quarter later."

Bridge question: *"Where does your CII / ETS reporting come from today, and how late?"*

Back to **Fleet Overview**: *NT Ariadne* now **Diverted – Engine Repair**, heading to Perama.
> "Alarm → rule → action → ship re-routed → work order raised, no human in the loop."

## 22–28 min · Act 4 – Catch it before it breaks

**Main Engines → KQL Native ML anomaly chart** on *NT Kallisto* + the bearing-wear line.
> "Act 2 was reactive. Here the turbocharger vibration is drifting from its own normal – no threshold configured, the Eventhouse learns each engine's baseline. Feed that into the same Activator and you inspect at the next port instead of paying for a tow."

Optional: **Cargo & Safety → NT Nefeli COT 3S** inert-gas O₂ creeping to the 8 % SOLAS limit.

## 28–35 min · Act 5 – One business model, plain-English questions

**NereusFleetOntology_graph**: Vessel, MainEngine, CargoTank, Voyage, Port, Charterer, MaintenanceOrder, EmissionsRecord – static and live data on the same entity.

**NereusFleetAgent**: 2–3 rehearsed prompts from [PROMPTS.md](PROMPTS.md).
> "A superintendent asks in plain English; the agent answers from the ontology, not from guesswork – on top of your ERP, vessel and telemetry data in one place."

## 35–50 min · Discovery (the most important part)

Stop demoing and ask:

1. **Source** – what leaves the ship today? Which system / vendor, format, frequency, link?
2. **Landing** – where does it land first ashore, and which jobs aggregate it?
3. **Consumers** – technical, operations, commercial, HSEQ? Which reports hurt most?
4. **The one alert** – if one alert happened automatically tomorrow, what would it be?
5. **Constraints** – vendor contracts, security rules, on-prem requirements?
6. **Success** – what makes a proof of concept a clear "yes"?

## 50–60 min · Close on a concrete next step

> "Take **3–5 vessels and one telemetry feed** that already reaches shore; send a **copy** into Fabric alongside today's path so nothing you run changes; build **one live dashboard, one Activator rule and a join to vessel / ERP reference data** in OneLake. **2–4 weeks**, success criteria agreed today."

Agree before hanging up: **owners** on both sides (and a partner if relevant), a **dated** technical deep-dive / workshop, and a **data sample** (even one vessel, one day) plus the list of reports that matter.

## Objection handling

| They say | You say |
|---|---|
| "We're in the middle of an infrastructure clean-up." | "The proof of concept runs alongside – a copy of one feed, nothing migrated." |
| "Connectivity at sea is intermittent." | "Eventstream accepts batches whenever the link is up; event timestamps preserve the on-board time, so history is correct." |
| "On-board systems are vendor-owned." | "We start where the data already lands ashore – no change on board." |
| "What about our Power BI?" | "It stays. Fabric puts the data underneath on OneLake – faster, fresher, not replaced." |
| "Cost?" | "Start on a small or trial capacity; size to real volume afterwards – we model it together." |
| "Our ERP?" | "It can be mirrored or connected into OneLake next to the telemetry – that's what makes vessel / voyage / maintenance questions answerable in one place." |

## After the session

`./demo-control.ps1 stop` (or `reset` if presenting again).
