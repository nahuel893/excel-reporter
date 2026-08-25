# Acciones Comerciales — Deep EDA (pandas-pro)

Periodo: 2026-07-01 → 2026-07-21 (21 días cerrados)

---

## 1. Data assessment

### `FACT_NET` — 1,812 rows × 8 cols · 0.5 MB
cols: Sucursal, Código, Descripción_2, Descripción_3, Descripción_12, Suma de Facturacion Neta…

**Nulls**:
  - `Código`: 1 (0.1%)
  - `Descripción_2`: 1 (0.1%)
  - `Descripción_3`: 1 (0.1%)
  - `Descripción_12`: 1 (0.1%)
  - `Suma de Campo1`: 67 (3.7%)

### `ART-ACCION` — 1,843 rows × 7 cols · 0.5 MB
cols: SUCURSAL, Artículo Distribuidora, Descripción, Acción, Descripción Acción, mvb…

**Nulls**:
  - `Artículo Distribuidora`: 1 (0.1%)
  - `Descripción`: 1 (0.1%)
  - `Acción`: 1 (0.1%)
  - `Descripción Acción`: 1 (0.1%)
  - `mvb`: 1 (0.1%)

### `CLIENTE-FECHA` — 51,563 rows × 10 cols · 22.1 MB
cols: Fecha, SUCURSAL, Cod. Cliente, Razón Social, Artículo Distribuidora, Descripción…

**Nulls**:
  - `Fecha`: 1 (0.0%)
  - `SUCURSAL`: 1 (0.0%)
  - `Cod. Cliente`: 1 (0.0%)
  - `Razón Social`: 1 (0.0%)
  - `Artículo Distribuidora`: 1 (0.0%)
  - `Descripción`: 1 (0.0%)
  - `Calibre`: 1 (0.0%)
  - `Acción`: 1 (0.0%)
  - `Descripción Acción`: 1 (0.0%)

### `wapi` — 55,202 rows × 29 cols · 41.1 MB
cols: Fecha, Comprobante, Agrupaciones, Cod. Cliente, Razón Social, Dirección…

**Nulls**:
  - `Fecha`: 1 (0.0%)
  - `Comprobante`: 1 (0.0%)
  - `Agrupaciones`: 52,851 (95.7%)
  - `Cod. Cliente`: 1 (0.0%)
  - `Razón Social`: 1 (0.0%)
  - `Dirección`: 1 (0.0%)
  - `Artículo CMQ`: 55,202 (100.0%)
  - `Descripción`: 1 (0.0%)
  - `Marca`: 2 (0.0%)
  - `Calibre`: 2 (0.0%)
  - `Precio Neto SF`: 1 (0.0%)
  - `Cantidad Sin Cargo`: 42,862 (77.6%)
  - `Descuento %`: 12,340 (22.4%)
  - `Acción`: 1 (0.0%)
  - `Descripción Acción`: 1 (0.0%)
  - `Artículo Distribuidora`: 1 (0.0%)
  - `SUCURSAL`: 27 (0.0%)
  - `CONCAT`: 1 (0.0%)
  - `PRECIO FINAL `: 584 (1.1%)
  - `mvb`: 1 (0.0%)
  - `ZONA`: 21,173 (38.4%)
  - `Tipo Descuento`: 1 (0.0%)

---

## 2. Outliers en descuentos (FACT_NET)

**Quantiles de descuentos por (sucursal, artículo)**:

| quantile | value |
|---|---|
| 0.500 | 0 |
| 0.900 | 230,420 |
| 0.950 | 983,733 |
| 0.990 | 5,494,950 |
| 0.999 | 30,307,792 |
| 1.000 | 43,887,843 |

- Filas con descuento < 0 (devoluciones/ajustes): **7** (0.39%)
- Filas con descuento = 0 (sin promoción): **928** (51.24%)
- Filas con descuento > 0 (con promoción): **876**

**Top 10 filas con mayor descuento** (probable concentración):

