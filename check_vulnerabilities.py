# check_vulnerabilities.py
import os
import sqlite3
import shutil

db_path = "data/rutas_qsr.db"
log_file = "data/audit_log.txt"
vuln_found = False

print("=====================================================================")
print("🔍 INICIANDO AUDITORÍA DE SEGURIDAD RELACIONAL | RUTAS-QSR (PYTHON)")
print("=====================================================================")

if not os.path.exists(db_path):
    print("ℹ️ La base de datos no existe aún. Se inicializará limpia.")
    exit()

conn = sqlite3.connect(db_path)
cursor = conn.cursor()

columnas_oficiales = {
    'id_sucursal', 'sucursal_nombre', 'cliente_marca', 'latitud', 'longitud', 
    'estado', 'zona_localidad', 'direccion_completa', 'estatus_visita', 
    'fecha_ultima_visita', 'tipo_visita'
}

try:
    cursor.execute("PRAGMA table_info(sucursales);")
    columnas_actuales = {row[1].lower() for row in cursor.fetchall()}
    
    if not columnas_actuales:
        print("ℹ️ La tabla sucursales aún no ha sido creada.")
    elif columnas_actuales != columnas_oficiales:
        print("🚨 ALERTA: Desviación estructural detectada en la base de datos.")
        print(f"Columnas no reconocidas o faltantes: {columnas_actuales.symmetric_difference(columnas_oficiales)}")
        vuln_found = True
    else:
        print("✅ Estructura de campos validada al 100%. Molde perfecto de 11 columnas.")
except Exception as e:
    print(f"❌ Error al analizar columnas: {e}")

if vuln_found:
    print("---------------------------------------------------------------------")
    print("🛠️ INICIANDO DEPURACIÓN Y RECONSTRUCCIÓN DEL ESQUEMA...")
    conn.close()
    
    shutil.copy(db_path, f"{db_path}.bak")
    print(f"💾 Respaldo de emergencia creado en: {db_path}.bak")
    
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS sucursales_nueva (
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
    );
    """)
    
    try:
        columnas_seguras = list(columnas_actuales.intersection(columnas_oficiales))
        if columnas_seguras:
            cols_str = ", ".join(columnas_seguras)
            cursor.execute(f"""
            INSERT OR IGNORE INTO sucursales_nueva ({cols_str})
            SELECT {cols_str} FROM sucursales;
            """)
        
        cursor.execute("DROP TABLE IF EXISTS sucursales;")
        cursor.execute("ALTER TABLE sucursales_nueva RENAME TO sucursales;")
        cursor.execute("VACUUM;")
        conn.commit()
        print("⚡ Limpieza ejecutada con éxito. El esquema ha sido homologado estrictamente.")
    except Exception as e:
        print(f"❌ Error durante la migración: {e}")
else:
    print("---------------------------------------------------------------------")
    print("🎉 RESULTADO: Base de datos RUTAS QSR sana, segura y lista para operar.")

conn.close()