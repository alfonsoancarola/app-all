# App All

Mega-app que reúne **Farmer Selling** + **Lineups** + carpeta **MARS** en una
sola interfaz de Streamlit con menú de dos botones.

```
10. App All/
├── app_all.py          ← launcher (lo corrés con streamlit)
├── requirements.txt
├── README.md
├── fs_maiz/            ← antes en  ~/2. fs_maiz
├── Lineups/            ← antes en  ~/3. Lineups
└── 0. MARS/            ← antes en  ~/0. MARS
```

## Pasos finales de migración (UNA sola vez)

El sandbox de Claude copió todo lo chico (scripts, JSON, XLS, CSV chicos),
pero los dos archivos gordos de Farmer Selling — `sio_historico.csv` (2 GB)
y `_sio_chunks/` (2 GB) — los movés vos en la terminal porque dentro del
mismo disco un `mv` es instantáneo:

```bash
# 1) Mover los archivos gordos a la nueva ubicación
mv "/Users/alfonsoancarola/2. fs_maiz/data/sio_historico.csv" \
   "/Users/alfonsoancarola/10. App All/fs_maiz/data/sio_historico.csv"

mv "/Users/alfonsoancarola/2. fs_maiz/data/_sio_chunks" \
   "/Users/alfonsoancarola/10. App All/fs_maiz/data/_sio_chunks"

# 2) Limpiar los partials que dejó la copia (basura, ~2 GB)
rm -f "/Users/alfonsoancarola/10. App All/fs_maiz/data/.sio_historico.csv."*
rm -f "/Users/alfonsoancarola/10. App All/fs_maiz/data/sio_historico.csv.tmp"
```

## Reapuntar el cron diario (launchd) a la nueva carpeta

El pipeline diario de Farmer Selling (`make daily`) corre por `launchd`. Hay
que sacar el job viejo y registrar uno nuevo que apunte a la nueva ruta:

```bash
# Sacá el job viejo, parado en la carpeta vieja
cd "/Users/alfonsoancarola/2. fs_maiz"
make unschedule

# Registrá el job nuevo desde la carpeta nueva
cd "/Users/alfonsoancarola/10. App All/fs_maiz"
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
make schedule HORAS=10:45,18:45
```

> `make schedule` lee `pwd` para generar el plist, así que con tal de pararte
> en la nueva ruta antes de correrlo, queda apuntando bien.

## Correr la mega-app

```bash
cd "/Users/alfonsoancarola/10. App All"

# Primera vez
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Después siempre
source .venv/bin/activate
streamlit run app_all.py
```

Se abre el browser con dos botones grandes:

- 🌽 **Farmer Selling** → carga `fs_maiz/app.py` (todo lo que ya conocés:
  selector de cultivo, matriz, orígenes, destinos, logística, etc.)
- 🚢 **Lineups** → carga `Lineups/lineups_app.py` (current month, overview,
  port, destination, shipper, data)

Arriba a la izquierda, dentro de cada app, queda un botón **← Menú** para
volver al inicio sin tener que recargar Streamlit.

## Exponerla con ngrok (compartir con colegas)

Hay un script de conveniencia que lanza Streamlit + ngrok juntos:

```bash
cd "/Users/alfonsoancarola/10. App All"
./run_ngrok.sh
```

Te imprime la URL pública (ej. `https://abcd-1234.ngrok-free.app`) y deja
las dos cosas corriendo en la misma terminal. Ctrl+C apaga ambas.

Si 8501 está ocupado:

```bash
PORT=8505 ./run_ngrok.sh
```

Pre-requisitos (one-time):

```bash
brew install --cask ngrok
ngrok config add-authtoken <tu_token>      # https://dashboard.ngrok.com/get-started/your-authtoken
```

Si preferís dos terminales separadas, el patrón clásico funciona igual:

```bash
# Terminal 1
cd "/Users/alfonsoancarola/10. App All"
source .venv/bin/activate
streamlit run app_all.py

# Terminal 2
ngrok http 8501   # o el puerto que muestre Streamlit al arrancar
```

> Nota: la URL gratuita de ngrok cambia en cada reinicio. Si querés una URL
> fija, ngrok paid tiene "reserved domains" (~$8/mes). Para uso interno
> compartiendo el link cuando lo prendés está bien.

## Borrar las carpetas viejas (cuando confirmes que anda)

Cuando hayas hecho los pasos de arriba y verificado que la mega-app funciona
bien, podés borrar las carpetas originales:

```bash
rm -rf "/Users/alfonsoancarola/2. fs_maiz"
rm -rf "/Users/alfonsoancarola/3. Lineups"
rm -rf "/Users/alfonsoancarola/0. MARS"
```

## Cómo funciona el launcher por dentro

`app_all.py` hace una sola llamada a `st.set_page_config()` (Streamlit no
permite más de una por sesión). Cuando hacés click en un botón:

1. Hace `os.chdir()` a la subcarpeta de la app — así rutas relativas como
   `Path("data")` siguen funcionando igual que cuando se corría sola.
2. Inserta la subcarpeta en `sys.path` — así los `import cultivos`,
   `from cultivos import ...`, etc., resuelven los .py vecinos.
3. Lee el script original, le saca al vuelo la llamada a `set_page_config`
   (con regex), y hace `exec()` pasándole `__file__` y `__name__="__main__"`.

El código original de las dos apps queda **intacto**. Si en el futuro
querés volver a tener apps separadas, alcanza con copiar las subcarpetas a
donde quieras y correr `streamlit run <app.py>` de cada una.

## Si algo no funciona

- "MARS no aparece" → el wrapper exporta `LINEUPS_MARS_DIR=…/0. MARS` antes
  de correr Lineups. Si moviste MARS afuera, editá esa variable en
  `app_all.py` o exportala antes de lanzar Streamlit.
- "No me encuentra `cultivos`" → el wrapper agrega `fs_maiz/` a `sys.path`
  automáticamente. Si rompiste el path manualmente, restaurá el original
  o reiniciá Streamlit.
- "Streamlit dice `set_page_config can only be called once`" → te fallaron
  los strip del regex; chequeá que las dos apps tengan **exactamente una**
  llamada a `st.set_page_config(...)` (es así por defecto).
