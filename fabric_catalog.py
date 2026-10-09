"""Inventario de Microsoft Fabric: workspaces, items, pipelines, programaciones y ejecuciones.

Autenticacion interactiva: el login lo haces VOS en el navegador (o con device code).
El script nunca ve ni guarda tu usuario/contrasena, solo recibe un token.

Uso:
    uv run fabric_catalog.py                                    # catalogo basico
    uv run fabric_catalog.py -w prod -w stage                   # filtrar workspaces
    uv run fabric_catalog.py --include-schedules                 # + programaciones
    uv run fabric_catalog.py --include-schedules --include-runs  # + ejecuciones
    uv run fabric_catalog.py -w prod --include-schedules --runs-limit 10
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import requests
from azure.identity import (
    AuthenticationRecord,
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    TokenCachePersistenceOptions,
)

API = "https://api.fabric.microsoft.com/v1"
SCOPE = "https://api.fabric.microsoft.com/.default"
CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
AUTH_RECORD = Path(__file__).parent / ".auth_record.json"

DAY_NAMES_ES = {
    "Monday": "lunes", "Tuesday": "martes", "Wednesday": "miércoles",
    "Thursday": "jueves", "Friday": "viernes", "Saturday": "sábado", "Sunday": "domingo",
}
WEEK_INDEX_ES = {
    "First": "primer", "Second": "segundo", "Third": "tercer",
    "Fourth": "cuarto", "Fifth": "quinto",
}


def safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "_"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class FabricApiError(Exception):
    def __init__(self, status: int, message: str, error_code: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.error_code = error_code


def classify_http_error(status: int) -> str:
    if status == 401:
        return "unauthorized"
    if status == 403:
        return "forbidden"
    if status == 404:
        return "not_found"
    if status == 429:
        return "rate_limited"
    if status >= 500:
        return "server_error"
    return "http_error"


def get_credential(device_code: bool, tenant: str | None):
    cache = TokenCachePersistenceOptions(name="fabric_ut")
    record = None
    if AUTH_RECORD.exists():
        record = AuthenticationRecord.deserialize(AUTH_RECORD.read_text())
    kwargs = dict(
        client_id=CLIENT_ID,
        cache_persistence_options=cache,
        authentication_record=record,
    )
    if tenant:
        kwargs["tenant_id"] = tenant
    cred = (DeviceCodeCredential if device_code else InteractiveBrowserCredential)(**kwargs)
    if record is None:
        print(">> Se abrira el login de Microsoft. Ingresa tus credenciales ahi.")
        record = cred.authenticate(scopes=[SCOPE])
        AUTH_RECORD.write_text(record.serialize())
    return cred


class Fabric:
    def __init__(self, cred):
        self.cred = cred
        self.s = requests.Session()

    def _headers(self):
        tok = self.cred.get_token(SCOPE).token
        return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    def request(self, method, url, **kw):
        for attempt in range(6):
            r = self.s.request(method, url, headers=self._headers(), timeout=120, **kw)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", str(2 ** attempt)))
                time.sleep(min(wait, 60))
                continue
            if r.status_code >= 500 and attempt < 4:
                time.sleep(min(2 ** attempt, 30))
                continue
            if r.status_code >= 400:
                try:
                    body = r.json()
                    msg = body.get("message", r.text[:300])
                    code = body.get("errorCode", "")
                except Exception:
                    msg, code = r.text[:300], ""
                raise FabricApiError(r.status_code, msg, code)
            return r
        return r

    def paged(self, path, key="value", limit=None):
        url = f"{API}{path}"
        out = []
        while url:
            r = self.request("GET", url)
            body = r.json()
            out += body.get(key, [])
            if limit and len(out) >= limit:
                out = out[:limit]
                break
            next_uri = body.get("continuationUri")
            token = body.get("continuationToken")
            if next_uri:
                url = next_uri
            elif token:
                sep = "&" if "?" in url else "?"
                url = f"{url}{sep}continuationToken={requests.utils.quote(token)}"
            else:
                url = None
        return out

    def list_pipeline_schedules(self, ws_id: str, pipeline_id: str) -> list[dict]:
        return self.paged(f"/workspaces/{ws_id}/dataPipelines/{pipeline_id}/jobs/execute/schedules")

    def list_pipeline_runs(self, ws_id: str, pipeline_id: str, limit: int | None = None) -> list[dict]:
        return self.paged(
            f"/workspaces/{ws_id}/dataPipelines/{pipeline_id}/jobs/execute/instances",
            limit=limit,
        )

    def get_definition(self, ws_id, item_id, fmt=None):
        q = f"?format={fmt}" if fmt else ""
        r = self.request("POST", f"{API}/workspaces/{ws_id}/items/{item_id}/getDefinition{q}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 202:
            loc = r.headers["Location"]
            while True:
                time.sleep(int(r.headers.get("Retry-After", "3")))
                r = self.request("GET", loc)
                st = r.json().get("status") if r.content else None
                if st == "Succeeded":
                    return self.request("GET", loc.rstrip("/") + "/result").json()
                if st in ("Failed", "Cancelled"):
                    raise RuntimeError(json.dumps(r.json())[:300])
        raise RuntimeError(f"HTTP {r.status_code}: {r.text[:300]}")


def describe_schedule(cfg: dict) -> str:
    stype = cfg.get("type", "")
    times = cfg.get("times", [])
    times_str = ", ".join(times) if times else "?"
    tz = cfg.get("localTimeZoneId", "UTC")

    if stype == "Daily":
        return f"Todos los días a las {times_str} ({tz})"

    if stype == "Weekly":
        days = cfg.get("weekdays", [])
        day_names = [DAY_NAMES_ES.get(d, d) for d in days]
        if len(day_names) == 2 and set(day_names) == {"sábado", "domingo"}:
            days_desc = "fines de semana"
        elif day_names == ["lunes", "martes", "miércoles", "jueves", "viernes"]:
            days_desc = "de lunes a viernes"
        elif day_names == ["lunes", "miércoles"]:
            days_desc = "lunes y miércoles"
        else:
            days_desc = " y ".join(day_names) if day_names else "?"
        return f"{days_desc.capitalize()} a las {times_str} ({tz})"

    if stype == "Monthly":
        occ = cfg.get("occurrence", {})
        recurrence = cfg.get("recurrence", 1)
        occ_type = occ.get("occurrenceType", "")
        if occ_type == "DayOfMonth":
            dom = occ.get("dayOfMonth", "?")
            base = f"El día {dom} de cada mes"
        elif occ_type == "OrdinalWeekday":
            wi = WEEK_INDEX_ES.get(occ.get("weekIndex", ""), occ.get("weekIndex", ""))
            wd = DAY_NAMES_ES.get(occ.get("weekday", ""), occ.get("weekday", ""))
            base = f"El {wi} {wd} de cada mes"
        else:
            base = "Mensual (ocurrencia no reconocida)"
        if recurrence > 1:
            base += f" (cada {recurrence} meses)"
        return f"{base} a las {times_str} ({tz})"

    if stype == "Cron":
        interval = cfg.get("interval", "?")
        return f"Intervalo de {interval} minutos ({tz})"

    return "Configuración no interpretada"


def parse_schedule_status(schedule: dict, now_utc: datetime | None = None) -> str:
    now = now_utc or datetime.now(timezone.utc)
    enabled = schedule.get("enabled")
    cfg = schedule.get("configuration", {})
    end_str = cfg.get("endDateTime")

    if enabled is False:
        return "deshabilitada"

    if end_str:
        try:
            end_dt = datetime.fromisoformat(end_str.replace("Z", "+00:00"))
            if end_dt.tzinfo is None:
                end_dt = end_dt.replace(tzinfo=timezone.utc)
            if end_dt < now:
                return "vencida"
        except (ValueError, AttributeError):
            pass

    if enabled is True:
        return "habilitada"

    return "desconocida"


def convert_time_to_tz(time_str: str, tz_id: str, target_tz: str) -> dict:
    result = {
        "originalTime": time_str,
        "originalTzId": tz_id,
        "convertedTime": "",
        "convertedTz": target_tz,
        "conversionOk": False,
    }
    try:
        tz = ZoneInfo(target_tz)
        dt = datetime.strptime(time_str, "%H:%M").replace(tzinfo=tz)
        result["convertedTime"] = dt.strftime("%H:%M")
        result["conversionOk"] = True
    except (ZoneInfoNotFoundError, ValueError):
        pass
    return result


def save_definition(defn: dict, dest: Path) -> int:
    n = 0
    for part in defn.get("definition", {}).get("parts", []):
        target = dest / part["path"]
        target.parent.mkdir(parents=True, exist_ok=True)
        data = part["payload"]
        if part.get("payloadType") == "InlineBase64":
            target.write_bytes(base64.b64decode(data))
        else:
            target.write_text(str(data), encoding="utf-8")
        n += 1
    return n


def write_csv(path: Path, rows: list[dict]):
    if not rows:
        return
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        wr.writeheader()
        wr.writerows(rows)


def write_json(path: Path, data):
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), "utf-8")


def main():
    ap = argparse.ArgumentParser(description="Catalogo de Microsoft Fabric")
    ap.add_argument("-w", "--workspace", action="append",
                    help="Filtro por nombre (substring, case-insensitive). Repetible.")
    ap.add_argument("-o", "--out", default="output", help="Carpeta de salida")
    ap.add_argument("--export-definitions", action="store_true",
                    help="Baja la definicion de cada item")
    ap.add_argument("--device-code", action="store_true",
                    help="Login por device code (si no hay navegador)")
    ap.add_argument("--tenant", help="Tenant ID (opcional)")
    ap.add_argument("--reset-login", action="store_true", help="Borra la sesion guardada")
    ap.add_argument("--include-schedules", action="store_true",
                    help="Consulta las programaciones de los pipelines")
    ap.add_argument("--include-runs", action="store_true",
                    help="Consulta el historial de ejecuciones de los pipelines")
    ap.add_argument("--runs-limit", type=int, default=20,
                    help="Maximo de ejecuciones por pipeline (default: 20)")
    ap.add_argument("--item-type", help="Filtrar por tipo de item (ej: DataPipeline)")
    ap.add_argument("--schedule-status", choices=["enabled", "disabled", "all"],
                    default="all", help="Filtrar reporte de programaciones por estado")
    ap.add_argument("--timezone", default=None,
                    help="Zona horaria IANA para presentacion (ej: America/Bogota)")
    ap.add_argument("--output-format", choices=["csv", "json", "both"], default="both",
                    help="Formato de exportacion (default: both)")
    a = ap.parse_args()

    if a.reset_login and AUTH_RECORD.exists():
        AUTH_RECORD.unlink()

    if a.include_runs and not a.include_schedules:
        a.include_schedules = True

    target_tz = a.timezone or "America/Bogota"
    try:
        ZoneInfo(target_tz)
    except ZoneInfoNotFoundError:
        print(f"Aviso: zona horaria '{target_tz}' no valida, se omitira la conversion.")
        target_tz = None

    fab = Fabric(get_credential(a.device_code, a.tenant))
    out = Path(a.out) / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    workspaces = fab.paged("/workspaces")
    if a.workspace:
        flt = [f.lower() for f in a.workspace]
        workspaces = [w for w in workspaces if any(f in w["displayName"].lower() for f in flt)]
    print(f"Workspaces a procesar: {len(workspaces)}")

    catalog, rows, errors = [], [], []
    pipelines, schedules_rows, runs_rows = [], [], []
    schedules_raw, summary = [], {}
    collected_at = utc_now_iso()

    for w in workspaces:
        print(f"\n== {w['displayName']} ({w['id']})")
        try:
            items = fab.paged(f"/workspaces/{w['id']}/items")
        except FabricApiError as e:
            errors.append({
                "workspace": w["displayName"], "workspaceId": w["id"],
                "stage": "list_items", "error": str(e),
                "category": classify_http_error(e.status), "errorCode": e.error_code,
            })
            print(f"   ! no se pudieron listar items: {e}")
            continue
        except Exception as e:
            errors.append({
                "workspace": w["displayName"], "workspaceId": w["id"],
                "stage": "list_items", "error": str(e), "category": "unknown", "errorCode": "",
            })
            print(f"   ! error inesperado: {e}")
            continue

        if a.item_type:
            items = [it for it in items if it["type"] == a.item_type]

        catalog.append({"workspace": w, "items": items})
        for it in items:
            rows.append({
                "workspace": w["displayName"], "workspaceId": w["id"],
                "capacityId": w.get("capacityId", ""),
                "itemType": it["type"], "itemName": it["displayName"],
                "itemId": it["id"], "description": it.get("description", ""),
            })

        types = {}
        for it in items:
            types[it["type"]] = types.get(it["type"], 0) + 1
        print("   ", types or "(vacio)")

        pipeline_items = [it for it in items if it["type"] == "DataPipeline"]
        for p in pipeline_items:
            pipeline_rec = {
                "workspaceName": w["displayName"], "workspaceId": w["id"],
                "pipelineName": p["displayName"], "pipelineId": p["id"],
                "description": p.get("description", ""),
                "scheduleCount": 0, "scheduleStatus": "no_consultada",
            }

            if a.include_schedules:
                try:
                    sched_list = fab.list_pipeline_schedules(w["id"], p["id"])
                    pipeline_rec["scheduleCount"] = len(sched_list)
                    pipeline_rec["scheduleStatus"] = "sin_programaciones" if not sched_list else "con_programaciones"

                    for sched in sched_list:
                        cfg = sched.get("configuration", {})
                        status = parse_schedule_status(schedule=sched)
                        desc = describe_schedule(cfg)
                        owner = sched.get("owner", {})

                        conv = {"convertedTime": "", "conversionOk": False}
                        if target_tz and cfg.get("times"):
                            t = cfg["times"][0]
                            conv = convert_time_to_tz(t, cfg.get("localTimeZoneId", ""), target_tz)

                        row = {
                            "workspaceName": w["displayName"], "workspaceId": w["id"],
                            "pipelineName": p["displayName"], "pipelineId": p["id"],
                            "scheduleId": sched.get("id", ""),
                            "scheduleEnabled": sched.get("enabled", ""),
                            "scheduleStatus": status,
                            "scheduleType": cfg.get("type", ""),
                            "scheduleDescription": desc,
                            "startDateTime": cfg.get("startDateTime", ""),
                            "endDateTime": cfg.get("endDateTime", ""),
                            "localTimeZoneId": cfg.get("localTimeZoneId", ""),
                            "convertedTime": conv.get("convertedTime", ""),
                            "convertedTz": conv.get("convertedTz", ""),
                            "conversionOk": conv.get("conversionOk", ""),
                            "ownerId": owner.get("id", ""),
                            "ownerType": owner.get("type", ""),
                            "createdDateTime": sched.get("createdDateTime", ""),
                            "configurationJson": json.dumps(cfg, ensure_ascii=False),
                            "collectionStatus": "ok",
                            "collectedAtUtc": collected_at,
                        }
                        schedules_rows.append(row)

                        if a.schedule_status == "enabled" and not sched.get("enabled"):
                            continue
                        if a.schedule_status == "disabled" and sched.get("enabled"):
                            continue

                        schedules_raw.append({
                            "workspaceName": w["displayName"], "workspaceId": w["id"],
                            "pipelineName": p["displayName"], "pipelineId": p["id"],
                            "scheduleId": sched.get("id", ""),
                            "enabled": sched.get("enabled"),
                            "parsedStatus": status,
                            "description": desc,
                            "configuration": cfg,
                            "owner": owner,
                            "createdDateTime": sched.get("createdDateTime"),
                        })

                except FabricApiError as e:
                    pipeline_rec["scheduleStatus"] = f"error_{classify_http_error(e.status)}"
                    errors.append({
                        "workspace": w["displayName"], "workspaceId": w["id"],
                        "pipeline": p["displayName"], "pipelineId": p["id"],
                        "stage": "list_schedules", "error": str(e),
                        "category": classify_http_error(e.status), "errorCode": e.error_code,
                    })
                    print(f"   ! schedules/{p['displayName']}: {e}")

            pipelines.append(pipeline_rec)

            if a.include_runs:
                try:
                    runs = fab.list_pipeline_runs(w["id"], p["id"], limit=a.runs_limit)
                    for run in runs:
                        start = run.get("startTimeUtc", "")
                        end = run.get("endTimeUtc", "")
                        duration = ""
                        if start and end:
                            try:
                                s_dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
                                e_dt = datetime.fromisoformat(end.replace("Z", "+00:00"))
                                dur = e_dt - s_dt
                                duration = str(dur)
                            except (ValueError, AttributeError):
                                pass

                        failure = run.get("failureReason")
                        runs_rows.append({
                            "workspaceName": w["displayName"], "workspaceId": w["id"],
                            "pipelineName": p["displayName"], "pipelineId": p["id"],
                            "runId": run.get("id", ""),
                            "invokeType": run.get("invokeType", ""),
                            "status": run.get("status", ""),
                            "startTimeUtc": start,
                            "endTimeUtc": end,
                            "duration": duration,
                            "failureReason": json.dumps(failure, ensure_ascii=False) if failure else "",
                            "rootActivityId": run.get("rootActivityId", ""),
                            "jobType": run.get("jobType", ""),
                            "collectedAtUtc": collected_at,
                        })
                except FabricApiError as e:
                    errors.append({
                        "workspace": w["displayName"], "workspaceId": w["id"],
                        "pipeline": p["displayName"], "pipelineId": p["id"],
                        "stage": "list_runs", "error": str(e),
                        "category": classify_http_error(e.status), "errorCode": e.error_code,
                    })
                    print(f"   ! runs/{p['displayName']}: {e}")

        if a.export_definitions:
            for it in items:
                dest = out / "definitions" / safe(w["displayName"]) / safe(it["type"]) / safe(it["displayName"])
                try:
                    n = save_definition(fab.get_definition(w["id"], it["id"]), dest)
                    print(f"    ok  {it['type']}/{it['displayName']} ({n} archivos)")
                except FabricApiError as e:
                    errors.append({
                        "workspace": w["displayName"], "item": it["displayName"],
                        "type": it["type"], "stage": "definition", "error": str(e),
                        "category": classify_http_error(e.status), "errorCode": e.error_code,
                    })
                    print(f"    --  {it['type']}/{it['displayName']}: sin definicion ({str(e)[:80]})")
                except Exception as e:
                    errors.append({
                        "workspace": w["displayName"], "item": it["displayName"],
                        "type": it["type"], "stage": "definition", "error": str(e),
                        "category": "unknown", "errorCode": "",
                    })
                    print(f"    --  {it['type']}/{it['displayName']}: error ({str(e)[:80]})")

    summary = {
        "collectedAtUtc": collected_at,
        "workspacesProcessed": len(workspaces),
        "totalItems": len(rows),
        "totalPipelines": len(pipelines),
        "totalSchedules": len(schedules_rows),
        "totalRuns": len(runs_rows),
        "totalErrors": len(errors),
        "pipelinesWithSchedules": sum(1 for p in pipelines if p.get("scheduleCount", 0) > 0),
        "pipelinesWithoutSchedules": sum(1 for p in pipelines if p.get("scheduleCount", 0) == 0 and a.include_schedules),
        "pipelinesWithScheduleErrors": sum(1 for p in pipelines if p.get("scheduleStatus", "").startswith("error_")),
        "errorsByCategory": {},
        "schedulesByType": {},
        "schedulesByStatus": {},
        "runsByStatus": {},
        "runsByInvokeType": {},
    }
    for e in errors:
        cat = e.get("category", "unknown")
        summary["errorsByCategory"][cat] = summary["errorsByCategory"].get(cat, 0) + 1
    for r in schedules_rows:
        t = r.get("scheduleType", "?")
        summary["schedulesByType"][t] = summary["schedulesByType"].get(t, 0) + 1
        st = r.get("scheduleStatus", "?")
        summary["schedulesByStatus"][st] = summary["schedulesByStatus"].get(st, 0) + 1
    for r in runs_rows:
        st = r.get("status", "?")
        summary["runsByStatus"][st] = summary["runsByStatus"].get(st, 0) + 1
        it = r.get("invokeType", "?")
        summary["runsByInvokeType"][it] = summary["runsByInvokeType"].get(it, 0) + 1

    fmt = a.output_format
    if fmt in ("json", "both"):
        write_json(out / "catalog.json", catalog)
        write_json(out / "errors.json", errors)
        write_json(out / "summary.json", summary)
        if a.include_schedules:
            write_json(out / "schedules.json", schedules_raw)
    if fmt in ("csv", "both"):
        write_csv(out / "catalog.csv", rows)
        if pipelines:
            write_csv(out / "pipelines.csv", pipelines)
        if schedules_rows:
            write_csv(out / "pipeline_schedules.csv", schedules_rows)
        if runs_rows:
            write_csv(out / "pipeline_runs.csv", runs_rows)
        write_json(out / "errors.json", errors)
        write_json(out / "summary.json", summary)

    print(f"\nResumen:")
    print(f"  Workspaces:   {len(workspaces)}")
    print(f"  Items:        {len(rows)}")
    if a.include_schedules:
        print(f"  Pipelines:    {len(pipelines)}")
        print(f"  Programaciones: {len(schedules_rows)}")
        sin = summary.get("pipelinesWithoutSchedules", 0)
        if sin:
            print(f"  Pipelines sin programaciones: {sin}")
    if a.include_runs:
        print(f"  Ejecuciones:  {len(runs_rows)}")
    print(f"  Errores:      {len(errors)}")
    print(f"\nListo -> {out.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
