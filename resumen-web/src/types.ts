// JSON contract types — mirrors POST /resumen-mensual/datos response

export interface InfoDias {
  'Dias Habiles': number
  'Dias Transcurridos': number
  'Dias Faltantes': number
}

export interface Meta {
  fecha_desde: string
  fecha_hasta: string
  col_n1: string
  col_n2: string
  info_dias: InfoDias
  con_objetivo: boolean
}

export interface Row {
  Sucursal: string
  col_n2: number | null
  col_n1: number | null
  'Total Ventas': number | null
  Tendencia: number | null
  MMAA: number | null
  MA: number | null
  Objetivo: number | null
  'Tend vs Obj (%)': number | null
  is_subtotal: boolean
}

export interface Section {
  label: string
  rows: Row[]
}

export interface Sheet {
  generico: string
  note: string | null
  sin_prvta?: boolean
  sections: Section[]
}

export interface DatosResponse {
  meta: Meta
  sheets: Sheet[]
}

// Subtotal values keyed by canonical column names
export interface SubtotalSet {
  'SUBTOTAL CASA CENTRAL': SubtotalValues
  'SUCURSALES SIN DIRECTA': SubtotalValues
  'TOTAL SIN SMK': SubtotalValues
}

export interface SubtotalValues {
  col_n2: number | null
  col_n1: number | null
  'Total Ventas': number | null
  Tendencia: number | null
  MMAA: number | null
  MA: number | null
  Objetivo: number | null
  'Tend vs Obj (%)': number | null
}

// Request params
export interface DatosRequest {
  fecha_desde: string
  fecha_hasta: string
  genericos?: string[]
  con_objetivo?: boolean
  marca_splits?: Record<string, string[]>
  cupos_manuales?: Record<string, Record<string, number>>
  genericos_sin_prvta?: string[]
}
