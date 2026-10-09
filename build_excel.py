"""Genera Excel organizado para el plan de transferencia a partir de catalog.csv."""
import glob, sys
from pathlib import Path
import pandas as pd
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter

src = sys.argv[1] if len(sys.argv) > 1 else sorted(glob.glob("output/*/catalog.csv"))[-1]
d = pd.read_csv(src, encoding="utf-8-sig").fillna("")
d[["Proyecto", "Ambiente"]] = d.workspace.str.split("-", n=1, expand=True)
ENVS = ["PROD", "STAGE", "TEST"]
d["Ambiente"] = pd.Categorical(d["Ambiente"], ENVS, ordered=True)

inv = d.rename(columns={"workspace": "Workspace", "itemType": "Tipo", "itemName": "Item",
    "description": "Descripcion", "itemId": "ItemId", "workspaceId": "WorkspaceId"})
inv = inv.sort_values(["Proyecto", "Ambiente", "Tipo", "Item"])
inv_out = inv[["Proyecto", "Ambiente", "Workspace", "Tipo", "Item", "Descripcion", "ItemId", "WorkspaceId"]].copy()
inv_out["Responsable"] = ""; inv_out["Prioridad"] = ""; inv_out["Estado transferencia"] = ""; inv_out["Observaciones"] = ""

res_ws = d.groupby(["Proyecto", "Ambiente"], observed=True).size().unstack(fill_value=0)[ENVS]
res_ws["Total"] = res_ws.sum(axis=1)
res_ws = res_ws.reset_index()

tipo = d.pivot_table(index="itemType", columns="workspace", values="itemId", aggfunc="count", fill_value=0)
tipo["Total"] = tipo.sum(axis=1)
tipo = tipo.sort_values("Total", ascending=False).reset_index().rename(columns={"itemType": "Tipo"})

pv = d.pivot_table(index=["Proyecto", "itemType", "itemName"], columns="Ambiente", values="itemId",
                   aggfunc="count", observed=True).reindex(columns=ENVS)
par = pv.notna().replace({True: "X", False: ""})
par["Ambientes"] = pv.notna().sum(axis=1)
par = par.reset_index().rename(columns={"itemType": "Tipo", "itemName": "Item"})
par["Observacion"] = par["Ambientes"].map({3: "En los 3 ambientes", 2: "Falta en un ambiente", 1: "Solo en un ambiente"})
par = par.sort_values(["Proyecto", "Ambientes", "Tipo", "Item"], ascending=[True, True, True, True])

sql = inv_out[inv_out.Tipo.isin(["Warehouse", "Lakehouse", "SQLEndpoint"])]
orq = inv_out[inv_out.Tipo.isin(["DataPipeline", "Dataflow", "CopyJob", "Notebook"])]
bi = inv_out[inv_out.Tipo.isin(["SemanticModel", "Report", "PaginatedReport"])]

out = Path("output") / "Inventario_Fabric_Transferencia.xlsx"
with pd.ExcelWriter(out, engine="openpyxl") as xw:
    res_ws.to_excel(xw, sheet_name="Resumen", index=False, startrow=3)
    tipo.to_excel(xw, sheet_name="Por tipo", index=False)
    par.to_excel(xw, sheet_name="Paridad ambientes", index=False)
    inv_out.to_excel(xw, sheet_name="Inventario completo", index=False)
    orq.to_excel(xw, sheet_name="Orquestacion y ETL", index=False)
    sql.to_excel(xw, sheet_name="Datos (WH-LH)", index=False)
    bi.to_excel(xw, sheet_name="BI (Modelos-Reportes)", index=False)

    hdr = PatternFill("solid", fgColor="1F4E78")
    for ws in xw.book.worksheets:
        hr = 4 if ws.title == "Resumen" else 1
        for c in ws[hr]:
            c.fill = hdr; c.font = Font(bold=True, color="FFFFFF"); c.alignment = Alignment(horizontal="center", wrap_text=True)
        for i, col in enumerate(ws.columns, 1):
            w = max((len(str(c.value)) for c in col[:300] if c.value is not None), default=8)
            ws.column_dimensions[get_column_letter(i)].width = min(max(w + 2, 10), 55)
        ws.freeze_panes = ws.cell(row=hr + 1, column=1)
        ws.auto_filter.ref = f"A{hr}:{get_column_letter(ws.max_column)}{ws.max_row}"
        if ws.title in ("Paridad ambientes",):
            for r in ws.iter_rows(min_row=2):
                for c in r[3:6]:
                    if c.value == "X": c.alignment = Alignment(horizontal="center"); c.fill = PatternFill("solid", fgColor="C6EFCE")
    r = xw.book["Resumen"]
    r["A1"] = "Inventario Microsoft Fabric - Plan de transferencia"; r["A1"].font = Font(bold=True, size=14)
    r["A2"] = f"Fuente: {src} | Total items: {len(d)} | Workspaces: {d.workspace.nunique()} | Tipos: {d.itemType.nunique()}"
print("OK", out.resolve())
