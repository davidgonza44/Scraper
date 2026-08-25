# BERA Price Tracker

Base inicial para recolectar y conservar el historial de precios de publicaciones de
pastillas de freno compatibles con la familia de aplicación H0019, incluidas sus
aplicaciones BERA y las demás aplicaciones confirmadas por el proveedor.

El proyecto integra la API oficial de Mercado Libre y Facebook Marketplace mediante
Apify (backend principal) o Bright Data experimental, además de un adapter local SQLite para conservar publicaciones, ejecuciones
de recolección y precios. No realiza scraping HTML ni automatización de navegador.

## Requisitos

- Python 3.12 o superior.
- `uv` es opcional, pero simplifica la creación del entorno de desarrollo.
- Node.js **24 LTS** para la GUI Reflex, administrado **por proyecto** con
  [fnm](https://github.com/Schniz/fnm). No uses Node 25 (Current) dentro de este
  repositorio: Reflex 0.8 genera un frontend con React Router 7.13 / Vite 6, que
  esperan una LTS (`>=20.19`). Node 25 provoca fallos de `react-router dev` en
  Windows (`EPERM` al hacer `scandir` de `.web/.react-router/types/app/routes`).
  El repositorio fija la major en `.nvmrc` y `.node-version`. Esto **no** exige
  reemplazar el Node global/default de otros proyectos (por ejemplo Node 25).

## Instalación de desarrollo

En PowerShell:

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -e ".[dev]"
```

La única dependencia de runtime Python documentada históricamente era `httpx`.
Hoy el extra de GUI también instala Reflex. Las herramientas de calidad se
instalan mediante el extra `dev`.

## Development on Windows

Este repositorio usa **Node 24 LTS solo dentro del proyecto**, mediante **fnm**.
El Node global del sistema (por ejemplo `v25.9.0`) puede seguir siendo el
habitual fuera de `D:\Scraper`.

> Node 24 es la versión requerida por este repositorio. Esto no requiere reemplazar la versión global/default de Node utilizada por otros proyectos.

La GUI Reflex se inicia con `.\dev.ps1`. Ese script **no** borra `.web`, **no**
mata procesos `node.exe` y **no** reinstala dependencias. `.web` se reutiliza
para que Reflex arranque más rápido. Reflex se fuerza a **npm** solo en esa
sesión (`REFLEX_USE_NPM=1`) porque Bun ha fallado en este frontend.

URL típica: http://localhost:3000

No dejes `reflex run` abierto después de una comprobación. No lances búsquedas
reales contra proveedores durante el arranque.

### Instalación inicial de fnm

Una sola vez, si todavía no tienes fnm:

```powershell
winget install Schniz.fnm
```

Cierra y vuelve a abrir PowerShell para que `fnm` quede en el PATH de la
sesión. No hace falta desinstalar Node 25 ni cambiar el PATH de forma
permanente desde este repositorio.

### Instalación de Node 24 administrado por fnm

Una sola vez, en cualquier directorio:

```powershell
fnm install 24
```

`fnm` guarda esa versión en su propio almacén. **No** reemplaza el Node global
del sistema. Si omites este paso, `.\dev.ps1` puede ejecutar `fnm install 24`
cuando falte; el efecto es el mismo y tampoco toca el Node global.

### Inicio normal del proyecto

Después de clonar o de `git pull`, y con `.venv` ya creado:

```powershell
cd D:\Scraper
.\dev.ps1
```

Rutina diaria:

```powershell
cd D:\Scraper
.\dev.ps1
```

`dev.ps1` se ejecuta desde la raíz del repositorio aunque lo llames desde otro
directorio. Usa `.venv\Scripts\python.exe` (no hace falta activar `.venv` a
mano), define `PYTHONPATH=src` y `REFLEX_USE_NPM=1` solo para esa sesión, y
arranca `python -m reflex run`.

### Verificación

Con el entorno fnm de este proyecto activo (dentro de `.\dev.ps1`, o tras
`fnm use 24` en esa sesión):

```powershell
node -v
```

debe mostrar una versión `v24.x.x`. Fuera de este proyecto, sin inicializar
fnm, `node -v` puede seguir mostrando el Node global (por ejemplo `v25.9.0`).

### Recuperación excepcional del frontend

`.web` está en `.gitignore` y **no** se borra en un arranque normal. Solo si el
frontend está corrupto (`Starting frontend failed`, `EPERM` / `scandir` en
`.web/.react-router\types\app\routes`):

```powershell
.\reset-frontend.ps1
```

Ese script intenta detener únicamente procesos ligados a `.web` o al Reflex de
este repositorio (no hace `taskkill /IM node.exe`), elimina `.web` y avisa de
que el siguiente `.\dev.ps1` será más lento porque Reflex reconstruirá el
frontend. No lo uses a diario.

### Opcional: fnm al hacer `cd`

Para que PowerShell seleccione Node 24 al entrar a este directorio gracias a
`.node-version`, puedes añadir **tú** la inicialización oficial de fnm a tu
perfil. **Este repositorio no modifica `$PROFILE`.**

1. Abre el perfil (créalo si no existe):

```powershell
if (!(Test-Path -LiteralPath $PROFILE)) {
    New-Item -Path $PROFILE -Type File -Force | Out-Null
}
notepad $PROFILE
```

2. Añade esta línea (inicialización oficial de fnm con `--use-on-cd`):

```powershell
fnm env --use-on-cd --shell powershell | Out-String | Invoke-Expression
```

3. Cierra y vuelve a abrir PowerShell.

Después, de forma opcional:

```powershell
cd D:\Scraper
node -v
```

puede mostrar Node 24 sin llamar a `.\dev.ps1`. Sigue siendo opcional: el
flujo soportado a diario es `.\dev.ps1`.

## CLI

```powershell
.\.venv\Scripts\python.exe -m bera_price_tracker --help
.\.venv\Scripts\python.exe -m bera_price_tracker doctor
.\.venv\Scripts\python.exe -m bera_price_tracker search "pastillas de freno bera"
.\.venv\Scripts\python.exe -m bera_price_tracker collect "pastillas de freno bera"
.\.venv\Scripts\python.exe -m bera_price_tracker collect "pastillas sbr" --provider facebook --city caracas --limit 5
.\.venv\Scripts\python.exe -m bera_price_tracker inspect "pastillas de freno bera"
.\.venv\Scripts\python.exe -m bera_price_tracker history MLV123456789
.\.venv\Scripts\python.exe -m bera_price_tracker stats MLV123456789
```

`doctor` es un diagnóstico completamente offline para comprobar la configuración y el
estado de SQLite antes de ejecutar `collect`. No realiza llamadas HTTP y solo informa si
el access token está configurado, sin revelar secretos:

```powershell
.\.venv\Scripts\bera-price-tracker.exe doctor
```

`search` consulta Mercado Libre y muestra ID externo, título, precio, moneda y URL.
Devuelve un error legible si falta configuración o si la API no puede completar la
búsqueda, y nunca escribe en SQLite. `collect` ejecuta el mismo provider mediante
`CollectListings`, guarda las observaciones y muestra la cantidad almacenada y la ruta de
la base.

`inspect` trabaja exclusivamente sobre SQLite local y muestra las publicaciones del
último batch ya recolectado para la combinación de source y query. No consulta Internet
ni requiere access token. `--limit` controla cuántas publicaciones se leen y muestran
(20 por defecto, entre 1 y 200), sin modificar los datos:

```powershell
.\.venv\Scripts\bera-price-tracker.exe inspect "pastillas de freno bera" --limit 50
```

`history` lee exclusivamente la base SQLite local y muestra la metadata actual y todas
las observaciones de precio de una publicación, incluyendo la query que la encontró. No
requiere Internet ni access token, pero la publicación debe haberse guardado antes con
`collect`. Mercado Libre es el source por defecto; puede indicarse explícitamente:

```powershell
.\.venv\Scripts\bera-price-tracker.exe history MLV123456789 --source mercado_libre
```

`stats` reutiliza ese historial local para calcular current/previous, mínimo, máximo,
media, mediana y cambios de una sola publicación. Tampoco requiere Internet ni token y
necesita al menos una observación previamente recolectada. No mezcla monedas ni compara
publicaciones entre sí:

```powershell
.\.venv\Scripts\bera-price-tracker.exe stats MLV123456789 --source mercado_libre
```

## Configuración

La configuración se lee directamente de variables de entorno. `.env.example` documenta
los nombres previstos, pero la aplicación no carga archivos `.env` ni almacena secretos.

Valores conservadores por defecto:

- `BERA_TRACKER_DATABASE_PATH=data/bera_price_tracker.db`
- `BERA_TRACKER_MERCADOLIBRE_PAGE_SIZE=50`
- `BERA_TRACKER_MERCADOLIBRE_MAX_PAGES=3`
- `BERA_TRACKER_MERCADOLIBRE_TIMEOUT_SECONDS=10`
- `BERA_TRACKER_MERCADOLIBRE_MAX_RETRIES=2`
- `BERA_TRACKER_BRIGHTDATA_BASE_URL=https://api.brightdata.com`
- `BERA_TRACKER_BRIGHTDATA_DATASET_ID=gd_lvt9iwuh6fbcwmx1a`
- `BERA_TRACKER_BRIGHTDATA_POLL_INTERVAL_SECONDS=5`
- `BERA_TRACKER_BRIGHTDATA_POLL_TIMEOUT_SECONDS=900`
- `BERA_TRACKER_FACEBOOK_CITY=caracas`
- `BERA_TRACKER_FACEBOOK_RECORD_LIMIT=5`
- `BERA_TRACKER_APIFY_API_TOKEN` (requerido para `--provider facebook`)

## Prueba manual de Mercado Libre

Esta prueba requiere Internet, una aplicación válida de Mercado Libre y un access token
vigente. No guardes el token en el repositorio.

```powershell
$env:BERA_TRACKER_MERCADOLIBRE_SITE_ID="MLV"
$env:BERA_TRACKER_MERCADOLIBRE_ACCESS_TOKEN="<TOKEN_REAL>"
$env:BERA_TRACKER_DATABASE_PATH="data/bera_price_tracker.db"

.\.venv\Scripts\bera-price-tracker.exe collect "pastillas de freno bera"
```

Volver a ejecutar `collect` registra otro punto temporal, incluso cuando un precio no
cambió. Una búsqueda con cero resultados también registra un `collection_run` válido,
sin listings ni snapshots.

El token se envía únicamente mediante `Authorization: Bearer` y nunca como query
parameter. Este proyecto todavía no implementa OAuth ni renovación de tokens.

## Clasificador experimental con Ollama

El adapter de IA usa exclusivamente la API local de Ollama. Requiere Ollama instalado,
una sesión autenticada y acceso previo al modelo `minimax-m3:cloud`. La autenticación cloud
la administra Ollama; BERA Price Tracker no requiere una API key ni llama directamente
a `ollama.com`.

Verificación manual opcional:

```powershell
ollama run minimax-m3:cloud
```

Configuración, con valores predeterminados:

```powershell
$env:BERA_TRACKER_OLLAMA_BASE_URL="http://localhost:11434"
$env:BERA_TRACKER_OLLAMA_MODEL="minimax-m3:cloud"
$env:BERA_TRACKER_OLLAMA_TIMEOUT_SECONDS="90"
```

El smoke tool es dry-run por defecto y no realiza inferencias:

```powershell
.\.venv\Scripts\python.exe tools\ollama_classifier_smoke.py
```

Una prueba real requiere `--execute` y realiza como máximo una inferencia, sin retries:

```powershell
.\.venv\Scripts\python.exe tools\ollama_classifier_smoke.py --execute
```

La petición usa `model`, `messages`, un único tool de clasificación, `stream=false` y
`think=false`. La clasificación se obtiene exclusivamente de los argumentos estructurados
del tool. El prompt y el schema distinguen los modelos BERA de las demás aplicaciones de
H0019; el adapter no reintenta ni usa `message.content` como fallback. Ante un fallo, el
resultado híbrido permanece en `REVIEW` y se informa el problema.

## Facebook Marketplace con Apify

Configura el token únicamente en el entorno; no lo guardes ni lo versiones:

```powershell
$env:BERA_TRACKER_APIFY_API_TOKEN = Read-Host "Apify API token" -MaskInput

.\.venv\Scripts\bera-price-tracker.exe collect "pastilla bera sbr" `
    --provider facebook --city caracas --limit 5
```



Bright Data permanece en el codigo como backend experimental/legacy y ya no es el default de `--provider facebook`.

Cada ejecución envía un solo input y como máximo un POST de scrape, con
`limit_per_input` limitado a 5. Una respuesta `202` se sigue mediante el mismo
`snapshot_id`; el polling nunca dispara otro scrape. Los items fallidos se descartan de
forma individual y el boundary conserva solamente los campos necesarios.

La clasificación H0019 determinista se ejecuta primero. MiniMax M3 se consulta por
Ollama solamente para candidatos `REVIEW`, siempre con el candidato sanitizado. Un fallo
o respuesta inválida de IA permanece en `REVIEW`; solo `RELEVANT` se convierte en
`Listing` y se persiste en el `CollectionBatch` atómico. El resumen del comando muestra
los contadores transitorios sin imprimir descriptions ni payloads raw.

`tools/brightdata_marketplace_spike.py` permanece como herramienta diagnóstica separada;
el comando `collect --provider facebook` usa Apify. `tools/brightdata_marketplace_spike.py` y el cliente Bright Data quedan como legado experimental.

### Diagnóstico de relevancia con `--explain`

`collect --explain` imprime una línea de decisión por candidato procesado:

```powershell
.\.venv\Scripts\bera-price-tracker.exe collect "pastilla bera sbr" `
    --provider facebook --city caracas --limit 5 --explain
```

Solo muestra datos permitidos: título saneado, precio, moneda, decisión, origen de la
clasificación, tipo de producto, coincidencia H0019, modelos, compatibilidad, posición y
una razón breve. Nunca imprime descriptions, cookies, `profile_id`, datos de contacto,
payloads raw, el token de Bright Data ni el prompt o la respuesta cruda de MiniMax. Los
candidatos descartados antes de clasificar aparecen como `SKIPPED` con `invalid_price`,
`non_ve`, `duplicate_product_id` o `source_error: bad_input`.

La opción es solo observabilidad: no altera la clasificación, la deduplicación, lo que se
persiste, ni el número de llamadas a Bright Data o a la IA.

## Persistencia SQLite

`SQLiteListingRepository` usa `sqlite3` de la biblioteca estándar, crea y migra la base
al abrirla, guarda dinero como texto decimal exacto y timestamps UTC como texto RFC3339.
La ruta se configura con `BERA_TRACKER_DATABASE_PATH`; su valor por defecto es
`data/bera_price_tracker.db`.

Cada ejecución se persiste como un batch atómico: run, metadata y snapshots comparten una
única transacción. Si falla cualquier listing, todo el batch se revierte.

Las lecturas de `inspect` y `history` usan adapters SQLite separados abiertos en modo de
solo lectura; no crean bases, no aplican migraciones y no modifican el esquema. La
metadata mostrada es la versión actual de `listings`: el esquema todavía no conserva
versiones históricas de título, URL, vendedor, ubicación o condición. Por ello, en
`inspect` el precio y la moneda pertenecen al run elegido, mientras esa metadata puede
haber sido actualizada por una recolección posterior.

## Calidad

```powershell
.\.venv\Scripts\ruff.exe format --check .
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe src tests
.\.venv\Scripts\python.exe -m pytest
```

Consulta [docs/architecture.md](docs/architecture.md) para conocer los límites de capas y
el flujo previsto.
