import streamlit as st
import pandas as pd
import gspread
import uuid
import time
# from tu_archivo_rutas import motor_vrp, motor_radial  <-- Importa aquí tus funciones matemáticas reales

# ==========================================
# 1. CONEXIÓN A GOOGLE SHEETS
# ==========================================
st.set_page_config(page_title="ECOLAB - Centro de Despacho VRP", layout="wide")
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/c/ca/Ecolab_logo.svg/1024px-Ecolab_logo.svg.png", width=300)
st.title("Centro de Despacho e Inteligencia Logística")

@st.cache_resource
def conectar_sheets():
    # Asegúrate de tener tu archivo credenciales.json en la misma carpeta que este código
    gc = gspread.service_account(filename='credenciales.json')
    # Abre el archivo por su nombre exacto
    sh = gc.open('RutasQSR_Cloud')
    return sh

try:
    sh = conectar_sheets()
    st.success("✅ Conectado a la Nube (AppSheet) exitosamente.")
except Exception as e:
    st.error(f"❌ Error de conexión: {e}. Revisa tu archivo credenciales.json")
    st.stop()

# ==========================================
# 2. LECTURA DE BASES DE DATOS
# ==========================================
hoja_params = sh.worksheet('Parametros_Ruta')
hoja_sucursales = sh.worksheet('Base_Sucursales')
hoja_itinerario = sh.worksheet('Itinerario_Activo')

# Traer datos a DataFrames de Pandas
df_params = pd.DataFrame(hoja_params.get_all_records())
df_sucursales = pd.DataFrame(hoja_sucursales.get_all_records())

# ==========================================
# 3. INTERFAZ Y DETECCIÓN DE RUTAS PENDIENTES
# ==========================================
st.subheader("Bandeja de Solicitudes desde AppSheet (Gerentes)")

# Filtrar solo las que el gerente marcó y están PENDIENTES
if not df_params.empty and 'estatus_calculo' in df_params.columns:
    pendientes = df_params[df_params['estatus_calculo'] == 'PENDIENTE']
else:
    pendientes = pd.DataFrame()

if pendientes.empty:
    st.info("No hay rutas pendientes por calcular en este momento. Esperando peticiones del celular...")
else:
    st.write("🔴 **¡Atención! Hay rutas solicitadas por el gerente:**")
    st.dataframe(pendientes)
    
    if st.button("🚀 Procesar y Calcular Rutas Pendientes"):
        
        for index, solicitud in pendientes.iterrows():
            id_ruta = solicitud['id_ruta']
            tipo_motor = solicitud['tipo_motor']
            max_vis = int(solicitud['max_visitas']) if pd.notna(solicitud['max_visitas']) else 10
            
            st.warning(f"Calculando Ruta {id_ruta} usando {tipo_motor}...")
            
            # Cambiar estatus a CALCULANDO en Google Sheets (fila index + 2 por los encabezados)
            fila_sheet = index + 2 
            hoja_params.update_cell(fila_sheet, 7, 'CALCULANDO') # 7 es la columna G (estatus_calculo)

            # ==========================================
            # 4. AQUÍ VA TU LÓGICA MATEMÁTICA (VRP / RADIAL)
            # ==========================================
            # NOTA PARA JAVIER: Aquí conectas tus motores. 
            # Por ahora, haré una simulación tomando las primeras 'max_vis' sucursales.
            
            # --- INICIO DE TU MAGIA ---
            if tipo_motor == 'Motor VRP':
                # df_resultado = motor_vrp(df_sucursales, max_vis, solicitud['hora_inicio'], solicitud['hora_termino'])
                df_resultado = df_sucursales.head(max_vis).copy() # SIMULACIÓN: Tomar las primeras 'X'
            elif tipo_motor == 'Diseño Radial':
                # df_resultado = motor_radial(df_sucursales, max_vis)
                df_resultado = df_sucursales.head(max_vis).copy() # SIMULACIÓN
            else:
                df_resultado = df_sucursales.head(max_vis).copy()
            # --- FIN DE TU MAGIA ---
            
            # ==========================================
            # 5. PREPARAR EL PAQUETE PARA APPSHEET (ITINERARIO)
            # ==========================================
            # Ahora empacamos el resultado en el formato exacto que espera el celular
            datos_para_appsheet = []
            orden = 1
            
            for i, sucursal in df_resultado.iterrows():
                id_parada = str(uuid.uuid4())[:8] # Genera un ID único para la parada
                
                fila_itinerario = [
                    id_parada,                      # A: id_parada
                    id_ruta,                        # B: id_ruta
                    orden,                          # C: orden
                    sucursal['id_sucursal'],        # D: id_sucursal
                    f"{sucursal['cliente_marca']} - {sucursal['sucursal_nombre']}", # E: marca_nombre
                    sucursal['latitud'],            # F: latitud
                    sucursal['longitud'],           # G: longitud
                    sucursal['direccion_completa'], # H: direccion
                    "PENDIENTE"                     # I: estatus_parada
                ]
                datos_para_appsheet.append(fila_itinerario)
                orden += 1
            
            # ==========================================
            # 6. ENVIAR RESULTADOS A LA NUBE Y CERRAR CICLO
            # ==========================================
            st.info(f"Enviando {len(datos_para_appsheet)} paradas al celular de la ruta {id_ruta}...")
            
            # Insertar en la hoja Itinerario_Activo
            hoja_itinerario.append_rows(datos_para_appsheet)
            
            # Actualizar el estatus del Gerente a LISTO
            hoja_params.update_cell(fila_sheet, 7, 'LISTO')
            
            st.success(f"✅ ¡Ruta {id_ruta} enviada con éxito! El celular del operador ya tiene su itinerario.")
            time.sleep(2)
            
        st.balloons()
        st.success("🎯 Todas las peticiones han sido procesadas.")
        # Refrescar la página para esperar nuevas órdenes
        st.rerun()

# Botón de actualización manual
st.markdown("---")
if st.button("🔄 Refrescar Bandeja de Entrada"):
    st.rerun()