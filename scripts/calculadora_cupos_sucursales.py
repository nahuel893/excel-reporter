"""Calculadora de cupos del INTERIOR: se tipea el cupo por sucursal y categoria,
y el objetivo por preventista y por ruta sale con formulas de Excel.

Invierte el flujo que habia hasta agosto 2026. Antes CCU pasaba el objetivo ya
abierto por preventista y `apertura_rutas_sucursales.py` lo bajaba a ruta. Ahora
el objetivo llega por SUCURSAL y la apertura a preventista tambien la hace este
libro — en vivo, con formulas, para poder tantear un cupo y ver el reparto sin
volver a correr nada.

Reglas de negocio (las mismas que el script de apertura)
--------------------------------------------------------
- La ruta sale de `dim_cliente.id_ruta_fv1`, NUNCA del vendedor que facturo en
  `fact_ventas`: ese es quien emitio la factura, no quien persigue el objetivo.
- La clave es COMPUESTA `(id_sucursal, id_ruta)`. `id_ruta` se reusa entre
  sucursales; keyear por ruta sola colapsa la ruta 1 de Oran con la de Metan.
- El reparto es en cascada: SUCURSAL -> PREVENTISTA -> RUTA. La ruta reparte el
  objetivo de SU preventista, no el de la sucursal, asi la suma de las rutas de
  un preventista da exactamente su objetivo.
- Las ventas negativas (notas de credito) pesan CERO, nunca restan cupo.
- Si nadie tiene historia en una sucursal-categoria, el reparto es parejo.
- NO se redondea en ninguna formula. La suma de las partes da exacto el cupo
  tipeado; los decimales se esconden con formato de celda, no con ROUND.

Categorias (cambio de SEPTIEMBRE 2026)
--------------------------------------
SALTA, SCHNEIDER y NORTE pasan a ser marca individual en TODAS las sucursales.
Antes la propia de la provincia iba individual y las otras dos caian en
MULTICERVEZAS (NORTE individual en Jujuy, SALTA individual en Salta). Eso ya no
existe: las tres tienen columna propia y MULTICERVEZAS queda con el resto.

MULTI CCU se tipea como UN solo cupo por sucursal y se abre en sus tres
genericos por historia, como venia. Casa Central y Guemes los cargan abiertos y
si el grano no coincide bronze recibe dos granos distintos.
"""
from __future__ import annotations

import sys
import unicodedata
from datetime import date
from pathlib import Path

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.core.data_loader import DataLoader  # noqa: E402
from src.core.output_paths import service_output_dir  # noqa: E402

MESES_HISTORIA = 3
# Casa Central (1) y Guemes (16) tienen su propio archivo de cupo. Si entraran
# aca tambien, el mismo objetivo se cargaria dos veces en la base.
SUCURSALES_EXCLUIDAS = {1, 16}
# No es ruta de preventa: absorberia cupo que nadie persigue.
SIN_CUPO = {"DIRECTA", "RUIZ MARCELO", "VENDEDOR CHOPERAS"}

# --- Categorias -------------------------------------------------------------
MULTICERV = "MULTICERVEZAS"
IMPORTADAS = "IMPORTADAS"
MULTICCU = "MULTI CCU"
GEN_MULTICCU = ["VINOS CCU", "SIDRAS Y LICORES", "PERNOD RICARD"]
MARCAS_IMPORTADAS = {"BLUE MOON", "KUNSTMAN", "KUNSTMANN"}
CERVEZA_INDIVIDUALES = ["SALTA", "SCHNEIDER", "NORTE", "HEINEKEN", "IMPERIAL", "MILLER"]
# El orden manda: es el de las filas del libro y el de los cuadros.
CERVEZA_CATS = [*CERVEZA_INDIVIDUALES, MULTICERV, IMPORTADAS]
CATEGORIAS = [*CERVEZA_CATS, "AGUAS DANONE", MULTICCU]

