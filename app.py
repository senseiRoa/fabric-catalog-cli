"""Panel para explorar el catalogo de Microsoft Fabric.  Uso: uv run streamlit run app.py"""
import glob
from pathlib import Path

import altair as alt
import pandas as pd
import plotly.express as px
import streamlit as st

st.set_page_config(page_title="Fabric explorer", page_icon=":material/hub:", layout="wide")
ENVS = ["PROD", "STAGE", "TEST"]


@st.cache_data(ttl=600, show_spinner="Cargando catalogo...")
def load(src) -> pd.DataFrame:
    d = pd.read_csv(src, encoding="utf-8-sig").fillna("")
    d[["Proyecto", "Ambiente"]] = d["workspace"].str.split("-", n=1, expand=True)
    d["Ambiente"] = d["Ambiente"].where(d["Ambiente"].isin(ENVS), "OTRO")
    return d.rename(columns={"workspace": "Workspace", "itemType": "Tipo", "itemName": "Item",
                             "itemId": "ItemId", "workspaceId": "WorkspaceId",
                             "description": "Descripcion", "capacityId": "CapacityId"})


# ---------- Sidebar ----------
with st.sidebar:
    st.header(":material/tune: Filtros")
    files = sorted(glob.glob("output/*/catalog.csv"))
    upload = st.file_uploader("Otro catalog.csv (opcional)", type="csv")
    if upload is None and not files:
        st.error("No hay catalog.csv en output/. Corre fabric_catalog.py primero.")
        st.stop()
    src = upload if upload is not None else st.selectbox("Corrida", files[::-1])
    df = load(src)

    proy = st.multiselect("Proyecto", sorted(df.Proyecto.unique()), default=sorted(df.Proyecto.unique()))
    amb = st.pills("Ambiente", sorted(df.Ambiente.unique()), selection_mode="multi",
                   default=sorted(df.Ambiente.unique()))
    tipos = st.multiselect("Tipo de item", sorted(df.Tipo.unique()), placeholder="Todos")
    texto = st.text_input("Buscar por nombre", placeholder="ej: gold, fhir, pl_")

f = df[df.Proyecto.isin(proy) & df.Ambiente.isin(amb or df.Ambiente.unique())]
if tipos:
    f = f[f.Tipo.isin(tipos)]
if texto:
    f = f[f.Item.str.contains(texto, case=False, regex=False)]

# ---------- Header + KPIs ----------
st.title(":material/hub: Fabric explorer")
st.caption(f"Fuente: {getattr(src, 'name', src)}")
with st.container(horizontal=True):
    st.metric("Items", f"{len(f):,}", border=True)
    st.metric("Workspaces", f.Workspace.nunique(), border=True)
    st.metric("Tipos", f.Tipo.nunique(), border=True)
    st.metric("Pipelines", int((f.Tipo == "DataPipeline").sum()), border=True)
    st.metric("Notebooks", int((f.Tipo == "Notebook").sum()), border=True)
    st.metric("Warehouses / Lakehouses", int(f.Tipo.isin(["Warehouse", "Lakehouse"]).sum()), border=True)

if f.empty:
    st.warning("Los filtros no devuelven items.")
    st.stop()

tab_res, tab_tree, tab_par, tab_exp = st.tabs(
    [":material/bar_chart: Resumen", ":material/account_tree: Mapa", ":material/compare_arrows: Paridad", ":material/search: Explorador"])

# ---------- Resumen ----------
with tab_res:
    c1, c2 = st.columns(2)
    with c1, st.container(border=True):
        st.subheader("Items por workspace y tipo")
        by_ws = f.groupby(["Workspace", "Tipo"]).size().reset_index(name="Cantidad")
        ch = alt.Chart(by_ws).mark_bar().encode(
            y=alt.Y("Workspace:N", sort="-x"), x="Cantidad:Q",
            color=alt.Color("Tipo:N"), tooltip=["Workspace", "Tipo", "Cantidad"])
        st.altair_chart(ch, width="stretch", alt="Items por workspace apilados por tipo")
    with c2, st.container(border=True):
        st.subheader("Mapa de calor: tipo x workspace")
        ch = alt.Chart(by_ws).mark_rect().encode(
            x=alt.X("Workspace:N", axis=alt.Axis(labelAngle=-45)), y=alt.Y("Tipo:N"),
            color=alt.Color("Cantidad:Q", scale=alt.Scale(scheme="blues")),
            tooltip=["Workspace", "Tipo", "Cantidad"])
        txt = ch.mark_text(fontSize=10).encode(text="Cantidad:Q", color=alt.value("black"))
        st.altair_chart(ch + txt, width="stretch", alt="Mapa de calor de items por tipo y workspace")
    with st.container(border=True):
        st.subheader("Proyecto x ambiente")
        pa = f.groupby(["Proyecto", "Ambiente"]).size().reset_index(name="Cantidad")
        ch = alt.Chart(pa).mark_bar().encode(
            x="Proyecto:N", y="Cantidad:Q", xOffset="Ambiente:N",
            color=alt.Color("Ambiente:N", sort=ENVS), tooltip=["Proyecto", "Ambiente", "Cantidad"])
        st.altair_chart(ch, width="stretch", alt="Items por proyecto y ambiente")