| Sucursal                        | Descripción_2              | Descripción_12   |   Suma de Descuentos |
|:--------------------------------|:---------------------------|:-----------------|---------------------:|
| 1 - CASA CENTRAL                | SALTA RUBIA 1000 * 12 VR   | CERVEZAS         |          4.38878e+07 |
| 1 - CASA CENTRAL                | SALTA RUBIA 1200 * 10      | CERVEZAS         |          3.26111e+07 |
| 9 - SUCURSAL PERICO             | SCHNEIDER 710*24 LATA 0606 | CERVEZAS         |          2.97675e+07 |
| 4 - SUCURSAL JOAQUIN V GONZALEZ | SCHNEIDER 710*24 LATA 0606 | CERVEZAS         |          1.92204e+07 |
| 11 - SUCURSAL MAIMARA           | NORTE 1000*12 VR           | CERVEZAS         |          1.90427e+07 |
| 1 - CASA CENTRAL                | CARPANO ROSSO 950 * 6      | FRATELLI B       |          1.67371e+07 |
| 5 - SUCURSAL METAN              | SCHNEIDER 710*24 LATA 0606 | CERVEZAS         |          1.63526e+07 |
| 7 - SUCURSAL TARTAGAL           | SCHNEIDER 710*24 LATA 0606 | CERVEZAS         |          1.26392e+07 |
| 6 - SUCURSAL ORAN               | SCHNEIDER 710*24 LATA 0606 | CERVEZAS         |          1.23633e+07 |
| 15 - SUCURSAL SAN PEDRO         | SCHNEIDER 710*24 LATA 0606 | CERVEZAS         |          1.20382e+07 |

---

## 3. Pareto de clientes (concentración de descuentos)

- **9,974 clientes** distintos con descuento en el período.
- Top 20 clientes = **14.4%** del descuento total.
- Top 50 clientes = **20.4%**.
- Top 100 clientes = **26.6%**.
- Mitad del descuento = primeros **597** clientes (índice de concentración).

- **HHI** del descuento (cliente): 0.0026 (diversificado)

---

## 4. Patrones temporales (cliente-fecha)

**Descuento por día de la semana**:

| weekday   |   descuento |   ops |   ratio_d_f |
|:----------|------------:|------:|------------:|
| Friday    | 1.08092e+08 | 11104 |   0.245024  |
| Monday    | 8.60408e+07 |  8243 |   0.195037  |
| Saturday  | 9.52427e+07 | 10846 |   0.215896  |
| Thursday  | 3.65333e+07 |  5551 |   0.0828137 |
| Tuesday   | 6.5646e+07  |  7104 |   0.148806  |
| Wednesday | 4.95949e+07 |  7155 |   0.112422  |

**Volatilidad diaria del descuento (CV)**: 0.746

- Día con más descuento: **2026-07-18** — $60,336,138
- Día con menos descuento: **2026-07-09** — $584,859

---

## 5. Eficiencia promocional por genérico CCU (lower D/F = mejor)

| Descripción_12   |        fact |             desc |   arts |   ratio_d_f |     desc_per_art |
|:-----------------|------------:|-----------------:|-------:|------------:|-----------------:|
| CERVEZAS         | 3.23576e+09 |      3.71029e+08 |     60 |  0.114665   |      6.18382e+06 |
| AGUAS DANONE     | 2.74686e+08 |      5.53715e+07 |     60 |  0.201581   | 922858           |
| FRATELLI B       | 8.29143e+08 |      3.43084e+07 |     27 |  0.0413781  |      1.27068e+06 |
| VINOS            | 2.39143e+08 |      2.71548e+07 |     15 |  0.113551   |      1.81032e+06 |
| VINOS CCU        | 1.868e+08   |      9.83307e+06 |     38 |  0.0526396  | 258765           |
| PERNOD RICARD    | 4.75292e+07 |      4.35025e+06 |     81 |  0.091528   |  53706.8         |
| BOUTIQUE         | 2.1219e+06  |      1.68554e+06 |     21 |  0.794352   |  80263.7         |
| SIDRAS Y LICORES | 2.32886e+06 | 616881           |     13 |  0.264886   |  47452.4         |
| JUGOS            | 3.16324e+06 | 530212           |     27 |  0.167617   |  19637.5         |
| GASEOSAS         | 2.83813e+07 | 312669           |     15 |  0.0110167  |  20844.6         |
| VINOS FINOS      | 1.09568e+07 | 180886           |     42 |  0.016509   |   4306.81        |
| ENERGIZANTES     | 1.63996e+07 | 104724           |      3 |  0.00638577 |  34908           |
| TAMBO            | 1.42935e+06 |   4132.23        |     14 |  0.00289099 |    295.159       |
| ENVASES CCU      | 1.07231e+06 |      0           |      5 |  0          |      0           |