# Colores
AZUL = "1F4E78"
AMARILLO = "FFFF00"      # pestana de la hoja que se carga en la base
VERDE = "C6EFCE"         # celdas que se tipean a mano
GRIS = "F2F2F2"
GRIS_BANDA = "808080"    # banda de los bloques de solo lectura
VERDE_BANDA = "375623"   # banda del bloque que se tipea
NARANJA = "FCE4D6"       # TOTAL GENERAL
BORDE = Border(*[Side(style="thin", color="BFBFBF")] * 4)
# Sin decimales: son bultos, y el libro se lee de un pantallazo. El VALOR
# sigue con todos sus decimales — esto es formato de celda, no ROUND, asi la
# suma de las partes cierra exacto contra el cupo tipeado.
FMT = "#,##0"
FMT_PCT = "0.0%"


def _txt(v) -> str:
    if v is None or (isinstance(v, float) and v != v):
        return ""
    s = unicodedata.normalize("NFKD", str(v).strip().upper())
    return "".join(c for c in s if not unicodedata.combining(c))


def meses_atras(hoy: date, n: int) -> list[str]:
    """Los n meses cerrados anteriores a `hoy`, mas viejo primero."""
    y, m = hoy.year, hoy.month
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y}-{m:02d}")
    return list(reversed(out))


def clasificar(generico, marca) -> str | None:
    """marca de gold -> categoria del libro. None = fuera del universo."""
    g, m = _txt(generico), _txt(marca)
    if g == "CERVEZAS":
        if m in CERVEZA_INDIVIDUALES:
            return m
        if m in MARCAS_IMPORTADAS:
            return IMPORTADAS
        return MULTICERV
    if g == "AGUAS DANONE":
        return "AGUAS DANONE"
    if g in GEN_MULTICCU:
        return g          # se agrupa en MULTI CCU, pero guarda su propia historia
    return None


def categoria_padre(cat: str) -> str:
    return MULTICCU if cat in GEN_MULTICCU else cat


def cargar_rutas(dl: DataLoader):
    """(sucursal, preventista) -> [(id_sucursal, id_ruta, des_ruta)]."""
    df = dl.execute_query("""
        SELECT ds.descripcion AS sucursal, dc.id_sucursal,
               dc.id_ruta_fv1 AS ruta,
               MIN(dc.des_ruta_fv1) AS des_ruta,
               UPPER(TRIM(dc.des_personal_fv1)) AS preventista
        FROM gold.dim_cliente dc
        JOIN gold.dim_sucursal ds ON ds.id_sucursal = dc.id_sucursal
        WHERE COALESCE(dc.anulado, false) = false
          AND dc.id_sucursal NOT IN :excl
          AND dc.id_ruta_fv1 IS NOT NULL AND dc.des_personal_fv1 IS NOT NULL
        GROUP BY 1, 2, 3, 5
    """, {"excl": tuple(SUCURSALES_EXCLUIDAS)})
    rutas: dict[tuple[str, str], list] = {}
    for f in df.itertuples(index=False):
        prev = _txt(f.preventista)
        if prev in SIN_CUPO:
            continue
        rutas.setdefault((_txt(f.sucursal), prev), []).append(
            (int(f.id_sucursal), int(f.ruta),
             _txt(f.des_ruta) or f"RUTA {int(f.ruta)}"))
    for v in rutas.values():
        v.sort()
    return rutas


def cargar_historia(dl: DataLoader, meses: list[str]):
    """Ventas por (id_sucursal, id_ruta, categoria, mes). Ruta de dim_cliente."""
    desde = f"{meses[0]}-01"
    y, m = int(meses[-1][:4]), int(meses[-1][5:])
    hasta = f"{y + 1}-01-01" if m == 12 else f"{y}-{m + 1:02d}-01"
    df = dl.execute_query("""
        SELECT dc.id_sucursal, dc.id_ruta_fv1 AS ruta, da.generico, da.marca,
               to_char(fv.fecha_comprobante, 'YYYY-MM') AS mes,
               SUM(fv.cantidades_total) AS qty
        FROM gold.fact_ventas fv
        JOIN gold.dim_cliente dc ON dc.id_cliente = fv.id_cliente
                                AND dc.id_sucursal = fv.id_sucursal
        JOIN gold.dim_articulo da ON da.id_articulo = fv.id_articulo
        WHERE fv.anulado = false
          AND dc.id_sucursal NOT IN :excl
          AND fv.fecha_comprobante >= :d AND fv.fecha_comprobante < :h
          AND dc.id_ruta_fv1 IS NOT NULL
        GROUP BY 1, 2, 3, 4, 5
    """, {"excl": tuple(SUCURSALES_EXCLUIDAS), "d": desde, "h": hasta})
    hist: dict[tuple[int, int, str, str], float] = {}
    for f in df.itertuples(index=False):
        cat = clasificar(f.generico, f.marca)
        if cat is None:
            continue
        k = (int(f.id_sucursal), int(f.ruta), cat, f.mes)
        hist[k] = hist.get(k, 0.0) + float(f.qty or 0)
    return hist