# ---------- Treemap ----------
with tab_tree:
    st.caption("Click en un bloque para hacer zoom. Jerarquia: proyecto > workspace > tipo > item.")
    depth = st.segmented_control("Nivel de detalle", ["Hasta tipo", "Hasta item"], default="Hasta tipo")
    t = f.copy(); t["n"] = 1
    path = ["Proyecto", "Workspace", "Tipo"] + (["Item"] if depth == "Hasta item" else [])
    fig = px.treemap(t, path=path, values="n", color="Tipo")
    fig.update_layout(margin=dict(t=10, l=0, r=0, b=0), height=650)
    st.plotly_chart(fig, width="stretch")

# ---------- Paridad ----------
with tab_par:
    st.caption("Compara por nombre exacto en que ambientes existe cada item (ignora el filtro de ambiente).")
    base = df[df.Proyecto.isin(proy) & df.Ambiente.isin(ENVS)]
    if tipos:
        base = base[base.Tipo.isin(tipos)]
    if texto:
        base = base[base.Item.str.contains(texto, case=False, regex=False)]
    pv = base.pivot_table(index=["Proyecto", "Tipo", "Item"], columns="Ambiente", values="ItemId",
                          aggfunc="count").reindex(columns=ENVS).notna()
    pv["N"] = pv.sum(axis=1)
    pv = pv.reset_index()
    with st.container(horizontal=True):
        st.metric("En los 3 ambientes", int((pv.N == 3).sum()), border=True)
        st.metric("En 2", int((pv.N == 2).sum()), border=True)
        st.metric("En 1 solo", int((pv.N == 1).sum()), border=True)
    pick = st.segmented_control("Mostrar", ["Todos", "Incompletos", "Solo en 1"], default="Incompletos")
    show = pv if pick == "Todos" else pv[pv.N < 3] if pick == "Incompletos" else pv[pv.N == 1]
    chk = st.column_config.CheckboxColumn
    st.dataframe(show.drop(columns="N"), hide_index=True, height=450, alt="Paridad de items entre ambientes",
                 column_config={e: chk(e) for e in ENVS})

# ---------- Explorador ----------
with tab_exp:
    ws_list = sorted(f.Workspace.unique())
    ws = st.selectbox("Workspace", ["(todos)"] + ws_list)
    g = f if ws == "(todos)" else f[f.Workspace == ws]
    cols = ["Workspace", "Tipo", "Item", "Descripcion", "ItemId"]
    ev = st.dataframe(g[cols].sort_values(["Workspace", "Tipo", "Item"]), hide_index=True, height=420,
                      on_select="rerun", selection_mode="single-row", alt="Items del workspace seleccionado")
    if ev.selection.rows:
        row = g[cols].sort_values(["Workspace", "Tipo", "Item"]).iloc[ev.selection.rows[0]]
        with st.container(border=True):
            st.subheader(row["Item"])
            st.write(f"**Tipo:** {row['Tipo']}  \n**Workspace:** {row['Workspace']}")
            if row["Descripcion"]:
                st.write(row["Descripcion"])
            st.code(row["ItemId"], language=None)
            wsid = g.loc[g.Workspace == row["Workspace"], "WorkspaceId"].iloc[0]
            st.link_button("Abrir workspace en Fabric", f"https://app.fabric.microsoft.com/groups/{wsid}")
    st.download_button("Descargar vista como CSV", g[cols].to_csv(index=False).encode("utf-8-sig"),
                       "fabric_vista.csv", "text/csv", icon=":material/download:")
