# MarksVision
An energy monitoring and energy management web application (Django).

## Running

```bash
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000      # web application
python manage.py poll_modbus                  # meter poller + nightly aggregation (separate process)
```

## Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required when `DJANGO_DEBUG=0` |
| `DJANGO_DEBUG` | `1` (default, development) or `0` (production) |
| `DJANGO_ALLOWED_HOSTS` | Comma separated host names / IPs |
| `DJANGO_HTTPS` | `1` when served over HTTPS (secure cookies) |
| `DJANGO_TIME_ZONE` | Plant time zone, default `Asia/Dhaka` |
| `MVC_DB_PATH` | SQLite database path (default `db.sqlite3`) |
| `MVC_MASTER_API_KEY` | Shared secret for the MVC_Master console. **Empty = `/api/*` is closed.** Set the same key on the customer in MVC_Master. |
| `WEATHER_API_KEY` | weatherapi.com key for the dashboard weather widget |
| `MODBUS_DEFAULT_FUNCTION_CODE` | Function code for register maps saved as bare numbers (default `4`) |
| `MVC_ML_ARTIFACTS_DIR` | Where downloaded ML datasets and trained models are kept (default `ml_artifacts/`, not in git) |

## Management commands

| Command | Use |
|---|---|
| `poll_modbus [--interval 15] [--once] [--no-aggregation]` | Continuous polling of meters and motors; aggregates and re-scores device health once per local day |
| `test_meter <id or name> [--store] [--discover]` | Commissioning: read one meter over its protocol and print the values |
| `scan_modbus <ip> [--unit 1] [--start 0 --end 100]` | Find which registers a Modbus TCP device answers (read-only) |
| `aggregate_meter_data [--since YYYY-MM-DD]` | Rebuild aggregates: weekly/monthly from raw readings, 3monthly/6monthly/yearly from the monthly aggregates, then the hierarchy |
| `populate_measurements` | Create standard measurements and units per meter type |
| `generate_demo_data --days 30` | Synthetic readings for demos/testing |
| `seed_demo_data --flush [--password X]` | **Deletes all data** and loads the compact demo plant (2 sites, 14 meters, users, dashboards, alarms, reports, bills; ~11 MB) |
| `fix_reading_timezone --before "YYYY-MM-DD HH:MM"` | One-off repair of readings saved with local time as UTC by the old poller |
| `train_maintenance_models` | Download the public datasets, train the predictive-maintenance models and score every device (same as *Start training* on the Machine Learning page) |
| `score_device_health` | Re-score every meter and motor with the latest trained model |
| `seed_motor_telemetry [--add-fields] [--degrading NAME]` | Demo only: 45 days of motor history with one developing fault |

## Machine learning (predictive maintenance)

Superusers get a **Machine Learning** page (`/ml/`) that trains the models, shows live training progress,
model quality and the health of every meter and motor.

* **Data:** [Microsoft Azure Predictive Maintenance](https://github.com/Azure-Samples/MachineLearningSamples-PredictiveMaintenance)
  (imminent failures), [NASA C-MAPSS](https://www.nasa.gov/intelligent-systems-division/discovery-and-systems-health/pcoe/pcoe-data-set-repository/)
  (gradual degradation) and [UCI AI4I 2020](https://archive.ics.uci.edu/dataset/601/ai4i+2020+predictive+maintenance+dataset)
  (failure type). About 92 MB, downloaded once into `ml_artifacts/datasets/`.
* **Models (XGBoost):** failure risk within 7 days, days until maintenance (used once wear is detected) and likely failure type.
* **Devices:** each meter or motor is mapped automatically to up to four signals - electrical, load, process, stress -
  from its measurement names, and compared with its own 30-day baseline, so every device type is supported.
  A device needs about 10 days of history before it can be scored. Motor values are stored by `poll_modbus`.
* Predictions are indicative until the plant has its own failure and maintenance history to learn from.

## Meter protocols

Each meter has a **protocol**, **connection settings** (`Meters.connection`) and **data points**
(`Meters.registerMapping`: measurement name -> point). *Settings > Hierarchy > Add Meter* changes its
fields to match the chosen protocol; everything is described once in `connections/protocols.py` and read by the
driver in `connections/drivers/`.

| Protocol | Connection | Data point | Python library |
|---|---|---|---|
| Modbus TCP | host, port 502, unit id | `{"fc": 4, "address": 801, "type": "float32", "scale": 1}` | built-in client |
| BACnet/IP | device IP, UDP port 47808, optional remote network + MS/TP MAC | `{"object_type": "analog-input", "instance": 3, "property": "present-value"}` | bacpypes3 |
| KNX | KNXnet/IP interface, tunnelling (UDP/TCP) or routing, port 3671 | `{"group_address": "1/2/3", "dpt": "14.056"}` | xknx |
| DALI / DALI-2 | daliserver gateway, port 55825 | `{"address": 5, "value": "active_power"}` (level, lamp/gear failure, status, DALI-2 part 252 power and energy) | python-dali |
| M-Bus | TCP gateway or serial level converter, primary or secondary address | `{"record": 0, "scale": 0.001}` | pyMeterBus + pyserial |
| MQTT | broker, port 1883/8883, TLS, user name/password, wait, max age | `{"topic": "plant/db1/power", "json_path": "ENERGY.Power"}` | paho-mqtt |
| OPC UA | server host, port 4840, endpoint path, optional user name/password | `{"node": "ns=2;s=Meter1.Voltage"}` | opcua |

Every point also accepts `"scale"`. `python manage.py test_meter <meter> --discover` (or *Test connection*)
lists M-Bus data records and MQTT topics to help build the mapping. MQTT meters are served by a background
subscription in the poller, so devices should publish with the retain flag or more often than *max age*.

## Tests

```bash
python manage.py test
```