def _encabezado(ws, headers: list[str], anchos: list[int]):
    ws.append(headers)
    for c in ws[1]:
        c.fill = PatternFill("solid", fgColor=AZUL)
        c.font = Font(bold=True, color="FFFFFF")
        c.alignment = Alignment(horizontal="center", wrap_text=True)
    for i, a in enumerate(anchos, start=1):
        ws.column_dimensions[get_column_letter(i)].width = a
    ws.freeze_panes = "A2"


def _cerrar(ws, primera_num: int, filas_total: list[int] = (),
            cols_pct: tuple[int, ...] = ()):
    """Bordes, formato numerico y pintado de las filas de total.

    `cols_pct` va aparte porque este barrido pisa cualquier `number_format`
    puesto celda por celda antes: sin esto las columnas de PESO y % PART
    quedaban con formato de bultos y se leian como 0.
    """
    for fila in ws.iter_rows(min_row=2, max_row=ws.max_row):
        for i, c in enumerate(fila, start=1):
            c.border = BORDE
            if i in cols_pct:
                c.number_format = FMT_PCT
            elif i >= primera_num:
                c.number_format = FMT
    for r in filas_total:
        for c in ws[r]:
            c.font = Font(bold=True)
            c.fill = PatternFill("solid", fgColor=NARANJA)


