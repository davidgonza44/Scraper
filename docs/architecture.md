# Arquitectura

## Enfoque

BERA Price Tracker comienza como un monolito modular con Ports and Adapters de forma
pragmática. Los límites sirven para aislar reglas y contratos de los detalles externos,
sin introducir microservicios, eventos, una unidad de trabajo ni un framework.

## Responsabilidades

- **Domain** contiene modelos, identidad y validaciones que no dependen de I/O.
- **Application** define puertos y coordina recolecciones mediante `CollectListings`,
  inspecciones mediante `InspectLatestCollection`, lecturas mediante `GetListingHistory`
  y cálculos mediante `GetListingStatistics`.
- **Infrastructure** aloja adapters de marketplaces y el adapter local SQLite de
  persistencia.
- **CLI** interpreta comandos y errores; un composition root pequeño conecta providers,
  servicios y repositorios sin contener reglas de negocio.
- **Config** traduce variables de entorno a una configuración tipada sin leer archivos de
  secretos.

## Flujo esperado

```text
CLI / Scheduler
      |
      v
CollectListings (Application Service)
      |
      | search(query)
      v
MarketplaceProvider (port)
      |
      v
MercadoLibreProvider / FacebookMarketplaceProvider (adapters)
      |
      v
API oficial o mecanismo permitido por la plataforma
      |
      v
Normalización a Listing
      |
      v
CollectionBatch
      |
      v
ListingRepository (port) -> SQLiteListingRepository -> Price History
```

El adapter normaliza la respuesta externa a `Listing`. El servicio construye un
`CollectionBatch` y lo entrega al repositorio mediante `record_collection`, permitiendo
que SQLite guarde run, metadata y snapshots en una sola transacción. Un resultado vacío
también produce un run válido.

El CLI ofrece flujos separados:

```text
search  -> MercadoLibreProvider -> salida humana (solo lectura)
collect -> CollectListings -> MercadoLibreProvider + SQLiteListingRepository
inspect -> InspectLatestCollection -> CollectionInspectionRepository
                                  -> SQLiteCollectionInspectionRepository (mode=ro)
history -> GetListingHistory -> ListingHistoryRepository
                              -> SQLiteListingHistoryRepository (mode=ro)
stats   -> GetListingStatistics -> ListingHistoryRepository (mode=ro)
                                -> cálculo Decimal puro
```

El composition root valida y construye el provider antes de abrir SQLite. En `collect`,
el repositorio se cierra mediante context manager. El cliente HTTP creado internamente
por Mercado Libre es propiedad del provider y se cierra al terminar la búsqueda; un
cliente inyectado conserva ownership externo.

`inspect` reconstruye el último batch ya persistido para una combinación exacta de
source y query. El flujo es `CLI inspect -> InspectLatestCollection ->
CollectionInspectionRepository -> SQLite read-only`; no construye providers o writers,
no usa Internet y no necesita access token. El run se elige por `collected_at DESC` y
`collection_runs.id DESC`, y sus observaciones se muestran en el orden determinista de
`price_snapshots.id ASC`. El `LEFT JOIN` conserva también un último run vacío. `--limit`
solo acota las filas leídas y mostradas; el total sigue describiendo el batch completo.

`history` abre únicamente el adapter de lectura SQLite: no construye providers, no usa
HTTP y no ejecuta migraciones. El lookup usa `ListingKey(source, external_id)` y un JOIN
entre `listings`, `price_snapshots` y `collection_runs`; así cada observación incluye su
query sin duplicarla en el snapshot.

`stats` reutiliza exactamente ese puerto y adapter read-only. `GetListingStatistics`
deriva los valores en memoria con `Decimal`; no existe repositorio estadístico, SQL
agregado ni almacenamiento de resultados calculados.

## Providers y nuevas fuentes

`MarketplaceProvider` evita que la aplicación conozca HTTP, SDKs, sesiones o selectores.
Una fuente nueva implementará el protocolo, mapeará sus datos al dominio y añadirá su
identificador a `MarketplaceSource`. El dominio no importará el adapter ni sus
dependencias.

Mercado Libre se conecta mediante su API oficial usando un cliente HTTP síncrono
encapsulado en su adapter. Facebook Marketplace usa el dataset autorizado de Bright Data,
con un solo input y hasta cinco registros por ejecución; el provider clasifica antes de
mapear al dominio. No se implementan bypasses de CAPTCHA, anti-bot, rate limits,
autenticación, controles de acceso ni otras protecciones técnicas.

## Historial de precios

`ListingKey`, formado por `source` y `external_id`, identifica una publicación sin usar
un ID propio de una base de datos. `Listing` representa el resultado normalizado de una
recolección y conserva los metadatos y la consulta que lo descubrió.

Cada `PriceSnapshot` guarda solamente la clave de la publicación, el precio, la moneda y
el instante de recolección. SQLite separa esos datos en:

- `listings`: identidad natural y metadata actual, con `first_seen_at` y `last_seen_at`;
- `collection_runs`: fuente, consulta y timestamp de cada búsqueda;
- `price_snapshots`: precio y moneda de un listing dentro de un run.

El run aporta el timestamp al snapshot, evitando duplicarlo. Las restricciones únicas
hacen idempotente un retry del mismo run/listing, mientras otro run conserva una nueva
observación aunque el precio no cambie. El adapter usa una conexión por instancia, claves
foráneas, transacciones y WAL para concurrencia ligera; PostgreSQL sería más apropiado
para cargas de alta concurrencia.

Las lecturas `inspect` e `history` presentan la metadata actual de `listings`. El esquema
no conserva versiones anteriores de título, URL, vendedor, ubicación ni condición. En
una inspección antigua, precio y moneda sí pertenecen al run histórico, pero esa metadata
puede reflejar una recolección posterior.
