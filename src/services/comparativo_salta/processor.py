"""Pure logic for the SALTA coverage comparison, split by package size (calibre).

Coverage here means DISTINCT CLIENTS WITH BULTOS > 0. It is not additive: a client
buying both 1000CC and 1200CC counts once in the brand total and once in each
calibre row, so the calibre rows never add up to the brand row. Every count is
therefore taken from the client-grain frame, never by summing another count.
"""
import pandas as pd

MARCA_TOTAL = "SALTA (marca, total)"

# Client identity is the composite key — id_cliente alone repeats across sucursales.
_CLIENTE_KEY = ["id_cliente", "id_sucursal"]


def asignar_zona(df: pd.DataFrame, zonas: dict) -> pd.DataFrame:
    """Rename `sucursal` to its virtual zone based on `id_ruta`.

    Unlike ``src.core.zonas.aplicar_zonas_virtuales`` this keeps the client grain:
    that helper drops `id_ruta` and re-aggregates, which would collapse the rows a
    distinct-client count depends on.
    """
    if df.empty or "id_ruta" not in df.columns:
        return df

    out = df.copy()
    for zona, cfg in zonas.items():
        mask = (out["sucursal"] == cfg["sucursal_real"]) & (
            out["id_ruta"].isin(cfg["rutas"])
        )
        out.loc[mask, "sucursal"] = zona
    return out


def _con_venta(df: pd.DataFrame) -> pd.DataFrame:
    """Rows that actually represent a purchase — the coverage universe."""
    if df.empty:
        return df
    return df[df["bultos"] > 0]


def contar_cobertura(df: pd.DataFrame, calibre: str | None = None) -> int:
    """Distinct clients with bultos > 0, optionally restricted to one calibre.

    The brand total is the UNION of the calibre sets, not the count of clients
    whose net across calibres is positive. The two differ by a handful of clients
    per month (3 of 8546 in Jul-2026) whose returns in one calibre cancel their
    purchase in another. The union is the only self-consistent option: a client
    shown in the "SALTA 1200" row must also appear in the brand row.
    """
    d = _con_venta(df)
    if d.empty:
        return 0
    if calibre is not None:
        d = d[d["calibre"] == calibre]
    return int(d.drop_duplicates(subset=_CLIENTE_KEY).shape[0])


def calibres_ordenados(*frames: pd.DataFrame) -> list[str]:
    """Calibres present in any period, ordered by coverage in the first frame.

    Taking the union keeps a calibre that sold last year but not this month from
    silently disappearing from the comparison.
    """
    presentes: set[str] = set()
    for f in frames:
        d = _con_venta(f)
        if not d.empty:
            presentes.update(d["calibre"].unique())
    if not presentes:
        return []

    base = _con_venta(frames[0]) if frames else pd.DataFrame()
    def _peso(c: str) -> int:
        if base.empty:
            return 0
        return int(base[base["calibre"] == c].drop_duplicates(subset=_CLIENTE_KEY).shape[0])

    return sorted(presentes, key=lambda c: (-_peso(c), c))


def construir_resumen(
    actual: pd.DataFrame,
    anterior: pd.DataFrame,
    mmaa: pd.DataFrame,
    etiquetas: dict[str, str],
) -> pd.DataFrame:
    """Coverage table: brand total plus one row per calibre, three periods wide.

    Args:
        actual/anterior/mmaa: client-grain frames for each period.
        etiquetas: column labels, keys 'actual', 'anterior', 'mmaa'.
    """
    col_a, col_p, col_m = etiquetas["actual"], etiquetas["anterior"], etiquetas["mmaa"]
    filas = []

    def _fila(detalle: str, calibre: str | None) -> dict:
        a = contar_cobertura(actual, calibre)
        p = contar_cobertura(anterior, calibre)
        m = contar_cobertura(mmaa, calibre)
        return {
            "Detalle": detalle,
            col_a: a,
            col_p: p,
            "Var. mes ant.": a - p,
            col_m: m,
            "Var. MMAA": a - m,
        }

    filas.append(_fila(MARCA_TOTAL, None))
    for c in calibres_ordenados(actual, anterior, mmaa):
        filas.append(_fila(f"SALTA {c.replace('CC', '')}", c))

    return pd.DataFrame(filas)