def construir(rutas, hist, meses):
    wb = Workbook()

    # ------------------------------------------------------------------ Cupos
    # Una fila por sucursal-categoria. Es mas largo que un grid, pero se tipea
    # bajando y las otras hojas apuntan a UN solo rango con SUMIFS.
    ws = wb.active
    ws.title = "Cupos"
    ws.sheet_properties.tabColor = VERDE

    sucursales = sorted({s for s, _ in rutas})
    # (sucursal, categoria, mes) -> bultos, ya agrupado al padre
    venta_suc: dict[tuple[str, str, str], float] = {}
    for (suc, prev), rs in rutas.items():
        for id_suc, ruta, _ in rs:
            for cat in CATEGORIAS + GEN_MULTICCU:
                for mes in meses:
                    q = hist.get((id_suc, ruta, cat, mes), 0.0)
                    if q:
                        k = (suc, categoria_padre(cat), mes)
                        venta_suc[k] = venta_suc.get(k, 0.0) + q

    # Layout: por cada categoria un bloque de 6 columnas.
    #   [mes1 mes2 mes3]  TOTAL 3M   CUPO   % s/3M
    #    \____ agrupadas ____/        verde
    # Los meses van en un grupo de outline: se abren para ver la tendencia y se
    # cierran para tipear sin ruido.
    n_mes = len(meses)
    ANCHO_CAT = 6
    F_CLAVE, F_BANDA, F_HDR = 1, 2, 3      # clave oculta, banda, encabezados
    F0 = 4                                  # primera sucursal
    F1 = F0 + len(sucursales) - 1
    F_TOT = F1 + 1

    def col_cat(i: int) -> int:
        """Primera columna del bloque de la categoria `i`."""
        return 2 + i * ANCHO_CAT

    ws.cell(F_CLAVE, 1, "(clave interna — no tocar)").font = Font(italic=True, size=8)
    ws.cell(F_BANDA, 1, "")
    ws.cell(F_HDR, 1, "SUCURSAL")
    for i, cat in enumerate(CATEGORIAS):
        b = col_cat(i)
        # La clave va en la MISMA columna que el CUPO: es contra esta fila que
        # las otras hojas hacen MATCH. Sin ella habria que adivinar el offset.
        ws.cell(F_CLAVE, b + 4, cat)
        cel = ws.cell(F_BANDA, b, cat)
        ws.merge_cells(start_row=F_BANDA, start_column=b,
                       end_row=F_BANDA, end_column=b + ANCHO_CAT - 1)
        cel.font = Font(bold=True, color="FFFFFF", size=11)
        cel.alignment = Alignment(horizontal="center")
        for c in range(b, b + ANCHO_CAT):
            ws.cell(F_BANDA, c).fill = PatternFill("solid", fgColor=VERDE_BANDA)
        for j, h in enumerate([*meses, "TOTAL 3M", "CUPO", "% s/3M"]):
            hc = ws.cell(F_HDR, b + j, h)
            hc.fill = PatternFill("solid", fgColor=AZUL)
            hc.font = Font(bold=True, color="FFFFFF", size=9)
            hc.alignment = Alignment(horizontal="center", wrap_text=True)
    hc = ws.cell(F_HDR, 1)
    hc.fill = PatternFill("solid", fgColor=AZUL)
    hc.font = Font(bold=True, color="FFFFFF")
    hc.alignment = Alignment(horizontal="center")

    for k, suc in enumerate(sucursales):
        r = F0 + k
        ws.cell(r, 1, suc)
        for i, cat in enumerate(CATEGORIAS):
            b = col_cat(i)
            for j, mes in enumerate(meses):
                ws.cell(r, b + j, venta_suc.get((suc, cat, mes), 0.0))
            L0, L1 = get_column_letter(b), get_column_letter(b + n_mes - 1)
            Lt, Lc = get_column_letter(b + 3), get_column_letter(b + 4)
            # Las notas de credito no restan cupo: el total que pondera nunca
            # baja de cero, aunque un mes suelto si pueda ser negativo.
            ws.cell(r, b + 3, f"=MAX(0,SUM({L0}{r}:{L1}{r}))")
            ws.cell(r, b + 4).fill = PatternFill("solid", fgColor=VERDE)
            ws.cell(r, b + 5, f'=IFERROR({Lc}{r}/{Lt}{r},"")')

    ws.cell(F_TOT, 1, "TOTAL")
    for i in range(len(CATEGORIAS)):
        b = col_cat(i)
        for j in range(ANCHO_CAT - 1):          # el % no se suma
            L = get_column_letter(b + j)
            ws.cell(F_TOT, b + j, f"=SUM({L}{F0}:{L}{F1})")
        Lt, Lc = get_column_letter(b + 3), get_column_letter(b + 4)
        # El total del ratio es el ratio de los totales: sumar porcentajes no
        # significa nada.
        ws.cell(F_TOT, b + 5, f'=IFERROR({Lc}{F_TOT}/{Lt}{F_TOT},"")')

    ancho_total = 1 + len(CATEGORIAS) * ANCHO_CAT
    for fila in ws.iter_rows(min_row=F0, max_row=F_TOT, min_col=1, max_col=ancho_total):
        for c in fila:
            c.border = BORDE
    for i in range(len(CATEGORIAS)):
        b = col_cat(i)
        for r in range(F0, F_TOT + 1):
            for j in range(ANCHO_CAT - 1):
                ws.cell(r, b + j).number_format = FMT
            ws.cell(r, b + 5).number_format = FMT_PCT
    for c in ws[F_TOT]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor=NARANJA)

    ws.row_dimensions[F_CLAVE].hidden = True
    ws.column_dimensions["A"].width = 30
    for i in range(len(CATEGORIAS)):
        b = col_cat(i)
        for j in range(ANCHO_CAT):
            ws.column_dimensions[get_column_letter(b + j)].width = 11 if j < 3 else 12
        # Los tres meses, agrupados y abiertos: se cierran desde el signo de
        # arriba cuando estorban.
        ws.column_dimensions.group(get_column_letter(b),
                                   get_column_letter(b + n_mes - 1),
                                   outline_level=1, hidden=False)
    ws.freeze_panes = "B4"

    # Coordenadas para el INDEX/MATCH de las otras hojas.
    c_ini, c_fin = get_column_letter(2), get_column_letter(ancho_total)
    rango_cupo = (f"Cupos!${c_ini}${F0}:${c_fin}${F1}",     # la matriz entera
                  f"Cupos!$A${F0}:$A${F1}",                  # sucursales (filas)
                  f"Cupos!${c_ini}${F_CLAVE}:${c_fin}${F_CLAVE}")  # clave (columnas)
    total_cupos = len(sucursales) * len(CATEGORIAS)

    # ------------------------------------------------------ Cupo Preventista
    wsp = wb.create_sheet("Cupo Preventista")
    # La venta va ABIERTA POR MES, no solo el acumulado: sirve para ver si un
    # preventista viene cayendo o creciendo antes de aceptar el reparto.
    _encabezado(wsp, ["SUCURSAL", "PREVENTISTA", "CATEGORIA", *meses,
                      "TOTAL 3M", "PESO", "OBJETIVO"],
                [30, 26, 16, 12, 12, 12, 13, 10, 14])
    c_m0 = get_column_letter(4)                  # primer mes
    c_m1 = get_column_letter(3 + n_mes)          # ultimo mes
    c_tot = get_column_letter(4 + n_mes)         # TOTAL 3M
    c_peso = get_column_letter(5 + n_mes)
    c_obj = get_column_letter(6 + n_mes)
    fila_prev: dict[tuple[str, str, str], int] = {}
    r = 2
    for (suc, prev) in sorted(rutas):
        for cat in CATEGORIAS:
            por_mes = {mes: 0.0 for mes in meses}
            for id_suc, ruta, _ in rutas[(suc, prev)]:
                for c in (GEN_MULTICCU if cat == MULTICCU else [cat]):
                    for mes in meses:
                        por_mes[mes] += hist.get((id_suc, ruta, c, mes), 0.0)
            wsp.cell(r, 1, suc)
            wsp.cell(r, 2, prev)
            wsp.cell(r, 3, cat)
            for i, mes in enumerate(meses):
                wsp.cell(r, 4 + i, por_mes[mes])
            # Las notas de credito no restan cupo: el peso arranca en cero. Un
            # mes puede quedar negativo, el TOTAL que pondera nunca.
            wsp.cell(r, 4 + n_mes, f"=MAX(0,SUM({c_m0}{r}:{c_m1}{r}))")
            base = f'SUMIFS(${c_tot}:${c_tot},$A:$A,$A{r},$C:$C,$C{r})'
            wsp.cell(r, 5 + n_mes, f'=IFERROR(${c_tot}{r}/{base},0)')
            # La hoja Cupos es una matriz: la celda se ubica cruzando sucursal
            # (filas) con categoria (columnas), no con SUMIFS sobre una columna.
            cupo_ref = (f"IFERROR(INDEX({rango_cupo[0]},"
                        f"MATCH($A{r},{rango_cupo[1]},0),"
                        f"MATCH($C{r},{rango_cupo[2]},0)),0)")
            # Sin historia en toda la sucursal-categoria, reparto parejo.
            wsp.cell(r, 6 + n_mes,
                     f'=IF({base}=0,'
                     f'IFERROR({cupo_ref}/COUNTIFS($A:$A,$A{r},$C:$C,$C{r}),0),'
                     f'${c_peso}{r}*{cupo_ref})')
            fila_prev[(suc, prev, cat)] = r
            r += 1
    wsp.cell(r, 1, "TOTAL GENERAL")
    for col in (*range(4, 4 + n_mes), 4 + n_mes, 6 + n_mes):
        L = get_column_letter(col)
        wsp.cell(r, col, f"=SUM({L}2:{L}{r - 1})")
    _cerrar(wsp, primera_num=4, filas_total=[r], cols_pct=(5 + n_mes,))
    wsp.auto_filter.ref = f"A1:{c_obj}{r - 1}"

    # ------------------------------------------------------------- Cupo Ruta
    wsr = wb.create_sheet("Cupo Ruta")
    # Tambien abierta por mes, igual que la de preventista.
    _encabezado(wsr, ["SUCURSAL", "PREVENTISTA", "CÓDIGO", "RUTA", "GRUPO",
                      "CATEGORIA", *meses, "TOTAL 3M", "PESO", "OBJETIVO"],
                [30, 26, 9, 22, 18, 16, 12, 12, 12, 13, 10, 14])
    r_m0 = get_column_letter(7)                  # primer mes
    r_m1 = get_column_letter(6 + n_mes)          # ultimo mes
    r_tot = get_column_letter(7 + n_mes)         # TOTAL 3M
    r_peso = get_column_letter(8 + n_mes)
    r_obj = get_column_letter(9 + n_mes)
    col_obj_ruta = 9 + n_mes
    filas_ruta: list[tuple[int, int, int, str, str, str]] = []
    r = 2
    for (suc, prev) in sorted(rutas):
        for id_suc, ruta, des_ruta in rutas[(suc, prev)]:
            for cat in CATEGORIAS:
                # MULTI CCU baja abierto en sus tres genericos; el resto va uno a uno.
                for gen in (GEN_MULTICCU if cat == MULTICCU else [cat]):
                    wsr.cell(r, 1, suc)
                    wsr.cell(r, 2, prev)
                    wsr.cell(r, 3, ruta)
                    wsr.cell(r, 4, des_ruta)
                    wsr.cell(r, 5, gen)
                    wsr.cell(r, 6, cat)
                    for i, mes in enumerate(meses):
                        wsr.cell(r, 7 + i, hist.get((id_suc, ruta, gen, mes), 0.0))
                    wsr.cell(r, 7 + n_mes, f"=MAX(0,SUM({r_m0}{r}:{r_m1}{r}))")
                    # El peso es dentro del PREVENTISTA, no de la sucursal: asi la
                    # suma de sus rutas da exacto su objetivo.
                    base = (f'SUMIFS(${r_tot}:${r_tot},$A:$A,$A{r},'
                            f'$B:$B,$B{r},$F:$F,$F{r})')
                    wsr.cell(r, 8 + n_mes, f'=IFERROR(${r_tot}{r}/{base},0)')
                    obj = (f"SUMIFS('Cupo Preventista'!${c_obj}:${c_obj},"
                           f"'Cupo Preventista'!$A:$A,$A{r},"
                           f"'Cupo Preventista'!$B:$B,$B{r},"
                           f"'Cupo Preventista'!$C:$C,$F{r})")
                    wsr.cell(r, col_obj_ruta,
                             f'=IF({base}=0,'
                             f'IFERROR({obj}/COUNTIFS($A:$A,$A{r},$B:$B,$B{r},$F:$F,$F{r}),0),'
                             f'${r_peso}{r}*{obj})')
                    filas_ruta.append((r, id_suc, ruta, des_ruta, gen, cat))
                    r += 1
    wsr.cell(r, 1, "TOTAL GENERAL")
    for col in (*range(7, 7 + n_mes), 7 + n_mes, col_obj_ruta):
        L = get_column_letter(col)
        wsr.cell(r, col, f"=SUM({L}2:{L}{r - 1})")
    _cerrar(wsr, primera_num=7, filas_total=[r], cols_pct=(8 + n_mes,))
    wsr.auto_filter.ref = f"A1:{r_obj}{r - 1}"

    # -------------------------------------------------- Base Pivot SUCURSALES
    # La hoja que carga el ETL. GRUPO = CATEGORIA = la etiqueta, salvo los tres
    # genericos de MULTI CCU, que llevan CATEGORIA=MULTICCU para poder agruparlos.
    # CERVEZAS va como DETALLE y por lo tanto SE CARGA: en gold es el TOTAL y
    # convive con sus marcas.
    wsb = wb.create_sheet("Base Pivot SUCURSALES")
    wsb.sheet_properties.tabColor = AMARILLO
    _encabezado(wsb, ["ZONA", "PREVENTISTA", "CÓDIGO", "RUTA", "NIVEL", "GRUPO",
                      "CATEGORIA", "CUPO"], [30, 26, 9, 22, 10, 18, 18, 14])
    por_ruta: dict[tuple[int, int], list] = {}
    for fr, id_suc, ruta, des_ruta, gen, cat in filas_ruta:
        por_ruta.setdefault((id_suc, ruta), []).append((fr, des_ruta, gen, cat))
    zona = {}
    prevs = {}
    for (suc, prev), rs in rutas.items():
        for id_suc, ruta, _ in rs:
            zona[(id_suc, ruta)] = f"{id_suc} - {suc}"
            prevs[(id_suc, ruta)] = prev
    r = 2
    for clave in sorted(por_ruta):
        items = por_ruta[clave]
        z, prev = zona[clave], prevs[clave]
        des_ruta = items[0][1]
        refs = {gen: fr for fr, _, gen, _ in items}
        # CERVEZAS: el total, suma de sus ocho.
        suma = "+".join(f"'Cupo Ruta'!${r_obj}${refs[c]}" for c in CERVEZA_CATS if c in refs)
        wsb.append([z, prev, clave[1], des_ruta, "DETALLE", "CERVEZAS", "CERVEZAS",
                    f"={suma}" if suma else 0])
        r += 1
        for cat in CERVEZA_CATS:
            if cat in refs:
                wsb.append([z, prev, clave[1], des_ruta, "DETALLE", cat, cat,
                            f"='Cupo Ruta'!${r_obj}${refs[cat]}"])
                r += 1
        if "AGUAS DANONE" in refs:
            wsb.append([z, prev, clave[1], des_ruta, "DETALLE", "AGUAS DANONE",
                        "AGUAS DANONE", f"='Cupo Ruta'!${r_obj}${refs['AGUAS DANONE']}"])
            r += 1
        suma_m = "+".join(f"'Cupo Ruta'!${r_obj}${refs[g]}" for g in GEN_MULTICCU if g in refs)
        if suma_m:
            wsb.append([z, prev, clave[1], des_ruta, "AGREGADO", "TOTAL MULTICCU",
                        "TOTAL MULTICCU", f"={suma_m}"])
            r += 1
            for gen in GEN_MULTICCU:
                if gen in refs:
                    wsb.append([z, prev, clave[1], des_ruta, "DETALLE", gen,
                                "MULTICCU", f"='Cupo Ruta'!${r_obj}${refs[gen]}"])
                    r += 1
    _cerrar(wsb, primera_num=8)
    wsb.auto_filter.ref = f"A1:H{r - 1}"

    return wb, total_cupos, len(filas_ruta)


