"""Inventario de Microsoft Fabric: workspaces, items y (opcional) definiciones.

Autenticacion interactiva: el login lo haces VOS en el navegador (o con device code).
El script nunca ve ni guarda tu usuario/contrasena, solo recibe un token.

Uso:
    uv run fabric_catalog.py                       # catalogo de todos los workspaces
    uv run fabric_catalog.py -w prod -w stage -w test
    uv run fabric_catalog.py -w prod --export-definitions
"""
from __future__ import annotations

import argparse
import base64
import csv
import json
import re
import sys
import time
from datetime import datetime
from pathlib import Path

import requests
from azure.identity import (
    AuthenticationRecord,
    DeviceCodeCredential,
    InteractiveBrowserCredential,
    TokenCachePersistenceOptions,
)

API = "https://api.fabric.microsoft.com/v1"
SCOPE = "https://api.fabric.microsoft.com/.default"
# Cliente publico de Azure CLI (no requiere registrar app propia)
CLIENT_ID = "04b07795-8ddb-461a-bbee-02f9e1bf7b46"
AUTH_RECORD = Path(__file__).parent / ".auth_record.json"


def safe(name: str) -> str:
    return re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip() or "_"


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
        AUTH_RECORD.write_text(record.serialize())  # solo metadata, sin secretos
    return cred


class Fabric:
    def __init__(self, cred):
        self.cred = cred
        self.s = requests.Session()

    def _headers(self):
        tok = self.cred.get_token(SCOPE).token
        return {"Authorization": f"Bearer {tok}", "Content-Type": "application/json"}

    def request(self, method, url, **kw):
        for _ in range(6):
            r = self.s.request(method, url, headers=self._headers(), timeout=120, **kw)
            if r.status_code == 429:
                time.sleep(int(r.headers.get("Retry-After", "10")))
                continue
            return r
        return r

    def paged(self, path, key="value"):
        url, out = f"{API}{path}", []
        while url:
            r = self.request("GET", url)
            r.raise_for_status()
            body = r.json()
            out += body.get(key, [])
            tok = body.get("continuationToken")
            sep = "&" if "?" in path else "?"
            url = f"{API}{path}{sep}continuationToken={tok}" if tok else None
        return out

    def get_definition(self, ws_id, item_id, fmt=None):
        q = f"?format={fmt}" if fmt else ""
        r = self.request("POST", f"{API}/workspaces/{ws_id}/items/{item_id}/getDefinition{q}")
        if r.status_code == 200:
            return r.json()
        if r.status_code == 202:  # operacion larga (LRO)
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


def main():
    ap = argparse.ArgumentParser(description="Catalogo de Microsoft Fabric")
    ap.add_argument("-w", "--workspace", action="append",
                    help="Filtro por nombre (substring, case-insensitive). Repetible.")
    ap.add_argument("-o", "--out", default="output", help="Carpeta de salida")
    ap.add_argument("--export-definitions", action="store_true",
                    help="Baja la definicion de cada item (pipelines, notebooks, .sql...)")
    ap.add_argument("--device-code", action="store_true",
                    help="Login por device code (si no hay navegador)")
    ap.add_argument("--tenant", help="Tenant ID (opcional)")
    ap.add_argument("--reset-login", action="store_true", help="Borra la sesion guardada")
    a = ap.parse_args()

    if a.reset_login and AUTH_RECORD.exists():
        AUTH_RECORD.unlink()

    fab = Fabric(get_credential(a.device_code, a.tenant))
    out = Path(a.out) / datetime.now().strftime("%Y%m%d_%H%M%S")
    out.mkdir(parents=True, exist_ok=True)

    workspaces = fab.paged("/workspaces")
    if a.workspace:
        flt = [f.lower() for f in a.workspace]
        workspaces = [w for w in workspaces if any(f in w["displayName"].lower() for f in flt)]
    print(f"Workspaces a procesar: {len(workspaces)}")

    catalog, rows, errors = [], [], []
    for w in workspaces:
        print(f"\n== {w['displayName']} ({w['id']})")
        try:
            items = fab.paged(f"/workspaces/{w['id']}/items")
        except Exception as e:  # sin permisos, capacidad pausada, etc.
            errors.append({"workspace": w["displayName"], "stage": "list_items", "error": str(e)})
            print(f"   ! no se pudieron listar items: {e}")
            continue
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

        if a.export_definitions:
            for it in items:
                dest = out / "definitions" / safe(w["displayName"]) / f"{safe(it['type'])}" / safe(it["displayName"])
                try:
                    n = save_definition(fab.get_definition(w["id"], it["id"]), dest)
                    print(f"    ok  {it['type']}/{it['displayName']} ({n} archivos)")
                except Exception as e:
                    errors.append({"workspace": w["displayName"], "item": it["displayName"],
                                   "type": it["type"], "stage": "definition", "error": str(e)})
                    print(f"    --  {it['type']}/{it['displayName']}: sin definicion ({str(e)[:80]})")

    (out / "catalog.json").write_text(json.dumps(catalog, indent=2, ensure_ascii=False), "utf-8")
    (out / "errors.json").write_text(json.dumps(errors, indent=2, ensure_ascii=False), "utf-8")
    if rows:
        with open(out / "catalog.csv", "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=list(rows[0]))
            wr.writeheader()
            wr.writerows(rows)
    print(f"\nListo. {len(rows)} items, {len(errors)} errores -> {out.resolve()}")


if __name__ == "__main__":
    sys.exit(main())
