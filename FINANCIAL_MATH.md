# FINANCIAL_MATH.md — Motor Matemático Farma (FIFO + Provisión IFRS 18)

Documenta la matemática implementada en [`databricks/farma_inventory_fifo.py`](./databricks/farma_inventory_fifo.py), que lee `gold_farma_sellthrough` y genera `gold_farma_provision_risk`.

## Granularidad del "lote"

`gold_farma_sellthrough` está agregado a nivel `(matnr, werks, fecha)` — no conserva el `LOTE` real de SAP. El `lote` de EDICOM (Sell-Out) es generado de forma independiente al `lote` de SAP (Sell-In) en los simuladores, por lo que un FIFO a nivel de lote físico real **no es reconstruible** con los datos disponibles. El motor FIFO trata cada fila `(matnr, werks, fecha)` como el **lote recibido ese día** — es la granularidad correcta y honesta dado el modelo de datos actual.

## 1. Stock On Hand (Window Functions)

Para cada combinación `(matnr, werks)`, ordenando por `fecha` ascendente:

```
acumulado_sellin(fecha_i)  = SUM(cantidad_blisters_sellin)  OVER (PARTITION BY matnr, werks ORDER BY fecha ROWS UNBOUNDED PRECEDING)
acumulado_sellout(fecha_i) = SUM(cantidad_blisters_sellout) OVER (PARTITION BY matnr, werks ORDER BY fecha ROWS UNBOUNDED PRECEDING)

stock_on_hand(fecha_i) = acumulado_sellin(fecha_i) - acumulado_sellout(fecha_i)
```

Es el inventario teórico en canal (lo que SAP entregó menos lo que EDICOM reportó vendido), acumulado hasta esa fecha.

## 2. Deducción FIFO lógica

FIFO asume que el Sell-Out consume primero los lotes (días) más antiguos. Dado:

- `total_sellout_final` = `MAX(acumulado_sellout)` sobre toda la partición `(matnr, werks)` — el consumo acumulado total observado (al final de la serie).
- `acumulado_sellin(fecha_i)` — lo recibido hasta e incluyendo el lote del día `i`.

El remanente del lote `i` es:

```
stock_remanente(fecha_i) = CLAMP( acumulado_sellin(fecha_i) - total_sellout_final ,  0 ,  cantidad_blisters_sellin(fecha_i) )
```

Interpretación:
- Si `acumulado_sellin(fecha_i) <= total_sellout_final`: el consumo total ya "pasó" este lote → **remanente = 0** (totalmente consumido).
- Si `acumulado_sellin(fecha_i) - total_sellout_final >= cantidad_blisters_sellin(fecha_i)`: el consumo nunca llegó a tocar este lote → **remanente = cantidad_blisters_sellin(fecha_i)** (intacto).
- En el punto donde el consumo acumulado "cruza" el lote: queda **parcialmente consumido**.

Esto reproduce exactamente el comportamiento de un FIFO físico sin necesitar una simulación fila-por-fila: es una fórmula cerrada sobre los acumulados.

## 3. Evaluación de caducidad y riesgo de provisión

Supuestos simulados (no existen en el modelo de datos origen, documentados aquí por transparencia):

- `SHELF_LIFE_DAYS = 270` (9 meses) — vida de anaquel uniforme por SKU. Elegido para ser demostrable dentro de los 365 días de historia de `farma_sell_in`; en un caso real este factor viene de `map_sku` o de la ficha técnica del producto.
- `COSTOS_UNITARIOS` — costo unitario simulado por blister, fijo por SKU (no aleatorio, reproducible entre corridas).

```
fecha_caducidad(fecha_i)    = fecha_i + SHELF_LIFE_DAYS
dias_para_caducar(fecha_i)  = fecha_caducidad(fecha_i) - CURRENT_DATE()

is_provision_risk(fecha_i)  = (stock_remanente(fecha_i) > 0) AND (dias_para_caducar(fecha_i) < 90)

provision_risk_value(fecha_i) = IF is_provision_risk THEN stock_remanente(fecha_i) * costo_unitario_simulado(matnr) ELSE 0
```

Un lote solo es "riesgo de provisión" si **todavía tiene stock remanente** (si ya se vendió completo, no hay nada que provisionar) **y** su caducidad está a menos de 90 días (o ya caducó, `dias_para_caducar` negativo).

## 4. Impacto en IFRS 18 — categoría Operating

`provision_risk_value` representa una **pérdida por deterioro de inventario** (inventario que probablemente no se podrá vender antes de caducar). Bajo IFRS, este tipo de provisión/write-down de inventario se reconoce como un **gasto operativo** (parte del costo de ventas o un cargo de deterioro), no como `Investing`, `Financing` ni `Taxes`.

En la estructura de `gold_acdoca_ifrs18` / `gold_ifrs18_pl.py`, esto significa que `provision_risk_value` es una señal que **debería eventualmente registrarse como una línea ACDOCA con `IFRS18_CATEGORY = 'Operating'`** (análoga a la cuenta `620000` de depreciación ya mapeada en `ifrs18_fsv_map`), **reduciendo el Operating Profit consolidado** en ese monto. Esta fase no modifica `gold_acdoca_ifrs18` — el cálculo queda documentado aquí como la base para una futura línea de asiento contable (`racct` de provisión por obsolescencia) dentro del Universal Journal.

## Resultado de la última corrida

- `gold_farma_provision_risk`: 2499 filas (matnr × werks × fecha).
- Lotes en riesgo de provisión (`is_provision_risk = true`): 1003.
- Impacto monetario total (`provision_risk_value`): **817,322.75** (moneda grupo).
