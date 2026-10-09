# fabric-catalog-cli - Catalogo de Microsoft Fabric

Inventario de workspaces, items (pipelines, dataflows, notebooks, warehouses,
lakehouses, reportes, etc.), **programaciones de pipelines** y **historial de
ejecuciones**, usando la REST API de Fabric.

## Flujo de ejecucion

```
┌─────────────────────────────────────────────────────────────┐
│  PASO 1: fabric_catalog.py                                  │
│  Consulta la API de Fabric y genera los CSVs                │
│                                                             │
│  uv run fabric_catalog.py --include-schedules --include-runs │
│                                                             │
│  Salida: output/<timestamp>/                                │
│    catalog.csv, pipelines.csv,                              │
│    pipeline_schedules.csv, pipeline_runs.csv, ...           │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  PASO 2: build_excel.py                                     │
│  Consolida TODO en un solo Excel unificado                  │
│                                                             │
│  uv run build_excel.py                                      │
│                                                             │
│  Salida: output/Inventario_Fabric_Transferencia.xlsx        │
│    10 hojas: items, pipelines, programaciones, ejecuciones  │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│  PASO 3 (opcional): panel visual                            │
│                                                             │
│  uv run streamlit run app.py                                │
│                                                             │
│  Panel interactivo en http://localhost:8501                  │
└─────────────────────────────────────────────────────────────┘
```

**Resumen rapido:**

```bash
# 1. Instalar dependencias (una sola vez)
uv sync

# 2. Extraer catalogo de Fabric
uv run fabric_catalog.py --include-schedules --include-runs

# 3. Generar Excel unificado
uv run build_excel.py
```

## Requisitos