def construir_resumen_por_zona(
    actual: pd.DataFrame,
    anterior: pd.DataFrame,
    mmaa: pd.DataFrame,
    etiquetas: dict[str, str],
) -> pd.DataFrame:
    """Same table as `construir_resumen`, broken down by zone."""
    zonas = sorted(set(_con_venta(actual).get("sucursal", pd.Series(dtype=str)).unique()))
    bloques = []
    for zona in zonas:
        sub = construir_resumen(
            actual[actual["sucursal"] == zona],
            anterior[anterior["sucursal"] == zona] if not anterior.empty else anterior,
            mmaa[mmaa["sucursal"] == zona] if not mmaa.empty else mmaa,
            etiquetas,
        )
        sub.insert(0, "Zona", zona)
        bloques.append(sub)

    if not bloques:
        return pd.DataFrame(columns=["Zona", "Detalle"])
    return pd.concat(bloques, ignore_index=True)


def construir_cobertura_mensual(
    df: pd.DataFrame, anio: int, *, forzar_12_meses: bool = False
) -> pd.DataFrame:
    """Coverage month by month, one row per sucursal x sabor x calibre.

    Columns are the twelve months of `anio` plus a yearly column. The yearly
    figure is NOT the sum of the months: it counts each client once no matter how
    many months they bought in, so it always lands below the sum and usually
    close to the largest single month. Same reason the ``TOTAL {sucursal}`` row
    is not the sum of the rows above it — a client buying 473 and 1200 is one
    client for the sucursal.
    """
    # Solo meses con movimiento: en el año en curso los que todavía no pasaron
    # saldrían en 0 y ensucian el cuadro sin aportar nada.
    # `forzar_12_meses` mantiene las doce columnas aunque estén vacías: es lo que
    # permite apilar dos años y que las columnas queden alineadas.
    con_datos = set(df["mes"].dropna().unique()) if "mes" in df.columns else set()
    ultimo = 12 if forzar_12_meses else max(
        (int(m[5:]) for m in con_datos if m.startswith(str(anio))), default=12
    )
    meses = [f"{anio}-{m:02d}" for m in range(1, ultimo + 1)]
    etiquetas = {m: f"{m[5:]}/{str(anio)[2:]}" for m in meses}
    col_anio = f"Año {anio}"

    d = _con_venta(df)
    if d.empty:
        return pd.DataFrame(columns=["Sucursal", "Sabor", "Calibre", *etiquetas.values(), col_anio])

    def _cuenta(sub: pd.DataFrame, mes: str | None) -> int:
        s = sub if mes is None else sub[sub["mes"] == mes]
        return int(s.drop_duplicates(subset=_CLIENTE_KEY).shape[0])

    filas = []
    for sucursal in sorted(d["sucursal"].dropna().unique()):
        bloque = d[d["sucursal"] == sucursal]
        # Orden de lectura del cuadro historico: por sabor, y dentro de cada
        # sabor por tamano de envase creciente (473, 1000, 1200), no por volumen.
        def _orden_calibre(c: str) -> tuple:
            return (0, int(c)) if c.isdigit() else (1, 0)

        combos = sorted(
            bloque.groupby(["sabor", "calibre"]).groups.keys(),
            key=lambda k: (k[0], _orden_calibre(k[1])),
        )
        primera = True
        for sabor, calibre in combos:
            sub = bloque[(bloque["sabor"] == sabor) & (bloque["calibre"] == calibre)]
            filas.append({
                "Sucursal": sucursal if primera else "",
                "Sabor": sabor,
                "Calibre": calibre,
                **{etiquetas[m]: _cuenta(sub, m) for m in meses},
                col_anio: _cuenta(sub, None),
            })
            primera = False
        filas.append({
            "Sucursal": f"TOTAL {sucursal}",
            "Sabor": "",
            "Calibre": "",
            **{etiquetas[m]: _cuenta(bloque, m) for m in meses},
            col_anio: _cuenta(bloque, None),
        })

    filas.append({
        "Sucursal": "TOTAL GENERAL",
        "Sabor": "",
        "Calibre": "",
        **{etiquetas[m]: _cuenta(d, m) for m in meses},
        col_anio: _cuenta(d, None),
    })
    return pd.DataFrame(filas)


def combos_sabor_calibre(frames: dict) -> list[tuple[str, str]]:
    """Pares (sabor, calibre) con cobertura en algun mes, en orden de lectura.

    Orden: sabor alfabetico y, dentro de cada sabor, calibre creciente por tamano
    de envase (473, 1000, 1200), que es como se lee el cuadro — no por volumen.
    """
    presentes: set[tuple[str, str]] = set()
    for df in frames.values():
        d = _con_venta(df)
        if not d.empty:
            presentes.update(map(tuple, d[["sabor", "calibre"]].drop_duplicates().values))

    def _orden(par: tuple[str, str]) -> tuple:
        sabor, calibre = par
        return (sabor, (0, int(calibre)) if calibre.isdigit() else (1, 0))

    return sorted(presentes, key=_orden)