- **Ratio D/F promedio CCU**: 14.51%
- **Ratio D/F promedio No-CCU**: 12.82%
- **CCU** está más presionado promocionalmente.

---

## 6. Sucursales — eficiencia relativa (facturación & ratio)

Ratio global: 10.36%. Sucursales ordenadas por desvío vs global:

| Sucursal                        |        fact |        desc |   arts |   ratio_d_f |   desc_per_art |   vs_global |
|:--------------------------------|------------:|------------:|-------:|------------:|---------------:|------------:|
| 5 - SUCURSAL METAN              | 2.44623e+08 | 3.58339e+07 |    127 |   0.146486  |       282156   |  0.0428807  |
| 4 - SUCURSAL JOAQUIN V GONZALEZ | 2.65399e+08 | 3.3032e+07  |    157 |   0.124462  |       210395   |  0.020856   |
| 11 - SUCURSAL MAIMARA           | 2.46258e+08 | 2.83601e+07 |     98 |   0.115164  |       289389   |  0.0115588  |
| 9 - SUCURSAL PERICO             | 3.47683e+08 | 3.95921e+07 |    132 |   0.113874  |       299940   |  0.0102688  |
| 10 - SUCURSAL LIBERTADOR        | 2.9847e+08  | 3.34606e+07 |    125 |   0.112107  |       267685   |  0.00850131 |
| 1 - CASA CENTRAL                | 2.0135e+09  | 2.16883e+08 |    351 |   0.107714  |       617901   |  0.00410888 |
| 12 - SUCURSAL HUMAHUACA         | 1.05257e+08 | 1.03208e+07 |     87 |   0.0980539 |       118630   | -0.00555159 |
| 15 - SUCURSAL SAN PEDRO         | 2.23253e+08 | 2.05841e+07 |    131 |   0.0922009 |       157130   | -0.0114046  |
| 14 - SUCURSAL LA QUIACA         | 1.17486e+08 | 9.58257e+06 |     93 |   0.0815638 |       103038   | -0.0220417  |
| 7 - SUCURSAL TARTAGAL           | 3.66281e+08 | 2.975e+07   |    125 |   0.0812218 |       238000   | -0.0223837  |
| 3 - SUCURSAL CAFAYATE           | 2.31703e+08 | 1.79959e+07 |    145 |   0.0776678 |       124109   | -0.0259377  |
| 6 - SUCURSAL ORAN               | 2.88217e+08 | 2.16601e+07 |    146 |   0.075152  |       148357   | -0.0284535  |
| 16 - SUCURSAL GUEMES            | 1.30783e+08 | 8.42717e+06 |     93 |   0.0644361 |        90614.8 | -0.0391694  |

- Sucursales con ratio **mayor** al global están más presionadas (peligro margen).
- Sucursales con ratio **menor** al global son más disciplinadas (potencialmente sub-invertidas en promo).

---

## 7. Distribución de tipo de descuento (wapi)

| Tipo Descuento   |   ops |   descuento |        fact |   ratio_d_f |
|:-----------------|------:|------------:|------------:|------------:|
| Descuentos       | 42862 | 3.10255e+08 | 2.96133e+09 |    0.104769 |
| SIN CARGO        | 12339 | 1.31129e+08 | 4.55184e+08 |    0.288079 |

---

## 8. Anomalías — comprobantes y multi-precio

- Comprobantes duplicados en wapi: **23,795** (43.11% de filas)

**Mix por zona (wapi)** — cuántos ops y descuentos:

| ZONA              |   ops |   descuento |        fact |   ratio_d_f |
|:------------------|------:|------------:|------------:|------------:|
| Antonio Cabrerizo | 23520 | 1.90219e+08 | 1.16545e+09 |    0.163216 |
| Adrian Garcia     |  6754 | 4.98662e+07 | 3.03812e+08 |    0.164135 |
| Hernan Yapura     |  3755 | 3.67566e+07 | 3.24534e+08 |    0.11326  |

---

## 9. Top acciones (ART-ACCION) — best/worst ratio

Total acciones: **236**

Top 10 acciones por descuento:

| Acción   | Descripción Acción                           |   descuento |   arts |   sucursales |     desc_per_art |
|:---------|:---------------------------------------------|------------:|-------:|-------------:|-----------------:|
| P2772    | YAPURA SCH 710 MUNDIAL 20%                   | 5.777e+07   |      1 |            8 |      5.777e+07   |
| P2773    | GARCIA SCH 710 MUNDIAL 20%                   | 3.1592e+07  |      1 |            4 |      3.1592e+07  |
| B0004    | VYP                                          | 2.86864e+07 |     42 |            8 | 683010           |
| S0004    | VYP                                          | 2.76602e+07 |     58 |            9 | 476901           |
| S0011    | ON PREMISE                                   | 2.25496e+07 |     27 |            4 | 835170           |
| P2655    | YAPURA MA HU LIB SP NORTE 11.99%(EXTRA TASA) | 1.84067e+07 |      1 |            5 |      1.84067e+07 |
| P2630    | SALTA SALTA 1200 4% (VYP)                    | 1.51909e+07 |      1 |            1 |      1.51909e+07 |
| P2341    | SALTA CUALQUIER ADO = S/CARGO (CTO VTO)      | 1.41052e+07 |     16 |            1 | 881574           |
| P2658    | SALTA SALTA 1200 MAYORISTAS (EXTRA TASA)     | 1.189e+07   |      1 |            1 |      1.189e+07   |
| B0011    | ON PREMISE                                   | 1.00666e+07 |     32 |            2 | 314583           |

**Top 10 acciones más concentradas (descuento / art)**:

| Acción   | Descripción Acción                           |   descuento |   arts |   desc_per_art |
|:---------|:---------------------------------------------|------------:|-------:|---------------:|
| P2772    | YAPURA SCH 710 MUNDIAL 20%                   | 5.777e+07   |      1 |    5.777e+07   |
| P2773    | GARCIA SCH 710 MUNDIAL 20%                   | 3.1592e+07  |      1 |    3.1592e+07  |
| P2655    | YAPURA MA HU LIB SP NORTE 11.99%(EXTRA TASA) | 1.84067e+07 |      1 |    1.84067e+07 |
| P2630    | SALTA SALTA 1200 4% (VYP)                    | 1.51909e+07 |      1 |    1.51909e+07 |
| P2658    | SALTA SALTA 1200 MAYORISTAS (EXTRA TASA)     | 1.189e+07   |      1 |    1.189e+07   |
| P2366    | YAPURA NORTE LTR 5% (LP 7.9)(VYP) 23320      | 8.16915e+06 |      1 |    8.16915e+06 |
| B0029    | EXTRA TASA                                   | 7.8577e+06  |      1 |    7.8577e+06  |
| P2626    | YAPURA PE SCH 710 MUNDIAL 5%                 | 7.36872e+06 |      1 |    7.36872e+06 |
| P2620    | GARCIA JVG SCH 710 MUNDIAL 5%                | 5.85008e+06 |      1 |    5.85008e+06 |
| P2632    | YAPURA SALTA 1200 4% (VYP)                   | 5.71997e+06 |      1 |    5.71997e+06 |

---

## 10. Recurrencia de clientes

- Promedio de ops por cliente en el período: **5.01**
- Mediana: **4**
- Top 1 cliente: **102 ops**
- Clientes con 1 sola op: **1,589** (15.9%)
- Clientes con 10+ ops: **1,113** (11.2%)

---

## 11. Crecimiento / varianza day-over-day

**Day-over-day % change (descuento)**:

| day        |        descuento |     dod_pct |
|:-----------|-----------------:|------------:|
| 2026-07-02 |      1.32625e+07 |    0.647377 |
| 2026-07-03 |      1.66999e+07 |   25.9187   |
| 2026-07-04 |      1.18093e+07 |  -29.2852   |
| 2026-07-06 |      1.35088e+07 |   14.391    |
| 2026-07-07 |      1.17814e+07 |  -12.7871   |
| 2026-07-08 |      2.03296e+07 |   72.5565   |
| 2026-07-09 | 584859           |  -97.1231   |
| 2026-07-10 |      3.27022e+07 | 5491.47     |
| 2026-07-11 |      2.30972e+07 |  -29.3712   |
| 2026-07-13 |      1.44029e+07 |  -37.6422   |
| 2026-07-14 |      4.26779e+07 |  196.315    |
| 2026-07-15 |      1.60881e+07 |  -62.3033   |
| 2026-07-16 |      2.26859e+07 |   41.0102   |
| 2026-07-17 |      5.86902e+07 |  158.707    |
| 2026-07-18 |      6.03361e+07 |    2.80451  |
| 2026-07-20 |      5.8129e+07  |   -3.65801  |
| 2026-07-21 |      1.11866e+07 |  -80.7555   |

---
