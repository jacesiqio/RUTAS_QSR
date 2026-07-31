# datos.py
import os
import sqlite3
import pandas as pd
from datetime import datetime

def inicializar_base_datos():
    """Crea y actualiza la estructura de la base de datos limpia de referencias obsoletas."""
    os.makedirs("data", exist_ok=True)
    
    conn = sqlite3.connect("data/rutas_qsr.db")
    cursor = conn.cursor()
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sucursales (
        id_sucursal TEXT PRIMARY KEY,
        sucursal_nombre TEXT,
        cliente_marca TEXT,
        latitud REAL,
        longitud REAL,
        estado TEXT,
        zona_localidad TEXT,
        direccion_completa TEXT,
        estatus_visita TEXT DEFAULT 'PENDIENTE',
        fecha_ultima_visita TEXT,
        tipo_visita TEXT DEFAULT 'STANDARD'
    )
    """)
    conn.commit()
    conn.close()

def importar_maestro_sucursales(archivo_excel, nombre_archivo):
    """Importa la base de datos, normaliza campos a minúsculas y procesa la carga incremental."""
    if nombre_archivo.lower().endswith('.csv'):
        df = pd.read_csv(archivo_excel)
    else:
        df = pd.read_excel(archivo_excel)
    
    df.columns = df.columns.str.strip().str.lower()
    
    mapeo_columnas = {
        'id_sucursal': 'id_sucursal', 'sucursal': 'sucursal_nombre', 'sucursal_nombre': 'sucursal_nombre',
        'cadena': 'cliente_marca', 'franquicia': 'cliente_marca', 'cliente_marca': 'cliente_marca',
        'latitud': 'latitud', 'longitud': 'longitud', 'estado': 'estado',
        'localidad': 'zona_localidad', 'zona_localidad': 'zona_localidad',
        'direccion_completa': 'direccion_completa', 'estatus_visita': 'estatus_visita', 'tipo_visita': 'tipo_visita'
    }
    
    df_renombrado = pd.DataFrame()
    for col_orig, col_dest in mapeo_columnas.items():
        if col_orig in df.columns and col_dest not in df_renombrado.columns:
            df_renombrado[col_dest] = df[col_orig]
            
    columnas_esperadas = ['id_sucursal', 'sucursal_nombre', 'cliente_marca', 'latitud', 'longitud', 'estado', 'zona_localidad', 'direccion_completa', 'estatus_visita', 'fecha_ultima_visita', 'tipo_visita']
    
    for col in columnas_esperadas:
        if col not in df_renombrado.columns:
            df_renombrado[col] = None
            
    df_renombrado['latitud'] = pd.to_numeric(df_renombrado['latitud'], errors='coerce')
    df_renombrado['longitud'] = pd.to_numeric(df_renombrado['longitud'], errors='coerce')
    df_renombrado['estatus_visita'] = df_renombrado['estatus_visita'].fillna('PENDIENTE')
    df_renombrado['tipo_visita'] = df_renombrado['tipo_visita'].fillna('STANDARD')
    
    conn = sqlite3.connect("data/rutas_qsr.db")
    df_renombrado.to_sql("temp_import", conn, if_exists="replace", index=False)
    
    cursor = conn.cursor()
    cursor.execute("""
    INSERT OR REPLACE INTO sucursales (
        id_sucursal, sucursal_nombre, cliente_marca, latitud, longitud, 
        estado, zona_localidad, direccion_completa, estatus_visita, fecha_ultima_visita, tipo_visita
    )
    SELECT 
        t.id_sucursal, t.sucursal_nombre, t.cliente_marca, t.latitud, t.longitud,
        t.estado, t.zona_localidad, t.direccion_completa,
        COALESCE((SELECT estatus_visita FROM sucursales WHERE id_sucursal = t.id_sucursal), t.estatus_visita, 'PENDIENTE'),
        COALESCE((SELECT fecha_ultima_visita FROM sucursales WHERE id_sucursal = t.id_sucursal), t.fecha_ultima_visita, NULL),
        COALESCE(t.tipo_visita, 'STANDARD')
    FROM temp_import t
    WHERE t.id_sucursal IS NOT NULL
    """)
    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM sucursales")
    total_filas = cursor.fetchone()[0]
    conn.close()
    
    return total_filas

def actualizar_estatus_sucursales(lista_ids, nuevo_estatus):
    if not lista_ids: return
    conn = sqlite3.connect("data/rutas_qsr.db")
    cursor = conn.cursor()
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    placeholders = ','.join(['?'] * len(lista_ids))
    cursor.execute(f"UPDATE sucursales SET estatus_visita = ?, fecha_ultima_visita = ? WHERE id_sucursal IN ({placeholders})", [nuevo_estatus, fecha_actual] + lista_ids)
    conn.commit()
    conn.close()

def reiniciar_estatus_visitas(estado=None):
    conn = sqlite3.connect("data/rutas_qsr.db")
    cursor = conn.cursor()
    if estado:
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE', fecha_ultima_visita = NULL WHERE estado = ?", (estado,))
    else:
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE', fecha_ultima_visita = NULL")
    conn.commit()
    conn.close()