def construir_cobertura_vendedor_bloques(
    frames: dict, bloques: list[dict]
) -> pd.DataFrame:
    """Cobertura por preventista con bloques de columnas definidos a mano.

    Cada bloque es un dict con ``sabor``, ``calibre``, ``meses`` (lista 'YYYY-MM')
    y opcionalmente ``cupo`` y ``grupo``. Un mismo (sabor, calibre) puede repetirse
    en dos bloques con meses distintos — es el caso del incentivo, donde el litro
    negro se mide contra agosto en una campania y contra septiembre en la otra.

    El ``cupo`` es el objetivo TOTAL de la sucursal: se escribe solo en la fila de
    totales y las celdas por vendedor quedan vacias, para repartirlo a mano.
    """
    filas_idx = set()
    for df in frames.values():
        d = _con_venta(df)
        if not d.empty:
            filas_idx.update(
                map(tuple, d[["sucursal", "preventista"]].fillna("(sin asignar)").drop_duplicates().values)
            )
    if not filas_idx:
        return pd.DataFrame()

    def _contar(df, sucursal, preventista, sabor, calibre) -> int:
        if df is None or df.empty:
            return 0
        d = _con_venta(df)
        sel = d[(d["sabor"] == sabor) & (d["calibre"] == calibre)]
        if sucursal is not None:
            sel = sel[
                (sel["sucursal"] == sucursal)
                & (sel["preventista"].fillna("(sin asignar)") == preventista)
            ]
        return int(sel.drop_duplicates(subset=_CLIENTE_KEY).shape[0])

    registros = []
    for sucursal, preventista in sorted(filas_idx):
        fila = {"Sucursal": sucursal, "Vendedor": preventista}
        for i, b in enumerate(bloques):
            for mes in b["meses"]:
                fila[_col_bloque(i, mes)] = _contar(
                    frames.get(mes), sucursal, preventista, b["sabor"], b["calibre"]
                )
            fila[_col_bloque(i, "Cupo")] = None   # se completa mas abajo
        registros.append(fila)

    total = {"Sucursal": "TOTAL GENERAL", "Vendedor": ""}
    for i, b in enumerate(bloques):
        for mes in b["meses"]:
            total[_col_bloque(i, mes)] = _contar(
                frames.get(mes), None, None, b["sabor"], b["calibre"]
            )
        total[_col_bloque(i, "Cupo")] = b.get("cupo")

    frame = pd.DataFrame(registros)

    # Reparto del cupo. La base es el PRIMER mes del bloque (el historico): es el
    # unico completo, y es contra el que se fijo el objetivo. Se reparte una vez y
    # queda escrito en la celda — no es una formula que se recalcule sola.
    for i, b in enumerate(bloques):
        if b.get("cupo") is None:
            continue
        col_hist = _col_bloque(i, b["meses"][0])
        col_cupo = _col_bloque(i, "Cupo")
        base = dict(zip(frame["Vendedor"], frame[col_hist].astype(float)))
        reparto = distribuir_cupo(base, b["cupo"])
        frame[col_cupo] = frame["Vendedor"].map(reparto)

    return pd.concat([frame, pd.DataFrame([total])], ignore_index=True)


def distribuir_cupo(base: dict[str, float], total: float) -> dict[str, int]:
    """Reparte `total` entre las claves de `base`, proporcional a su historia.

    Devuelve enteros que suman EXACTAMENTE `total`: el cupo es una cantidad de
    clientes, no admite decimales, y si la suma no cierra el objetivo global deja
    de ser el que fijo comercial. Se usa el metodo del resto mayor — repartir por
    truncamiento y dar las unidades sobrantes a quien tenga la fraccion mas alta —
    en vez de redondear cada parte por su cuenta, que no garantiza el total.

    Si nadie tiene historia, se reparte parejo: es preferible a dejar todo en cero.
    """
    if not base:
        return {}
    objetivo = int(round(total))
    suma = sum(base.values())

    if suma <= 0:
        piso, resto = divmod(objetivo, len(base))
        claves = sorted(base)
        return {k: piso + (1 if i < resto else 0) for i, k in enumerate(claves)}

    exactos = {k: v / suma * objetivo for k, v in base.items()}
    asignado = {k: int(v) for k, v in exactos.items()}
    faltan = objetivo - sum(asignado.values())

    # Desempate por nombre para que dos corridas den el mismo reparto.
    orden = sorted(exactos, key=lambda k: (-(exactos[k] - int(exactos[k])), k))
    for k in orden[:faltan]:
        asignado[k] += 1
    return asignado


def _col_bloque(indice: int, sufijo: str) -> str:
    """Nombre plano de columna. El indice evita que dos bloques del mismo
    (sabor, calibre) con meses distintos colisionen entre si."""
    return f"b{indice}|{sufijo}"


