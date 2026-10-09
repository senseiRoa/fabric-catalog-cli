# fabric_UT - Catalogo de Microsoft Fabric

Inventario de workspaces (prod/stage/test), items (pipelines, dataflows, notebooks,
warehouses, lakehouses, reportes, etc.) y definiciones, usando la REST API de Fabric.

Flujo completo: **1. generar el CSV -> 2. generar el Excel -> 3. correr el panel**.

## Requisitos

- [uv](https://docs.astral.sh/uv/) instalado
- Permisos de lectura en los workspaces (Viewer o superior; para
  `--export-definitions` hace falta Contributor o superior)

Instalar dependencias (una sola vez):

```bash
cd ~/downloads/fabric_UT
uv sync
```

## Paso 1. Generar el CSV (`fabric_catalog.py`)

```bash
# Todos los workspaces a los que tenes acceso
uv run fabric_catalog.py

# Solo algunos (filtro por substring del nombre, repetible)
uv run fabric_catalog.py -w prod -w stage -w test

# Ademas bajar las definiciones de cada item (pipelines, notebooks, .sql...)
uv run fabric_catalog.py -w prod -w stage -w test --export-definitions
```

Opciones utiles:

| Opcion | Para que |
| ------ | -------- |
| `--device-code` | Login por codigo (si no hay navegador, ej. SSH) |
| `--reset-login` | Borra la sesion guardada / cambia de cuenta |
| `--tenant <id>` | Fuerza un tenant especifico |
| `-o <carpeta>` | Carpeta de salida (default `output`) |

**Login:** lo haces VOS en el navegador (cuenta Microsoft/Entra). El script nunca
recibe tu contrasena, solo un token. `.auth_record.json` guarda solo metadata de la cuenta.

**Salida:** `output/<timestamp>/`

| Archivo | Contenido |
| ------- | --------- |
| `catalog.csv` | Una fila por item (workspace, tipo, nombre, id) |
| `catalog.json` | Detalle completo por workspace |
| `errors.json` | Workspaces/items que fallaron (permisos, tipo sin definicion) |
| `definitions/<ws>/<tipo>/<item>/...` | Definiciones decodificadas (solo con `--export-definitions`) |

## Paso 2. Generar el Excel (`build_excel.py`)

Toma automaticamente el `catalog.csv` mas reciente de `output/`:

```bash
uv run build_excel.py

# o indicando un CSV especifico
uv run build_excel.py output/20261005_120955/catalog.csv
```

Genera `output/Inventario_Fabric_Transferencia.xlsx` con las hojas:

1. **Resumen** - items por proyecto y ambiente
2. **Por tipo** - conteo por tipo de item y workspace
3. **Paridad ambientes** - en que ambientes (PROD/STAGE/TEST) existe cada item
4. **Inventario completo** - todos los items, con columnas vacias para Responsable,
   Prioridad, Estado transferencia y Observaciones
5. **Orquestacion y ETL** - pipelines, dataflows, copy jobs, notebooks
6. **Datos (WH-LH)** - warehouses, lakehouses, SQL endpoints
7. **BI (Modelos-Reportes)** - modelos semanticos y reportes

## Paso 3. Correr el panel visual (`app.py`)

```bash
uv run streamlit run app.py
```

Se abre en http://localhost:8501. Lee el ultimo `output/*/catalog.csv`
(o uno subido desde la barra lateral). Pestanas:

- **Resumen** - barras por workspace/tipo, mapa de calor, proyecto x ambiente
- **Mapa** - treemap interactivo (proyecto > workspace > tipo > item)
- **Paridad** - items por ambiente: completos, incompletos o solo en uno
- **Explorador** - tabla por workspace, detalle del item, link a Fabric y descarga CSV

Filtros en la barra lateral: proyecto, ambiente, tipo de item y busqueda por nombre.

## Limitaciones conocidas

- No todos los tipos de item soportan `getDefinition`; los que no, quedan en `errors.json`.
- Los esquemas de Warehouse (tablas, vistas, procs como `.sql`) se obtienen mejor via el
  endpoint SQL con `sqlpackage extract`; este proyecto cubre solo lo que expone la REST API.
- Metadata/lineage de TODO el tenant requiere rol Fabric Admin (Scanner API), no incluido.
- La paridad entre ambientes compara por nombre exacto del item.
- Si el tenant bloquea apps de terceros, el client id publico de Azure CLI puede estar
  bloqueado; pedi a IT una app registration y cambia `CLIENT_ID` en `fabric_catalog.py`.