def main() -> int:
    meses = meses_atras(date.today(), MESES_HISTORIA)
    dl = DataLoader()
    rutas = cargar_rutas(dl)
    hist = cargar_historia(dl, meses)

    sucursales = sorted({s for s, _ in rutas})
    print(f"Historia: {', '.join(meses)}")
    print(f"{len(sucursales)} sucursales | {len(rutas)} preventistas | "
          f"{sum(len(v) for v in rutas.values())} rutas")

    wb, filas_cupos, filas_ruta = construir(rutas, hist, meses)

    # El archivo vive en la carpeta del mes del CUPO (el que se esta armando),
    # no en la del ultimo mes de historia.
    hoy = date.today()
    periodo = f"{hoy.year}-{hoy.month:02d}"
    salida = service_output_dir("cupos", f"{periodo}-01", "month") / \
        f"CALCULADORA CUPOS SUCURSALES - {periodo}.xlsx"
    salida.parent.mkdir(parents=True, exist_ok=True)
    if salida.exists() and "--force" not in sys.argv:
        print(f"\nYa existe y NO se sobrescribe:\n  {salida}\n\nCorre con --force.")
        return 1
    wb.save(salida)
    print(f"\nGuardado: {salida}")
    print(f"  Cupos             {filas_cupos} celdas para tipear (matriz)")
    print(f"  Cupo Preventista  {len(rutas) * len(CATEGORIAS)} filas")
    print(f"  Cupo Ruta         {filas_ruta} filas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