def construir_cobertura_vendedor(
    frames: dict, meses: list[str], combos: list[tuple[str, str]]
) -> pd.DataFrame:
    """Cobertura por preventista: una fila por vendedor, columnas sabor x calibre x mes.

    Args:
        frames: {'YYYY-MM': frame al grano cliente} — uno por mes pedido.
        meses: los meses, en el orden en que van las columnas.
        combos: pares (sabor, calibre) que definen los bloques de columnas.

    La fila del vendedor es (sucursal, preventista), NO el preventista solo: los
    nombres pueden repetirse entre sucursales y juntarlos mezclaria dos personas
    distintas — la misma razon por la que los ids son compuestos.

    Cada bloque lleva ademas una columna ``Objetivo`` vacia, para completar a mano.
    """
    filas_idx = set()
    for df in frames.values():
        d = _con_venta(df)
        if not d.empty:
            filas_idx.update(
                map(tuple, d[["sucursal", "preventista"]].fillna("(sin asignar)").drop_duplicates().values)
            )
    if not filas_idx:
        return pd.DataFrame()

    registros = []
    for sucursal, preventista in sorted(filas_idx):
        fila = {"Sucursal": sucursal, "Vendedor": preventista}
        for sabor, calibre in combos:
            for mes in meses:
                df = frames.get(mes)
                if df is None or df.empty:
                    fila[_col(sabor, calibre, mes)] = 0
                    continue
                d = _con_venta(df)
                sel = d[
                    (d["sucursal"] == sucursal)
                    & (d["preventista"].fillna("(sin asignar)") == preventista)
                    & (d["sabor"] == sabor)
                    & (d["calibre"] == calibre)
                ]
                fila[_col(sabor, calibre, mes)] = int(
                    sel.drop_duplicates(subset=_CLIENTE_KEY).shape[0]
                )
            # Columna de carga manual: se deja vacia a proposito, no en 0, para
            # que se distinga "objetivo sin definir" de "objetivo cero".
            fila[_col(sabor, calibre, "Objetivo")] = None
        registros.append(fila)

    frame = pd.DataFrame(registros)

    # Fila de totales: cobertura de TODA la operacion, no la suma de los
    # vendedores — un cliente atendido por dos rutas contaria dos veces.
    total = {"Sucursal": "TOTAL GENERAL", "Vendedor": ""}
    for sabor, calibre in combos:
        for mes in meses:
            df = frames.get(mes)
            if df is None or df.empty:
                total[_col(sabor, calibre, mes)] = 0
                continue
            d = _con_venta(df)
            sel = d[(d["sabor"] == sabor) & (d["calibre"] == calibre)]
            total[_col(sabor, calibre, mes)] = int(
                sel.drop_duplicates(subset=_CLIENTE_KEY).shape[0]
            )
        total[_col(sabor, calibre, "Objetivo")] = None
    return pd.concat([frame, pd.DataFrame([total])], ignore_index=True)


def _col(sabor: str, calibre: str, mes: str) -> str:
    """Nombre plano de columna; el Excel lo abre despues en 3 niveles."""
    return f"{sabor}|{calibre}|{mes}"


def construir_detalle_clientes(
    actual: pd.DataFrame, anterior: pd.DataFrame, calibres: list[str]
) -> pd.DataFrame:
    """One row per client, one column pair (actual / previous) per calibre.

    Clients that bought in either period are kept, so a client that dropped to
    zero this month is still visible — that is the point of the sheet.
    """
    if actual.empty and anterior.empty:
        return pd.DataFrame()

    ident = ["id_cliente", "id_sucursal", "sucursal", "razon_social", "fantasia",
             "preventista", "id_ruta"]
    base = (
        pd.concat([actual[ident], anterior[ident]], ignore_index=True)
        .drop_duplicates(subset=_CLIENTE_KEY)
        .sort_values(["sucursal", "preventista", "razon_social"], na_position="last")
        .reset_index(drop=True)
    )

    for calibre in calibres:
        for df, sufijo in ((actual, "actual"), (anterior, "anterior")):
            serie = (
                df[df["calibre"] == calibre]
                .groupby(_CLIENTE_KEY, as_index=False)["bultos"].sum()
                .rename(columns={"bultos": f"{calibre}_{sufijo}"})
            )
            base = base.merge(serie, on=_CLIENTE_KEY, how="left")

    valor_cols = [c for c in base.columns if c.endswith(("_actual", "_anterior"))]
    base[valor_cols] = base[valor_cols].fillna(0.0)
    return base.drop(columns=["id_cliente", "id_sucursal"])
