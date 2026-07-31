import pandas as pd
import gspread
import streamlit as st

# ==========================================
# 1. CONEXIÓN A LA NUBE (GOOGLE SHEETS VIA SECRETS)
# ==========================================
@st.cache_resource
def conectar_bd():
    """Establece conexión con Google Sheets usando la bóveda de Streamlit Cloud."""
    try:
        # Extraemos las credenciales de la bóveda de Streamlit
        credenciales_dict = dict(st.secrets["gcp_service_account"])
        
        # Conectamos a Google usando ese diccionario en lugar de un archivo físico
        gc = gspread.service_account_from_dict(credenciales_dict)
        
        sh = gc.open('RutasQSR_Cloud')
        hoja = sh.sheet1  # Trabajamos sobre la primera pestaña
        return hoja
    except Exception as e:
        st.error(f"❌ Error crítico de conexión a la nube: {e}")
        st.info("💡 Verifica que hayas configurado correctamente los 'Secrets' en Streamlit Cloud.")
        st.stop()

# ==========================================
# 2. LECTURA DE DATOS (READ)
# ==========================================
def cargar_inventario_maestro():
    """Descarga toda la base de datos de la nube y la convierte en un DataFrame."""
    hoja = conectar_bd()
    datos = hoja.get_all_records()
    
    if not datos:
        # Si la hoja está vacía, devolvemos el cascarón con las 10 columnas oficiales
        columnas = [
            "id_sucursal", "cliente_marca", "sucursal_nombre", "estado", 
            "zona_localidad", "latitud", "longitud", "direccion_completa", 
            "visitas_realizadas", "estatus_visita"
        ]
        return pd.DataFrame(columns=columnas)
        
    return pd.DataFrame(datos)

def obtener_sucursales_pendientes():
    """Filtra y devuelve solo las sucursales PENDIENTES, ordenadas para dar prioridad a las más rezagadas."""
    df = cargar_inventario_maestro()
    if df.empty:
        return df
    
    # Extraemos solo las pendientes
    pendientes = df[df['estatus_visita'] != 'COMPLETADA'].copy()
    
    # APLICAMOS LA REGLA DE ORO: Ordenamos de menor a mayor cantidad de visitas realizadas
    if not pendientes.empty and 'visitas_realizadas' in pendientes.columns:
        # Convertimos a número por seguridad y rellenamos vacíos con 0
        pendientes['visitas_realizadas'] = pd.to_numeric(pendientes['visitas_realizadas'], errors='coerce').fillna(0)
        pendientes = pendientes.sort_values(by='visitas_realizadas', ascending=True)
        
    return pendientes

# ==========================================
# 3. ESCRITURA Y ACTUALIZACIÓN (WRITE / UPDATE)
# ==========================================
def inyectar_nuevas_sucursales(df_nuevas):
    """Sube nuevas sucursales a Google Sheets desde el Agente Cartógrafo (Enriquecedor)."""
    hoja = conectar_bd()
    # Convertimos el DataFrame a una lista pura para subirla en bloque
    valores_a_subir = df_nuevas.values.tolist()
    # Hacemos un "Append" para inyectarlas debajo de la última fila ocupada
    hoja.append_rows(valores_a_subir)
    return True

def actualizar_estatus_sucursal(id_sucursal, nuevo_estatus):
    """
    Busca la sucursal por ID y actualiza su estatus en tiempo real en la nube.
    Si el estatus es COMPLETADA, aplica la matemática acumulativa (+1 visita).
    """
    hoja = conectar_bd()
    # Extraemos toda la Columna A (ID de Sucursales) para encontrar en qué fila está
    columna_ids = hoja.col_values(1)
    
    try:
        # Sumamos +1 porque las filas en Sheets empiezan en 1 (y los índices de Python en 0)
        fila_excel = columna_ids.index(str(id_sucursal)) + 1
        
        # 1. Actualizamos el Estatus (Columna J -> Columna número 10)
        hoja.update_cell(fila_excel, 10, nuevo_estatus)
        
        # 2. Si es una visita completada, sumamos al histórico
        if nuevo_estatus == 'COMPLETADA':
            # Leemos el valor actual (Columna I -> Columna número 9)
            visitas_actuales = hoja.cell(fila_excel, 9).value
            
            # Si está vacío le ponemos 0, si no, lo convertimos a entero
            try:
                visitas_numero = int(visitas_actuales) if visitas_actuales else 0
            except ValueError:
                visitas_numero = 0
                
            nuevas_visitas = visitas_numero + 1
            hoja.update_cell(fila_excel, 9, nuevas_visitas)
            
        return True
    except ValueError:
        # El ID no se encontró en la columna A
        return False
