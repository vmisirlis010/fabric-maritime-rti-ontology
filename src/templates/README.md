# Templates

These files are **Fabric-generated item definitions** taken from George Alexiou's
[fabric-energy-rti-ontology](https://github.com/galex87/fabric-energy-rti-ontology) repository and re-used as structural
templates. `src/deploy.py` rewrites them at deploy time (names, stream, rule, workspace and item ids) for the maritime scenario.

| File | Origin (upstream) | Used for |
|---|---|---|
| `reflex_template.json` | `WT-Failures-Activator.Reflex/ReflexEntities.json` | `ME-Critical-Alarm-Activator` – eventstream source, `vessel_id` object, `fault_type` attribute, rule "changes to `ME_CRITICAL_ALARM`", run-notebook action |
| `anomaly_detector_template.json` | `AnomalyDetector_WindTurbine.AnomalyDetector/Configurations.json` | `AnomalyDetector_MainEngines` – re-pointed to `EngineTelemetry.tc_vibration_mm_s` by `vessel_id` |
| `anomalychart_visual_options.json` | `visualOptions` of the anomaly-chart tile in `AegeanPower_Live_Operations.KQLDashboard` | The KQL native-ML anomaly chart on the *Main Engines* dashboard page |

All credit for the original item design goes to George Alexiou.
