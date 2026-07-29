import sqlite3
import os
import pandas as pd
from datetime import datetime

# 📌 DETECCIÓN Y HOMOLOGACIÓN AUTOMÁTICA DE BASE DE DATOS
DB_DIR = "data"
DB_NAME = "rutas_qsr.db"

if os.path.exists(os.path.join(DB_DIR, DB_NAME)):
    DB_PATH = os.path.join(DB_DIR, DB_NAME)
elif os.path.exists(DB_NAME):
    DB_PATH = DB_NAME
else:
    os.makedirs(DB_DIR, exist_ok=True)
    DB_PATH = os.path.join(DB_DIR, DB_NAME)


def inicializar_base_datos():
    """Crea las tablas necesarias en rutas_qsr.db si no existen. (Sin perfiles FSM)"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Tabla principal de sucursales QSR
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


def importar_maestro_sucursales(uploaded_file, filename):
    """Importa o actualiza registros masivos desde Excel o CSV."""
    inicializar_base_datos()
    
    if filename.lower().endswith('.csv'):
        df = pd.read_csv(uploaded_file)
    else:
        df = pd.read_excel(uploaded_file)
        
    df.columns = df.columns.str.strip().str.lower()
    
    conn = sqlite3.connect(DB_PATH)
    df.to_sql("temp_importacion", conn, if_exists="replace", index=False)
    
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sucursales (
            id_sucursal, sucursal_nombre, cliente_marca, latitud, longitud,
            estado, zona_localidad, direccion_completa, estatus_visita, fecha_ultima_visita, tipo_visita
        )
        SELECT 
            id_sucursal, sucursal_nombre, cliente_marca, latitud, longitud,
            estado, zona_localidad, direccion_completa,
            COALESCE(estatus_visita, 'PENDIENTE'),
            fecha_ultima_visita,
            COALESCE(tipo_visita, 'STANDARD')
        FROM temp_importacion
    """)
    
    total = cursor.rowcount
    conn.commit()
    conn.close()
    
    return total


def actualizar_estatus_sucursales(ids_list, nuevo_estatus):
    """Actualiza el estatus de las visitas seleccionadas."""
    if not ids_list:
        return
        
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    placeholders = ','.join(['?'] * len(ids_list))
    fecha_actual = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    cursor.execute(f"""
        UPDATE sucursales 
        SET estatus_visita = ?, fecha_ultima_visita = ?
        WHERE id_sucursal IN ({placeholders})
    """, [nuevo_estatus, fecha_actual] + list(ids_list))
    
    conn.commit()
    conn.close()


def reiniciar_estatus_visitas(estado=None):
    """Reinicia todas las visitas o las de un estado a 'PENDIENTE'."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    if estado and estado != "TODOS LOS ESTADOS":
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE' WHERE estado = ?", (estado,))
    else:
        cursor.execute("UPDATE sucursales SET estatus_visita = 'PENDIENTE'")
        
    conn.commit()
    conn.close()