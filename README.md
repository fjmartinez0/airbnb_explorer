# airbnb_explorer

Seguimiento diario del calendario público de anuncios de Airbnb para inferir **reservas, anticipación de reserva y ocupación real** durante un periodo corto de observación.

Proyecto personal y educativo. Nació para contrastar las estimaciones de ocupación de [Inside Airbnb](https://insideairbnb.com/), que se basan en reseñas y cortes trimestrales, con lo que se observa día a día en unos pocos anuncios.

## Cómo funciona

1. **Captura** (`capture`): una vez al día abre cada anuncio en un navegador controlado por [Playwright](https://playwright.dev/python/), copia la respuesta del calendario que el propio sitio carga y la guarda.
2. **Comparación** (`analyze`): compara cada captura con la anterior. Una noche futura que pasa de *libre* a *no disponible* es una reserva probable. Una que pasa de *no disponible* a *libre* es una cancelación o un desbloqueo.
3. **Visor** (`viewer/index.html`): dos vistas.
   - **Resumen por zona:** ocupación promedio, tendencia de noches no disponibles, anticipación de reserva y tabla de anuncios, agrupados por las zonas que tú defines.
   - **Detalle por anuncio:** la matriz noche × día de captura, la anticipación y los eventos de un anuncio.

### Limitaciones

- "No disponible" mezcla reservas y bloqueos del anfitrión. Por eso el método se fija en los **cambios** de un día a otro, no en el estado.
- Dos reservas contiguas detectadas el mismo día se cuentan como una sola estancia.
- Los bloques nuevos de 28 noches o más se marcan como posible bloqueo y no cuentan como reserva.
- Con pocos anuncios y dos semanas, los resultados sirven para entender el comportamiento, no para estimar la ocupación de una zona.

## Estructura

```
airbnb_explorer/
├── explorer/               Código (paquete de Python)
│   ├── __main__.py         Línea de comandos (capture, analyze, export-viewer)
│   ├── config.py           Rutas y lectura de listings.json
│   ├── scraper.py          Navegador y captura del calendario
│   ├── parser.py           Respuesta de Airbnb → registros
│   ├── capture.py          Captura diaria de todos los anuncios
│   ├── storage.py          Archivos CSV y registro
│   ├── analysis.py         Detección de reservas y métricas
│   ├── viewer_data.py      Genera viewer/data.js
│   ├── notify.py           Notificaciones por ntfy
│   └── publish.py          Publicación del visor en GitHub Pages
├── viewer/index.html       Visor (se abre en cualquier navegador)
├── scheduling/             Programación diaria en macOS (launchd)
├── listings.example.json   Plantilla de anuncios
└── requirements.txt
```

Se generan localmente y **no se suben al repositorio**: `listings.json`, `settings.json`, `data/` y `viewer/data.js`.

## Instalación (macOS)

Requiere Python 3.9 o superior.

```bash
git clone https://github.com/fjmartinez0/airbnb_explorer.git
cd airbnb_explorer
pip3 install -r requirements.txt
python3 -m playwright install chromium
cp listings.example.json listings.json
```

Edita `listings.json` con tus anuncios:

```json
{"label": "lago-1", "id": "1450910272391543816", "zone": "El Lago", "host": ""}
```

- `id`: el número de `airbnb.com/rooms/<ID>`.
- `zone`: texto libre. Los anuncios con la misma zona se agrupan en el resumen.
- `host`: opcional. Si lo dejas vacío, se usa el nombre del anfitrión que aparece en el anuncio.

### Ajustes y notificaciones

```bash
cp settings.example.json settings.json
```

| Ajuste | Para qué |
|---|---|
| `ntfy_topic` | Canal de [ntfy](https://ntfy.sh) que recibe el resumen diario. Vacío = sin notificaciones. |
| `start_delay_minutes` | Espera aleatoria opcional antes de una corrida programada (por defecto 0: sin espera). |
| `pause_between_listings_seconds` | Pausa aleatoria entre anuncios (por defecto 60 a 300 s: de 1 a 5 min). |
| `retry_failed` | Reintenta una vez el anuncio que falle. |
| `publish_github_pages` | Publica el visor en la rama `gh-pages` después de cada captura. |
| `public_url` | Dirección del visor publicado; la notificación la abre al tocarla. |
| `public_include_identifiers` | Incluye nombres de anfitriones e IDs en la copia pública (por defecto no). |

Los canales del servidor público de ntfy son abiertos: cualquiera que conozca el nombre puede leerlos. Por eso la notificación solo incluye etiquetas, estados y conteos.

## Uso

```bash
python3 -m explorer capture --visible   # primera prueba, mostrando el navegador
python3 -m explorer capture             # captura normal
python3 -m explorer capture --only lago-1
python3 -m explorer analyze             # resultados en data/analysis/
python3 -m explorer notify-test         # prueba la notificación
open viewer/index.html                         # visor
```

### Programar la captura diaria

```bash
./scheduling/install_macos.sh        # todos los días a las 8:00
./scheduling/install_macos.sh 9      # o a otra hora
launchctl start com.airbnb-explorer.capture   # probar ahora
./scheduling/uninstall_macos.sh      # detener
```

Si el Mac está dormido a la hora programada, la captura corre al despertar.

### Visor en internet (GitHub Pages)

Con `publish_github_pages` activo, cada captura reconstruye el sitio (visor + datos) y lo sube como un único commit a la rama `gh-pages`, sin tocar `main`. La primera vez:

```bash
python3 -m explorer publish
```

y en GitHub: **Settings → Pages → Deploy from a branch → `gh-pages` / root**. Por defecto la copia pública omite nombres de anfitriones e IDs de anuncios; la copia local los conserva.

## Datos generados

| Archivo | Contenido |
|---|---|
| `data/calendar.csv` | Una fila por anuncio × noche × día de observación |
| `data/snapshots.csv` | Una fila por anuncio y captura: estado, noches no disponibles a 7 y 30 días, reseñas, anfitrión |
| `data/raw/` | Respuesta original de cada captura |
| `data/analysis/events.csv` | Reservas y liberaciones detectadas |
| `data/analysis/summary.csv` | Métricas por anuncio |

## Uso responsable

El script visita cada anuncio una vez al día, en orden aleatorio, con pausas largas entre anuncios y un perfil de navegador persistente. No usa proxies ni técnicas para ocultar la automatización.

Los términos de servicio de Airbnb restringen el acceso automatizado. Este proyecto está pensado para uso personal y educativo, con pocos anuncios y una consulta diaria. No publiques los datos capturados ni los identificadores de anuncios de terceros.

## Licencia

MIT