- Python 3.13 o superior
- [uv](https://docs.astral.sh/uv/) instalado (ver seccion siguiente)
- Permisos de lectura en los workspaces (Viewer o superior; para
  `--export-definitions` hace falta Contributor o superior)

### Instalar uv

Si `uv` no esta instalado, seguir la guia oficial:
https://docs.astral.sh/uv/getting-started/installation/

**Windows (PowerShell):**

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

**macOS / Linux:**

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

**Con pip (si ya se tiene Python):**

```bash
pip install uv
```

**Con Homebrew (macOS):**

```bash
brew install uv
```

Verificar la instalacion:

```bash
uv --version
```

### Instalar dependencias del proyecto

```bash
cd fabric-catalog-cli
uv sync
```

## Paso 1. Generar el CSV (`fabric_catalog.py`)

```bash
# Catalogo basico de todos los workspaces
uv run fabric_catalog.py

# Solo algunos workspaces (filtro por substring, repetible)
uv run fabric_catalog.py -w prod -w stage -w test

# + programaciones de pipelines
uv run fabric_catalog.py --include-schedules

# + programaciones y historial de ejecuciones (ultimas 10 por pipeline)
uv run fabric_catalog.py --include-schedules --include-runs --runs-limit 10

# Todo junto
uv run fabric_catalog.py -w prod --include-schedules --include-runs --runs-limit 20

# Exportar definiciones de cada item
uv run fabric_catalog.py -w prod --export-definitions
```

Opciones utiles:

| Opcion | Descripcion |
| ------ | ----------- |
| `--include-schedules` | Consulta las programaciones de cada pipeline |
| `--include-runs` | Consulta el historial de ejecuciones (implica `--include-schedules`) |
| `--runs-limit N` | Maximo de ejecuciones por pipeline (default: 20) |
| `--item-type DataPipeline` | Filtra por tipo de item |
| `--schedule-status enabled\|disabled\|all` | Filtra el reporte de programaciones |
| `--timezone America/Bogota` | Zona horaria IANA para presentacion |
| `--output-format csv\|json\|both` | Formato de exportacion (default: both) |
| `--device-code` | Login por codigo (si no hay navegador) |
| `--reset-login` | Borra la sesion guardada / cambia de cuenta |
| `--tenant <id>` | Fuerza un tenant especifico |
| `-o <carpeta>` | Carpeta de salida (default `output`) |

**Autenticacion:** el login se realiza en el navegador (cuenta Microsoft/Entra)
o via device code. El script nunca recibe la contrasena, solo un token.
El archivo `.auth_record.json` guarda unicamente metadata de la cuenta.

**Salida:** `output/<timestamp>/`

| Archivo | Contenido |
| ------- | --------- |
| `catalog.csv` | Una fila por item (workspace, tipo, nombre, id) |
| `catalog.json` | Detalle completo por workspace |
| `pipelines.csv` | Inventario consolidado de pipelines con conteo de programaciones |
| `pipeline_schedules.csv` | Una fila por cada programacion detectada |
| `pipeline_runs.csv` | Historial de ejecuciones (con `--include-runs`) |
| `schedules.json` | Programaciones normalizadas con JSON original |
| `errors.json` | Errores detallados por workspace, pipeline y etapa |
| `summary.json` | Estadisticas generales del inventario |
| `definitions/<ws>/<tipo>/<item>/...` | Definiciones decodificadas (con `--export-definitions`) |

### Campos de `pipelines.csv`

| Campo | Descripcion |
| ----- | ----------- |
| `workspaceName` / `workspaceId` | Workspace del pipeline |
| `pipelineName` / `pipelineId` | Identificacion del pipeline |
| `description` | Descripcion del pipeline |
| `scheduleCount` | Numero de programaciones detectadas |
| `scheduleStatus` | `con_programaciones`, `sin_programaciones` o `error_*` |

### Campos de `pipeline_schedules.csv`

| Campo | Descripcion |
| ----- | ----------- |
| `workspaceName` / `workspaceId` | Workspace del pipeline |
| `pipelineName` / `pipelineId` | Pipeline al que pertenece la programacion |
| `scheduleId` | ID de la programacion |
| `scheduleEnabled` | `true` / `false` segun la API |
| `scheduleStatus` | `habilitada`, `deshabilitada`, `vencida` o `desconocida` |
| `scheduleType` | `Daily`, `Weekly`, `Monthly` o `Cron` |
| `scheduleDescription` | Descripcion legible en espanol |
| `startDateTime` / `endDateTime` | Vigencia de la programacion (UTC) |
| `localTimeZoneId` | Zona horaria original (ID de Windows) |
| `convertedTime` | Hora convertida a la zona de referencia |
| `convertedTz` | Zona horaria de conversion utilizada |
| `conversionOk` | `true` si la conversion fue exitosa |
| `ownerId` / `ownerType` | Usuario o servicio que creo la programacion |
| `createdDateTime` | Fecha de creacion (UTC) |
| `configurationJson` | JSON original de la configuracion |
| `collectionStatus` | Estado de la coleccion |
| `collectedAtUtc` | Momento de recoleccion (UTC) |

### Ejemplos de `scheduleDescription`

- `Todos los dias a las 19:00 (SA Pacific Standard Time)`
- `De lunes a viernes a las 02:00 (SA Pacific Standard Time)`
- `Lunes y miercoles a las 06:30 (SA Pacific Standard Time)`
- `El dia 15 de cada mes a las 04:00 (SA Pacific Standard Time)`
- `Intervalo de 10 minutos (SA Pacific Standard Time)`
- `Configuracion no interpretada` (si el tipo no se reconoce)

### Campos de `pipeline_runs.csv`

| Campo | Descripcion |
| ----- | ----------- |
| `workspaceName` / `workspaceId` | Workspace del pipeline |
| `pipelineName` / `pipelineId` | Pipeline ejecutado |
| `runId` | ID de la ejecucion |
| `invokeType` | `Scheduled` o `Manual` (devuelto por la API) |
| `status` | `Completed`, `Failed`, `InProgress`, `Cancelled`, etc. |
| `startTimeUtc` / `endTimeUtc` | Inicio y fin (UTC) |
| `duration` | Duracion calculada (ej: `0:01:23.456`) |
| `failureReason` | Motivo del fallo (JSON si hay error) |
| `rootActivityId` | ID de correlacion para trazas |
| `jobType` | Tipo de job (ej: `Execute`) |
| `collectedAtUtc` | Momento de recoleccion (UTC) |

### Campos de `summary.json`

| Campo | Contenido |
| ----- | --------- |
| `workspacesProcessed` | Workspaces procesados |
| `totalItems` | Items inventariados |
| `totalPipelines` | Pipelines encontrados |
| `totalSchedules` | Programaciones detectadas |
| `totalRuns` | Ejecuciones registradas |
| `totalErrors` | Errores acumulados |
| `pipelinesWithSchedules` | Pipelines con al menos una programacion |
| `pipelinesWithoutSchedules` | Pipelines sin programaciones consultables |
| `pipelinesWithScheduleErrors` | Pipelines con errores al consultar schedules |
| `errorsByCategory` | Conteo por categoria (forbidden, not_found, etc.) |
| `schedulesByType` | Conteo por tipo (Daily, Weekly, Monthly, Cron) |
| `schedulesByStatus` | Conteo por estado (habilitada, vencida, etc.) |
| `runsByStatus` | Conteo de ejecuciones por estado |
| `runsByInvokeType` | Conteo por tipo de invocacion |

## Paso 2. Generar el Excel unificado (`build_excel.py`)

Lee automaticamente el `catalog.csv` mas reciente de `output/` y los CSVs de
programaciones/ejecuciones de la misma carpeta:

```bash
# Toma el catalog.csv mas reciente
uv run build_excel.py

# o indicando un catalog.csv especifico
uv run build_excel.py output/20261005_120955/catalog.csv
```

Genera `output/Inventario_Fabric_Transferencia.xlsx` con **todo unificado**:

1. **Resumen** - items por proyecto y ambiente
2. **Por tipo** - conteo por tipo de item y workspace
3. **Paridad ambientes** - en que ambientes (PROD/STAGE/TEST) existe cada item
4. **Inventario completo** - todos los items, con columnas vacias para Responsable,
   Prioridad, Estado transferencia y Observaciones
5. **Orquestacion y ETL** - pipelines, dataflows, copy jobs, notebooks
6. **Datos (WH-LH)** - warehouses, lakehouses, SQL endpoints
7. **BI (Modelos-Reportes)** - modelos semanticos y reportes
8. **Pipelines** - inventario de pipelines con conteo de programaciones *(si existe `pipelines.csv`)*
9. **Programaciones** - una fila por programacion, con colores por estado *(si existe `pipeline_schedules.csv`)*
10. **Ejecuciones** - historial de ejecuciones, con colores por estado *(si existe `pipeline_runs.csv`)*

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

## Tests

```bash
uv run pytest tests/ -v
```

39 tests unitarios con respuestas JSON simuladas (sin acceso real a Fabric).
Cubren: programaciones diaria/semanal/mensual/cron, pipelines sin programaciones,
configuraciones desconocidas, paginacion, errores HTTP 403/404/429/5xx,
conversion de zona horaria y exportacion CSV/JSON con caracteres espanoles.

## Permisos

| Endpoint | Scopes delegados necesarios |
| -------- | --------------------------- |
| Listar workspaces/items | `Item.Read.All` o `Workspace.Read.All` |
| Listar programaciones de pipelines | `DataPipeline.Read.All`, `Item.Read.All` o superior |
| Listar ejecuciones de pipelines | `DataPipeline.Read.All`, `Item.Read.All` o superior |
| Exportar definiciones | `Contributor` o superior en el workspace |

El script usa autenticacion interactiva (login en navegador o device code).
No almacena contrasenas ni tokens de acceso en archivos de salida.

**El script es exclusivamente de lectura.** No modifica recursos de Fabric.

## Limitaciones conocidas

- No todos los tipos de item soportan `getDefinition`; los que no, quedan en `errors.json`.
- Los esquemas de Warehouse (tablas, vistas, procs como `.sql`) se obtienen mejor via el
  endpoint SQL con `sqlpackage extract`; este proyecto cubre solo lo que expone la REST API.
- Metadata/lineage de TODO el tenant requiere rol Fabric Admin (Scanner API), no incluido.
- La paridad entre ambientes compara por nombre exacto del item.
- Si el tenant bloquea apps de terceros, el client id publico de Azure CLI puede estar
  bloqueado; solicitar a IT una app registration y cambiar `CLIENT_ID` en `fabric_catalog.py`.
- El tipo `Cron` en Fabric usa un intervalo en **minutos**, no una expresion cron convencional.
- Si una programacion tiene un tipo de configuracion no reconocido, se muestra
  `Configuracion no interpretada` y se conserva el JSON original.
- La conversion de zona horaria usa identificadores IANA; el campo original
  `localTimeZoneId` usa identificadores de Windows (ej: `SA Pacific Standard Time`).
- No se verifica contra un entorno real de Fabric en las pruebas; los tests usan
  respuestas JSON simuladas basadas en la documentacion oficial.
