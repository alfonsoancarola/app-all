# Lineups · Argentina Grain Shipments

Dashboard de Streamlit para mirar los lineups mensuales (Alpemar Shipping
Agency) por producto, estado (Sailed / At Roads / Lineup), puerto de origen,
destino y shipper.

## Cómo correrla

```bash
pip install -r requirements.txt
streamlit run lineups_app.py
```

La app levanta cualquier archivo `GRAIN-SBS-BARLEY-MALT SHIPMENTS <Mes> 2026.xls`
que esté en esta carpeta. Para los meses cerrados (marzo, abril) toda la
volumetría aparece como **Sailed**. Para el mes en curso (mayo) la app separa:

- **Sailed** — sección `LOADED` del .xls (ya zarpó)
- **At Roads** — sección `AT ROADS` (en rada)
- **Lineup** — sección `ANNOUNCED` (anunciado, todavía no llegó)

## Estructura

- `lineups_app.py` — la app
- `requirements.txt` — dependencias
- `GRAIN-SBS-BARLEY-MALT SHIPMENTS <Mes> 2026.xls` — fuentes mensuales
- `Copia de app.py` — referencia (Farmer Selling)
