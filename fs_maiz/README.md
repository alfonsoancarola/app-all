# Farmer Selling · Maíz 25/26 (Mac, automatizado)

App Streamlit + pipeline diario que se ocupa solo de:

1. **Bajar el CSV** de SIO Granos (Playwright headless, sin login).
2. **Chequear MINAGRI** todos los días y agregar punto al histórico solo si hay archivo nuevo.
3. **Regenerar** `data/matriz_maiz.csv` con el formato exacto que consume la app.

Pensado para correr desde una Mac con `launchd` (cron nativo).

## Estructura

```
fs_maiz/
├── Makefile                     ← interfaz: make daily / sio / minagri / run
├── README.md
├── requirements.txt
├── app.py                       ← tu app Streamlit
├── descargar_sio.py             ← Playwright headless (SIO)
├── actualizar_minagri.py        ← scrape MAGYP + parser XLSX
├── actualizar_fs.py             ← genera data/matriz_maiz.csv
├── correr_diario.py             ← orquestador (lo que llama launchd)
├── com.alfonso.fsmaiz.plist     ← template launchd
└── data/
    └── minagri_historico.json
```

## 1. Instalar

```bash
cp -R "/Users/alfonsoancarola/Library/Application Support/Claude/local-agent-mode-sessions/11a8f2a8-0ecc-4c9b-928c-ccfa474201ba/2a263b06-1ca6-40e4-ab14-d8d36c1064a2/local_de0e9edf-b4dd-4b4e-8302-21ffea8fecb3/outputs/fs_maiz" ~/fs_maiz
cd ~/fs_maiz
make setup
```

`make setup` crea `.venv/`, instala Streamlit + Playwright + httpx + beautifulsoup4 + openpyxl,
y baja Chromium para Playwright (~150 MB, una sola vez).

## 2. Correr el flujo completo a mano

```bash
make daily
```

Equivalente a: bajar SIO → chequear MINAGRI → regenerar matriz.

Ver la app:

```bash
make run
```

## 3. Programar el job diario

```bash
make schedule              # default: 18:30 todos los días
make schedule HORA=09:00   # custom
make unschedule            # quitar
```

Esto instala un `LaunchAgent` en `~/Library/LaunchAgents/com.<vos>.fsmaiz.plist` que invoca
`correr_diario.py`. Logs a `launchd.log` dentro del proyecto.

> ⚠ Para que el job pueda correr Chromium en background, la primera vez `make schedule`
> puede pedirte permisos de "Acceso completo al disco" para `bash` o `python`. Lo concedés
> en *Configuración → Privacidad y seguridad → Acceso completo al disco*.

## 4. ¿Y si SIO o MAGYP cambian la página?

Para eso están los modos de descubrimiento:

```bash
make discover-sio        # imprime selects, inputs y botones que ve en SIO
make debug-sio           # abre Chromium visible y va más lento (mirás qué hace)
make discover-minagri    # imprime los links que parsea de MAGYP
```

Los selectores de SIO están en la constante `CONFIG` arriba de `descargar_sio.py`
(`producto`, `cosecha`, `es_final`, `tipos`). Si SIO cambia un nombre, ajustás eso.

Los headers que `actualizar_minagri.py` busca para ubicar PH y Fijado están en `TARGETS`
(arriba del archivo). Por defecto reconoce variantes con/sin acentos y con o sin guion
(`MAIZ 25/26`, `MAIZ 2025/26`, etc.).

## 5. Comandos útiles

| comando | qué hace |
|---|---|
| `make daily` | flujo full (lo que corre el cron) |
| `make sio` | solo descargar SIO a `~/Downloads/sio.csv` |
| `make minagri` | solo chequear MAGYP (no agrega punto si no cambió) |
| `make minagri-force` | forzar reparsing aunque la URL coincida — corré directo: `.venv/bin/python actualizar_minagri.py --force` |
| `make update SIO=~/Downloads/sio.csv MINAGRI=17800` | flujo manual viejo (CSV ya descargado, MINAGRI hardcodeado) |
| `make run` | levanta Streamlit |
| `make discover-sio` | debug SIO |
| `make discover-minagri` | debug MAGYP |
| `make clean` | borra `.venv` |

## Cómo funcionan los inputs

**SIO Granos** — `siogranos.com.ar/Consulta_publica/operaciones_informadas_exportar.aspx`.
Página ASP.NET pública. Hay que aplicar 4 filtros (Producto, Cosecha, Es Final, TIPO) y
clickear Exportar para que baje el CSV. Playwright hace exactamente eso, sin depender
de hacks del ViewState.

**MAGYP "Compras del sector exportador"** — `2026/2026.php` lista los Excel publicados
cada miércoles. El script:

1. Scrapea la página y encuentra el último link a `.xlsx` (por fecha en el filename).
2. Compara con la URL/hash cacheada en el JSON. Si coincide → no hace nada.
3. Si cambió, descarga el XLSX, busca la fila de Maíz 25/26 y suma PH + Fijado.
4. Agrega el punto a `data/minagri_historico.json` con la fecha del archivo.

Todo robusto a sumar el mismo día varias veces (sobreescribe el punto en lugar de duplicar).

## Formato del `matriz_maiz.csv`

Columnas: `tipo, label, MAM, JJ, AS, OND, JF, total, low, prior, min`

| tipo | qué representa |
|---|---|
| `mensual` | Una fila por mes de concertación, Mar-25 → mes anterior al actual |
| `diario` | Un día hábil de mayo 26 ya transcurrido, delta diario por grupo |
| `mayo_target` | 3 filas: Objetivo / Ritmo nec./día / Falta (días rest.) |

`min` es el delta mensual MINAGRI en toneladas (kt × 1000), por interpolación lineal.
