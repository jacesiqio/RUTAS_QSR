# datos.py
import sqlite3
import pandas as pd
import os
from datetime import datetime

def inicializar_base_datos():
    """Crea y actualiza la estructura de la base de datos con soporte multi-cliente y control de visitas."""
    if not os.path.exists("data"):
        os.makedirs("data")
        
    conn = sqlite3.connect("data/fsm_rutas.db")
    cursor = conn.cursor()
    
    # 🏢 TABLA MAESTRA DE SUCURSALES 
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sucursales (
            id_sucursal TEXT PRIMARY KEY,
            sucursal_nombre TEXT,
            direccion_completa TEXT,
            latitud REAL,
            longitud REAL,
            estado TEXT,
            zona_localidad TEXT,
            tipo_visita TEXT,
            fsm_asignado TEXT,
            cliente_marca TEXT DEFAULT 'LITTLE CAESARS',
            estatus_visita TEXT DEFAULT 'PENDIENTE',
            fecha_ultima_visita TEXT
        )
    """)
    
    # Inyección silenciosa para asegurar columnas en bases antiguas
    try:
        cursor.execute("ALTER TABLE sucursales ADD COLUMN estatus_visita TEXT DEFAULT 'PENDIENTE'")
    except:
        pass
    try:
        cursor.execute("ALTER TABLE sucursales ADD COLUMN fecha_ultima_visita TEXT")
    except:
        pass
        
    # 👤 TABLA DE PERFILES FSM
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS fsm_perfiles (
            id_fsm TEXT PRIMARY KEY,
            nombre_completo TEXT,
            direccion_base TEXT,
            latitud_base REAL,
            longitud_base REAL
        )
    """)
    
    cursor.execute("""
        INSERT OR IGNORE INTO fsm_perfiles (id_fsm, nombre_completo, direccion_base, latitud_base, longitud_base)
        VALUES ('Javier Dominguez Delgadillo', 'Javier Dominguez Delgadillo', 'Atizapán Base, Edomex', 19.549732, -99.236967)
    """)
    
    conn.commit()
    conn.close()

def importar_maestro_sucursales(archivo_excel, nombre_archivo):
    """Importa el Excel, normaliza campos y preserva el estatus de visita."""
    df = pd.read_excel(archivo_excel)
    
    columnas_mapeadas = {
        'ID_SUCURSAL': 'id_sucursal',
        'SUCURSAL': 'sucursal_nombre',
        'DIRECCION_COMPLETA': 'direccion_completa',
        'LATITUD': 'latitud',
        'LONGITUD': 'longitud',
        'ESTADO': 'estado',
        'LOCALIDAD': 'zona_localidad',
        'FRANQUICIA': 'tipo_visita', 
        'FSM_ASIGNADO': 'fsm_asignado',
        'EMPRESA': 'cliente_marca'
    }
    
    columnas_existentes = {k: v for k, v in columnas_mapeadas.items() if k in df.columns}
    df_insertar = df[list(columnas_existentes.keys())].rename(columns=columnas_existentes)
    
    for col in df_insertar.select_dtypes(include=['object']).columns:
        df_insertar[col] = df_insertar[col].astype(str).str.upper()
        
    df_insertar['latitud'] = pd.to_numeric(df_insertar['latitud'], errors='coerce')
    df_insertar['longitud'] = pd.to_numeric(df_insertar['longitud'], errors='coerce')
    df_insertar = df_insertar.dropna(subset=['id_sucursal', 'latitud', 'longitud'])
    df_insertar = df_insertar.drop_duplicates(subset=['id_sucursal'], keep='first')
    
    conn = sqlite3.connect("data/fsm_rutas.db")
    df_insertar.to_sql("sucursales_temp", conn, if_exists="replace", index=False)
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sucursales (id_sucursal, sucursal_nombre, direccion_completa, latitud, longitud, estado, zona_localidad, tipo_visita, fsm_asignado, cliente_marca, estatus_visita, fecha_ultima_visita)
        SELECT t.id_sucursal, t.sucursal_nombre, t.direccion_completa, t.latitud, t.longitud, t.estado, t.zona_localidad, t.tipo_visita, t.fsm_asignado, t.cliente_marca, 
               COALESCE((SELECT estatus_visita FROM sucursales WHERE id_sucursal = t.id_sucursal), 'PENDIENTE'),
               COALESCE((SELECT fecha_ultima_visita FROM sucursales WHERE id_sucursal = t.id_sucursal), NULL)
        FROM sucursales_temp t
    """)
    conn.commit()
    
    cursor.execute("SELECT DISTINCT fsm_asignado FROM sucursales WHERE fsm_asignado IS NOT NULL LIMIT 1")
    fsm_res = cursor.fetchone()
    fsm_detectado = fsm_res[0] if fsm_res else "JAVIER DOMINGUEZ DELGADILLO"
    conn.close()
    
    return len(df_insertar), fsm_detectado

# ============================================================
# FUNCIONES DE GESTIÓN DE VISITAS (FASE 2)
# ============================================================
def actualizar_estatus_sucursales(lista_ids, nuevo_estatus="COMPLETADA"):
    """Actualiza masivamente el estatus y registra fecha de visita."""
    if not lista_ids:
        return
    conn = sqlite3.connect("data/fsm_rutas.db")
    cursor = conn.cursor()
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M")
    
    placeholders = ','.join(['?'] * len(lista_ids))
    query = f"UPDATE sucursales SET estatus_visita = ?, fecha_ultima_visita = ? WHERE id_sucursal IN ({placeholders})"
    
    cursor.execute(query, [nuevo_estatus, fecha_actual] + list(lista_ids))
    conn.commit()
    conn.close()

def reiniciar_estatus_visitas(estado=None, zona_localidad=None):
    """Reinicia todas las sucursales a 'PENDIENTE' para un nuevo ciclo."""
    conn = sqlite3.connect("data/fsm_rutas.db")
    cursor = conn.cursor()
    
    if estado and zona_localidad and zona_localidad != "TODAS LAS LOCALIDADES":
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE', fecha_ultima_visita = NULL WHERE estado = ? AND zona_localidad = ?", [estado, zona_localidad])
    elif estado:
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE', fecha_ultima_visita = NULL WHERE estado = ?", [estado])
    else:
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE', fecha_ultima_visita = NULL")
        
    conn.commit()
    conn.close()