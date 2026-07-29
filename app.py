import streamlit as st
import sys
import os
import time
import re
import sqlite3
import pandas as pd
import requests
import urllib.parse
import math
import io
import folium
from streamlit_folium import st_folium

# 🌟 CONFIGURACIÓN INICIAL DE STREAMLIT (DEBE SER LA PRIMERA LÍNEA)
st.set_page_config(page_title="RUTAS-QSR Dashboard", layout="wide", initial_sidebar_state="expanded")

# Inclusión dinámica del directorio actual en sys.path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# 📌 CONEXIÓN CON LA BASE DE DATOS Y MÓDULOS DEL PROYECTO
from datos import DB_PATH, inicializar_base_datos, importar_maestro_sucursales, actualizar_estatus_sucursales, reiniciar_estatus_visitas

# Importación flexible de simulación
try:
    from core.simulacion import simular_ruta_del_dia, calcular_distancia_haversine
except ImportError:
    from simulacion import simular_ruta_del_dia, calcular_distancia_haversine

# Importación flexible de motor logístico
try:
    from core.motor_logistico import generar_clusters_geograficos, optimizar_secuencia_por_proximidad
except ImportError:
    from motor_logistico import generar_clusters_geograficos, optimizar_secuencia_por_proximidad

# 🛡️ BLINDAJE DE SESIÓN CONTRA BUCLES INFINITOS
if 'bd_inicializada' not in st.session_state:
    inicializar_base_datos()
    st.session_state.bd_inicializada = True

# 🧠 VARIABLES DE SESIÓN (STATE)
if 'diaria_simulada' not in st.session_state:
    st.session_state.diaria_simulada = False
    st.session_state.diaria_visitas_final = []
    st.session_state.diaria_puntos_mapa = []
    st.session_state.diaria_coords_viaje = []
    st.session_state.diaria_ruta_n = 1
    st.session_state.diaria_alcaldia = ""

# Variables para el Diseñador Radial
if 'radial_simulada' not in st.session_state:
    st.session_state.radial_simulada = False
    st.session_state.radial_visitas_final = []
    st.session_state.radial_puntos_mapa = []
    st.session_state.radial_coords_viaje = []
    st.session_state.radial_pivote = ""
    st.session_state.radial_lat_piv = 0.0
    st.session_state.radial_lon_piv = 0.0
    st.session_state.radial_radio = 0.0

if 'geo_procesado' not in st.session_state:
    st.session_state.geo_procesado = False
    st.session_state.df_exitosos = pd.DataFrame()
    st.session_state.df_cuarentena = pd.DataFrame()
    st.session_state.df_duplicados = pd.DataFrame()

# 🎨 ESTILOS CSS PERSONALIZADOS (TABLAS ESTÁTICAS ANTI-VIBRACIÓN)
st.markdown("""
    <style>
    .main h1 { color: #002F6C; font-weight: 700; font-size: 1.8rem; }
    .stButton>button { background-color: #002F6C; color: white; border-radius: 6px; border: none; padding: 0.5rem 1rem; font-weight: bold; width: 100%; }
    .stButton>button:hover { background-color: #004B93; color: white; }
    div[data-testid="stExpander"] { border: 1px solid #002F6C; border-radius: 6px; }
    div[data-testid="stMetric"] { background-color: #f0f4f8; padding: 10px; border-radius: 6px; border-left: 5px solid #002F6C; }
    
    /* 🛡️ TABLAS HTML ESTÁTICAS */
    table.dataframe-renderizada { width: 100% !important; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; margin: 10px 0; }
    table.dataframe-renderizada th { background-color: #002F6C !important; color: white !important; font-weight: bold; padding: 10px; text-align: left; white-space: nowrap; }
    table.dataframe-renderizada td { padding: 8px 10px; border-bottom: 1px solid #e0e0e0; white-space: nowrap; }
    .contenedor-tabla-scroll { width: 100%; overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 4px; margin-bottom: 15px; background-color: white; }
    </style>
""", unsafe_allow_html=True)

st.title("🚗 Panel de Control Logístico | RUTAS-QSR")

# ============================================================
# FUNCIONES AUXILIARES Y HTML
# ============================================================
def renderizar_tabla_html(df):
    if df is None or df.empty:
        return ""
    html_table = df.to_html(classes="dataframe-renderizada", index=False, escape=False)
    return f'<div class="contenedor-tabla-scroll">{html_table}</div>'

def buscar_datos_osm_hibrido(marca, sucursal, localidad, estado):
    headers = {'User-Agent': 'RutasQSR_HybridAgent/1.0'}
    consultas = [
        f"{marca} {sucursal} {localidad} {estado} Mexico",
        f"{marca} {sucursal} {estado} Mexico",
        f"{marca} {sucursal} Mexico"
    ]
    for query in consultas:
        q_str = re.sub(' +', ' ', query).strip()
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q_str)}&format=json&limit=1&addressdetails=1"
        try:
            time.sleep(1.2)
            res = requests.get(url, headers=headers, timeout=10).json()
            if len(res) > 0:
                data = res[0]
                lat, lng = float(data['lat']), float(data['lon'])
                direccion = data.get('display_name', f"{sucursal}, {localidad}")
                addr = data.get('address', {})
                est_res = addr.get('state', '').upper()
                loc_res = addr.get('city', addr.get('town', addr.get('municipality', localidad))).upper()
                return lat, lng, direccion, est_res if est_res else estado, loc_res if loc_res else localidad
        except Exception:
            pass
    return None, None, None, None, None

def inyectar_a_base_maestra_11_campos(df_a_inyectar):
    conn = sqlite3.connect(DB_PATH)
    df_a_inyectar.to_sql("temp_homologacion", conn, if_exists="replace", index=False)
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR REPLACE INTO sucursales (
            id_sucursal, sucursal_nombre, cliente_marca, latitud, longitud, 
            estado, zona_localidad, direccion_completa, estatus_visita, fecha_ultima_visita, tipo_visita
        )
        SELECT 
            t.id_sucursal, t.sucursal_nombre, t.cliente_marca, t.latitud, t.longitud,
            t.estado, t.zona_localidad, t.direccion_completa,
            COALESCE((SELECT estatus_visita FROM sucursales WHERE id_sucursal = t.id_sucursal), 'PENDIENTE'),
            COALESCE((SELECT fecha_ultima_visita FROM sucursales WHERE id_sucursal = t.id_sucursal), NULL),
            COALESCE('STANDARD')
        FROM temp_homologacion t
    """)
    conn.commit()
    conn.close()

def obtener_ruta_vial_real(puntos_coordenadas):
    if len(puntos_coordenadas) < 2: 
        return puntos_coordenadas
    locs = ";".join([f"{lon},{lat}" for lat, lon in puntos_coordenadas])
    url = f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson"
    try:
        r_api = requests.get(url, timeout=5)
        if r_api.status_code == 200:
            data = r_api.json()
            if 'routes' in data and len(data['routes']) > 0:
                return [[lat, lon] for lon, lat in data['routes'][0]['geometry']['coordinates']]
    except Exception: 
        pass
    return puntos_coordenadas

def crear_mapa_base(puntos_marcadores, ruta_linea=None, color_linea="#002F6C"):
    if not puntos_marcadores: 
        return folium.Map(location=[19.4326, -99.1332], zoom_start=11)
    
    m = folium.Map(location=[puntos_marcadores[0]['lat'], puntos_marcadores[0]['lon']], zoom_start=11)
    lats, lons = [], []
    
    for p in puntos_marcadores:
        lats.append(p['lat'])
        lons.append(p['lon'])
        
        if p['idx'] == 0:
            color_icono, icono_tipo = "red", "home"
            popup_text = f"<b>{p['name']}</b><br>Punto de Partida"
        elif p['idx'] == "Pivote":
            color_icono, icono_tipo = "purple", "star"
            popup_text = f"<b>{p['name']}</b><br>Centro Referencia Radar"
        else:
            color_icono, icono_tipo = "blue", "info-sign"
            popup_text = f"<b>{p['name']}</b><br>Orden: {p['idx']}"
        
        folium.Marker(
            location=[p['lat'], p['lon']], popup=popup_text, icon=folium.Icon(color=color_icono, icon=icono_tipo)
        ).add_to(m)
        
    if ruta_linea and len(ruta_linea) > 1:
        folium.PolyLine(ruta_linea, color=color_linea, weight=4.5, opacity=0.85).add_to(m)
        for coord in ruta_linea:
            lats.append(coord[0])
            lons.append(coord[1])
            
    if lats and lons:
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
        
    return m

# ============================================================
# BARRA LATERAL (CARGA RÁPIDA)
# ============================================================
st.sidebar.header("📁 Carga Rápida (Matriz 11 Campos)")
uploaded_file = st.sidebar.file_uploader("Arrastra tu archivo listo (.xlsx, .csv)", type=["xlsx", "csv"])

if uploaded_file is not None:
    if 'ultimo_archivo_cargado' not in st.session_state or st.session_state.ultimo_archivo_cargado != uploaded_file.name:
        with st.spinner("Integrando base de datos a la matriz..."):
            total_filas = importar_maestro_sucursales(uploaded_file, uploaded_file.name)
            st.session_state.ultimo_archivo_cargado = uploaded_file.name
            st.sidebar.success(f"¡Carga Exitosa! {total_filas} registros operativos.")

# ============================================================
# MÓDULOS PRINCIPALES
# ============================================================
modulo_principal = st.radio(
    "Selecciona Módulo de Trabajo:", 
    ["🗺️ Planeación y Ruteo Inteligente", "📋 Control de Inventario y Visitas", "📥 Agente Enriquecedor de Nuevos Clientes"], 
    horizontal=True
)

if modulo_principal == "🗺️ Planeación y Ruteo Inteligente":
    df_marcas_maestras, df_estados_maestros = pd.DataFrame(), pd.DataFrame()
    
    try:
        conn = sqlite3.connect(DB_PATH)
        df_marcas_maestras = pd.read_sql_query("SELECT DISTINCT cliente_marca FROM sucursales WHERE cliente_marca IS NOT NULL ORDER BY cliente_marca", conn)
        df_estados_maestros = pd.read_sql_query("SELECT DISTINCT estado FROM sucursales WHERE estado IS NOT NULL AND estado != '' ORDER BY estado", conn)
        conn.close()
    except Exception as e:
        st.error(f"🚨 Error al leer la base de datos: {e}")

    if df_estados_maestros.empty:
        st.warning("⚠️ La base de datos está vacía o no hay tiendas registradas.")
    else:
        marcas_disponibles = ["TODAS LAS MARCAS"] + df_marcas_maestras['cliente_marca'].tolist()
        estados_disponibles = df_estados_maestros['estado'].tolist()

        st.markdown("### 🏢 Opciones de Ruteo Inteligente")
        tab_vrp, tab_radial = st.tabs(["⚡ Circuitos Automáticos (VRP Global)", "🎯 Diseñador Radial"])
        
        # ----------------------------------------------------
        # ⚡ PESTAÑA 1: CIRCUITOS AUTOMÁTICOS (VRP GLOBAL)
        # ----------------------------------------------------
        with tab_vrp:
            visitas_jornada = st.slider("Objetivo de visitas por jornada:", min_value=4, max_value=12, value=6)
            hora_inicio_diaria = st.select_slider("Hora de Inicio:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00")
            
            st.markdown("#### 📍 Configuración de Salida")
            opcion_origen = st.radio("Punto de Partida:", ["🏠 CASA", "🏢 ECOLAB (Cuautitlán)", "📍 Personalizado"], horizontal=True)
            
            lat_c, lon_c = 19.549965629588566, -99.23691334673492 # CASA
            nombre_origen_final = "🏠 CASA"
            
            if opcion_origen == "🏢 ECOLAB (Cuautitlán)":
                lat_c, lon_c = 19.655381063145374, -99.19368263138871
                nombre_origen_final = "🏢 ECOLAB (Cuautitlán)"
            elif opcion_origen == "📍 Personalizado":
                col_p1, col_p2 = st.columns(2)
                with col_p1:
                    nombre_origen_final = st.text_input("Nombre del Hotel / Origen:", value="Hotel Guanajuato")
                with col_p2:
                    coord_input = st.text_input("Pegar Latitud, Longitud (Ej: 21.0181, -101.2580):", value="")
                if coord_input:
                    try:
                        partes = coord_input.split(",")
                        lat_c = float(partes[0].strip())
                        lon_c = float(partes[1].strip())
                        st.success(f"✅ Satélite fijado en {nombre_origen_final}: Lat {lat_c}, Lon {lon_c}")
                    except Exception:
                        st.error("⚠️ Formato inválido. Asegúrate de separar con coma.")
            
            st.markdown("---")
            zona_general_elegida = st.selectbox("Zona General:", estados_disponibles)
            
            conn = sqlite3.connect(DB_PATH)
            df_selector_diario = pd.read_sql_query("SELECT DISTINCT zona_localidad FROM sucursales WHERE estado = ? AND zona_localidad IS NOT NULL", conn, params=[str(zona_general_elegida)])
            conn.close()

            if not df_selector_diario.empty:
                opciones_localidades = ["TODAS LAS LOCALIDADES"] + df_selector_diario['zona_localidad'].tolist()
                alcaldia_elegida = st.selectbox("Alcaldía objetivo:", opciones_localidades, index=0)
                
                conn = sqlite3.connect(DB_PATH)
                q_cnt = "SELECT COUNT(*) as total FROM sucursales WHERE " + ("estado = ?" if alcaldia_elegida == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?") + " AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')"
                p_cnt = [str(zona_general_elegida)] if alcaldia_elegida == "TODAS LAS LOCALIDADES" else [str(alcaldia_elegida), str(zona_general_elegida)]
                total_tiendas_zona = pd.read_sql_query(q_cnt, conn, params=p_cnt)['total'].values[0]
                conn.close()
                
                if total_tiendas_zona > 0:
                    total_rutas_calculadas = max(1, math.ceil(total_tiendas_zona / visitas_jornada))
                    ruta_elegida = st.selectbox(f"Circuitos Disponibles ({total_tiendas_zona} PENDIENTES):", list(range(1, total_rutas_calculadas + 1)))
                    
                    if st.button("🗺️ Desplegar Circuito Diario"):
                        conn = sqlite3.connect(DB_PATH)
                        q_pool = "SELECT * FROM sucursales WHERE " + ("estado = ?" if alcaldia_elegida == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?") + " AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')"
                        df_pool_sec = pd.read_sql_query(q_pool, conn, params=p_cnt)
                        conn.close()
                        
                        if not df_pool_sec.empty:
                            rutas_maestras = generar_clusters_geograficos(lat_c, lon_c, df_pool_sec.to_dict(orient='records'), visitas_jornada)
                            if rutas_maestras:
                                bloque_de_visitas = rutas_maestras[int(ruta_elegida) - 1] if int(ruta_elegida) <= len(rutas_maestras) else []
                                visitas_calc, _, _ = simular_ruta_del_dia(bloque_de_visitas, hora_inicio_diaria, len(bloque_de_visitas), False, "Base", (lat_c, lon_c))
                                
                                if visitas_calc:
                                    st.session_state.diaria_simulada = True
                                    st.session_state.diaria_alcaldia = alcaldia_elegida
                                    st.session_state.diaria_visitas_final = []
                                    st.session_state.diaria_puntos_mapa = [{"lat": lat_c, "lon": lon_c, "name": f"📍 ORIGEN ({nombre_origen_final})", "idx": 0}]
                                    st.session_state.diaria_coords_viaje = [(lat_c, lon_c)]
                                    
                                    tiendas_incluidas = 0
                                    for idx, v in enumerate(visitas_calc):
                                        orig = next(item for item in bloque_de_visitas if item['id_sucursal'] == v.get('ID Sucursal', v.get('ID', '')))
                                        h_llegada = v.get("ETA Llegada", "")
                                        h_salida = v.get("ETA Salida", v.get("Hora Salida", ""))
                                        
                                        if h_salida > "19:00":
                                            st.error(f"🛑 Corte Estricto: La ruta se detuvo antes de {orig['sucursal_nombre']}. La salida proyectada ({h_salida}) supera el límite absoluto de las 19:00 hrs.")
                                            break
                                        if h_salida > "18:00":
                                            st.warning(f"⚠️ Excepción Operativa: La sucursal {orig['sucursal_nombre']} terminaría a las {h_salida} hrs. Queda a tu criterio realizar esta visita.")
                                            
                                        st.session_state.diaria_visitas_final.append({
                                            "ID": orig['id_sucursal'], "Sec": tiendas_incluidas + 1, "Marca": orig['cliente_marca'], 
                                            "Sucursal": orig['sucursal_nombre'], "Llegada": h_llegada, "Salida": h_salida, "Dirección": orig['direccion_completa']
                                        })
                                        st.session_state.diaria_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {orig['sucursal_nombre']}", "idx": tiendas_incluidas + 1})
                                        st.session_state.diaria_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))
                                        tiendas_incluidas += 1
                                else:
                                    st.error("No se pudo generar la simulación de tiempos.")
                            else:
                                st.warning("⚠️ No se pudieron generar clusters con las tiendas actuales.")
                        else:
                            st.warning("⚠️ No hay tiendas pendientes en esta zona.")
                else:
                    st.success("✅ Todas las tiendas en esta zona ya están COMPLETADAS.")

            if st.session_state.diaria_simulada:
                st.write("---\n### 📋 Itinerario Diario")
                st.markdown(renderizar_tabla_html(pd.DataFrame(st.session_state.diaria_visitas_final)), unsafe_allow_html=True)
                ids_en_ruta = [item["ID"] for item in st.session_state.diaria_visitas_final]
                completadas_sel = st.multiselect("Marcar completadas:", options=ids_en_ruta, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.diaria_visitas_final if item["ID"] == x))
                if st.button("💾 Guardar Seleccionadas como COMPLETADAS"):
                    actualizar_estatus_sucursales(completadas_sel, "COMPLETADA")
                    st.session_state.diaria_simulada = False
                    st.rerun()
                st_folium(crear_mapa_base(st.session_state.diaria_puntos_mapa, obtener_ruta_vial_real(st.session_state.diaria_coords_viaje)), width=1200, height=450)

        # ----------------------------------------------------
        # 🎯 PESTAÑA 2: DISEÑADOR RADIAL 
        # ----------------------------------------------------
        with tab_radial:
            st.markdown("#### 🎯 Diseñador Radial (Ruteo por Proximidad)")
            st.info("Filtra por zona para seleccionar tu Tienda Pivote. El sistema trazará el radio para atrapar sucursales y generará la ruta respetando la zona elástica de horario (Max 19:00).")
            
            col_rv1, col_rv2 = st.columns(2)
            with col_rv1:
                visitas_jornada_rad = st.slider("Objetivo de visitas por jornada:", min_value=4, max_value=12, value=6, key="rad_visitas")
            with col_rv2:
                hora_inicio_diaria_rad = st.select_slider("Hora de Inicio:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00", key="rad_hora")

            st.markdown("#### 📍 Configuración de Salida")
            opcion_origen_rad = st.radio("Punto de Partida:", ["🏠 CASA", "🏢 ECOLAB (Cuautitlán)", "📍 Personalizado"], horizontal=True, key="rad_origen")
            
            lat_c_rad, lon_c_rad = 19.549965629588566, -99.23691334673492
            nombre_origen_rad_final = "🏠 CASA"
            
            if opcion_origen_rad == "🏢 ECOLAB (Cuautitlán)":
                lat_c_rad, lon_c_rad = 19.655381063145374, -99.19368263138871
                nombre_origen_rad_final = "🏢 ECOLAB (Cuautitlán)"
            elif opcion_origen_rad == "📍 Personalizado":
                col_pr1, col_pr2 = st.columns(2)
                with col_pr1:
                    nombre_origen_rad_final = st.text_input("Nombre del Hotel / Origen:", value="Hotel Guanajuato", key="rad_nombre")
                with col_pr2:
                    coord_input_rad = st.text_input("Pegar Latitud, Longitud:", value="", key="rad_coord")
                if coord_input_rad:
                    try:
                        partes = coord_input_rad.split(",")
                        lat_c_rad = float(partes[0].strip())
                        lon_c_rad = float(partes[1].strip())
                        st.success(f"✅ Satélite fijado en {nombre_origen_rad_final}: Lat {lat_c_rad}, Lon {lon_c_rad}")
                    except Exception:
                        st.error("⚠️ Formato inválido.")
                        
            st.markdown("---")
            zona_general_rad = st.selectbox("Zona General (Estado):", estados_disponibles, key="rad_zona")
            
            conn = sqlite3.connect(DB_PATH)
            df_loc_rad = pd.read_sql_query("SELECT DISTINCT zona_localidad FROM sucursales WHERE estado = ? AND zona_localidad IS NOT NULL", conn, params=[str(zona_general_rad)])
            
            if not df_loc_rad.empty:
                opciones_loc_rad = ["TODAS LAS LOCALIDADES"] + df_loc_rad['zona_localidad'].tolist()
                alcaldia_rad = st.selectbox("Alcaldía objetivo (Localidad):", opciones_loc_rad, key="rad_alc")
                
                q_pivote = "SELECT * FROM sucursales WHERE " + ("estado = ?" if alcaldia_rad == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?") + " AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')"
                p_pivote = [str(zona_general_rad)] if alcaldia_rad == "TODAS LAS LOCALIDADES" else [str(alcaldia_rad), str(zona_general_rad)]
                df_pivotes_pool = pd.read_sql_query(q_pivote, conn, params=p_pivote)
                
                df_all_pending = pd.read_sql_query("SELECT * FROM sucursales WHERE estatus_visita IS NULL OR estatus_visita != 'COMPLETADA'", conn)
                conn.close()
                
                if not df_pivotes_pool.empty:
                    opciones_tiendas_rad = df_pivotes_pool['sucursal_nombre'].tolist()
                    
                    col1, col2 = st.columns([2, 1])
                    with col1:
                        tienda_pivote_nombre = st.selectbox("Tienda Central (Pivote - Referencia Radar):", opciones_tiendas_rad, key="rad_piv")
                    with col2:
                        radio_km = st.slider("Radio de Cobertura (Km):", min_value=1.0, max_value=20.0, value=3.0, step=0.5, key="rad_km")
                    
                    if st.button("🔍 Escanear Perímetro y Generar Ruta", key="btn_rad"):
                        tienda_pivote = df_pivotes_pool[df_pivotes_pool['sucursal_nombre'] == tienda_pivote_nombre].iloc[0]
                        lat_pivote = float(tienda_pivote['latitud'])
                        lon_pivote = float(tienda_pivote['longitud'])
                        
                        tiendas_atrapadas = []
                        for idx, row in df_all_pending.iterrows():
                            if str(row['sucursal_nombre']).strip() == str(tienda_pivote_nombre).strip():
                                continue
                            dist = calcular_distancia_haversine(lat_pivote, lon_pivote, float(row['latitud']), float(row['longitud']))
                            if dist <= radio_km:
                                tiendas_atrapadas.append(row.to_dict())
                                
                        if tiendas_atrapadas:
                            tiendas_optimizadas = optimizar_secuencia_por_proximidad(lat_c_rad, lon_c_rad, tiendas_atrapadas)
                            bloque_de_visitas = tiendas_optimizadas[:visitas_jornada_rad]
                            
                            visitas_calc, _, _ = simular_ruta_del_dia(bloque_de_visitas, hora_inicio_diaria_rad, len(bloque_de_visitas), False, "Base", (lat_c_rad, lon_c_rad))
                            
                            if visitas_calc:
                                st.session_state.radial_simulada = True
                                st.session_state.radial_pivote = tienda_pivote_nombre
                                st.session_state.radial_lat_piv = lat_pivote
                                st.session_state.radial_lon_piv = lon_pivote
                                st.session_state.radial_radio = radio_km
                                st.session_state.radial_visitas_final = []
                                
                                st.session_state.radial_puntos_mapa = [
                                    {"lat": lat_c_rad, "lon": lon_c_rad, "name": f"📍 ORIGEN ({nombre_origen_rad_final})", "idx": 0},
                                    {"lat": lat_pivote, "lon": lon_pivote, "name": f"🌟 PIVOTE (Centro Radar): {tienda_pivote_nombre}", "idx": "Pivote"}
                                ]
                                st.session_state.radial_coords_viaje = [(lat_c_rad, lon_c_rad)]
                                
                                tiendas_incluidas = 0
                                for idx, v in enumerate(visitas_calc):
                                    orig = next(item for item in bloque_de_visitas if item['id_sucursal'] == v.get('ID Sucursal', v.get('ID', '')))
                                    h_llegada = v.get("ETA Llegada", "")
                                    h_salida = v.get("ETA Salida", v.get("Hora Salida", ""))
                                    
                                    if h_salida > "19:00":
                                        st.error(f"🛑 Corte Estricto: La ruta se detuvo antes de {orig['sucursal_nombre']}. La salida proyectada ({h_salida}) supera el límite absoluto de las 19:00 hrs.")
                                        break
                                    if h_salida > "18:00":
                                        st.warning(f"⚠️ Excepción Operativa: La sucursal {orig['sucursal_nombre']} terminaría a las {h_salida} hrs. Queda a tu criterio realizar esta visita en campo.")
                                        
                                    st.session_state.radial_visitas_final.append({
                                        "ID": orig['id_sucursal'], "Sec": tiendas_incluidas + 1, "Marca": orig['cliente_marca'], 
                                        "Sucursal": orig['sucursal_nombre'], "Llegada": h_llegada, "Salida": h_salida, "Dirección": orig['direccion_completa']
                                    })
                                    st.session_state.radial_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {orig['sucursal_nombre']}", "idx": tiendas_incluidas + 1})
                                    st.session_state.radial_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))
                                    tiendas_incluidas += 1
                                    
                                st.success(f"✅ Ruta trazada con {tiendas_incluidas} paradas.")
                            else:
                                st.error("Fallo al simular tiempos.")
                        else:
                            st.warning(f"No hay otras tiendas en un radio de {radio_km} km de {tienda_pivote_nombre}.")
                else:
                    st.warning("No hay tiendas pendientes en esta zona de búsqueda.")
            else:
                st.success("✅ Todas las tiendas del sistema están COMPLETADAS.")

            if st.session_state.radial_simulada:
                st.write("---\n### 📋 Itinerario Radial")
                st.markdown(renderizar_tabla_html(pd.DataFrame(st.session_state.radial_visitas_final)), unsafe_allow_html=True)
                ids_en_ruta = [item["ID"] for item in st.session_state.radial_visitas_final]
                completadas_sel = st.multiselect("Marcar completadas:", options=ids_en_ruta, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.radial_visitas_final if item["ID"] == x))
                if st.button("💾 Guardar Seleccionadas como COMPLETADAS", key="btn_save_rad"):
                    actualizar_estatus_sucursales(completadas_sel, "COMPLETADA")
                    st.session_state.radial_simulada = False
                    st.rerun()
                
                mapa_radial = crear_mapa_base(st.session_state.radial_puntos_mapa, obtener_ruta_vial_real(st.session_state.radial_coords_viaje))
                folium.Circle(
                    location=[st.session_state.radial_lat_piv, st.session_state.radial_lon_piv], 
                    radius=st.session_state.radial_radio * 1000, color='red', weight=2, fill=True, fillOpacity=0.1
                ).add_to(mapa_radial)
                st_folium(mapa_radial, width=1200, height=450)

# ============================================================
# 📋 MÓDULO 2: CONTROL DE INVENTARIO Y VISITAS (CON MODO EDICIÓN)
# ============================================================
elif modulo_principal == "📋 Control de Inventario y Visitas":
    st.markdown("### 📋 Módulo Administrativo de Inventario")
    
    # 🚀 NUEVO: Subdivisión en pestañas para proteger la Base de Datos
    tab_vista, tab_edicion = st.tabs(["👁️ Vista General", "✏️ Editor Maestro de Base de Datos"])
    
    with tab_vista:
        try:
            conn = sqlite3.connect(DB_PATH)
            df_inv = pd.read_sql_query("SELECT id_sucursal, cliente_marca, sucursal_nombre, estado, zona_localidad, estatus_visita, fecha_ultima_visita FROM sucursales ORDER BY estado", conn)
            conn.close()
        except Exception:
            df_inv = pd.DataFrame()
            
        if df_inv.empty:
            st.warning("⚠️ La base de datos está vacía.")
        else:
            st.markdown(renderizar_tabla_html(df_inv), unsafe_allow_html=True)
            lista_estados_limpia = sorted(df_inv['estado'].dropna().astype(str).unique().tolist())
            est_reset = st.selectbox("Estado a reiniciar:", ["TODOS LOS ESTADOS"] + lista_estados_limpia)
            if st.button("🚨 Reiniciar Estatus a PENDIENTE"):
                reiniciar_estatus_visitas(None if est_reset == "TODOS LOS ESTADOS" else est_reset)
                st.rerun()

    # 🛡️ ZONA RESTRINGIDA: EDITOR DE BASE DE DATOS
    with tab_edicion:
        st.info("⚠️ **ZONA RESTRINGIDA:** Aquí puedes editar, agregar o borrar información directamente de la Base de Datos. Los cambios guardados no se pueden deshacer.")
        
        # 1. El Seguro del Gatillo
        bloqueo_edicion = st.toggle("🔓 Habilitar Modo Edición Avanzada")
        
        if bloqueo_edicion:
            conn = sqlite3.connect(DB_PATH)
            df_completo = pd.read_sql_query("SELECT * FROM sucursales", conn)
            conn.close()
            
            # Tabla interactiva editable
            df_editado = st.data_editor(
                df_completo,
                num_rows="dynamic", # Permite agregar y borrar filas
                use_container_width=True,
                height=500
            )
            
            # 2. La Confirmación Explícita (Doble Verificación)
            st.markdown("#### 🔒 Acciones de Guardado")
            col_btn1, col_btn2 = st.columns([1, 2])
            
            with col_btn1:
                confirmacion = st.checkbox("☑️ Confirmo que revisé los cambios")
            
            with col_btn2:
                # El botón solo ejecuta el guardado si el checkbox está marcado
                if st.button("💾 Sobrescribir Base de Datos", type="primary"):
                    if confirmacion:
                        with st.spinner("Guardando cambios permanentemente..."):
                            try:
                                conn = sqlite3.connect(DB_PATH)
                                cursor = conn.cursor()
                                
                                # Estrategia segura: Guardar en tabla temporal, borrar original y volcar datos para mantener estructura
                                df_editado.to_sql("temp_backup", conn, if_exists="replace", index=False)
                                cursor.execute("DELETE FROM sucursales")
                                
                                # Obtener nombres de columnas dinámicamente para el INSERT
                                columnas = ", ".join(df_editado.columns)
                                cursor.execute(f"INSERT INTO sucursales ({columnas}) SELECT {columnas} FROM temp_backup")
                                cursor.execute("DROP TABLE temp_backup")
                                
                                conn.commit()
                                conn.close()
                                
                                st.success("✅ ¡Base de Datos actualizada con éxito!")
                                time.sleep(1.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"🚨 Error al guardar: {e}")
                    else:
                        st.warning("⚠️ Debes marcar la casilla de confirmación antes de presionar Guardar.")

elif modulo_principal == "📥 Agente Enriquecedor de Nuevos Clientes":
    st.markdown("### 📥 Agente Híbrido de Enriquecimiento (6 Campos Base)")
    excel_crudo = st.file_uploader("Sube la base de datos del cliente (.csv o .xlsx)", type=["xlsx", "csv"])
    if excel_crudo and not st.session_state.geo_procesado:
        if excel_crudo.name.lower().endswith('.csv'): df_input = pd.read_csv(excel_crudo)
        else: df_input = pd.read_excel(excel_crudo)
        df_input.columns = df_input.columns.str.strip().str.lower()
        columnas_requeridas = ['id_sucursal', 'sucursal_nombre', 'cliente_marca', 'franquicia', 'zona_localidad', 'estado']
        faltantes = [c for c in columnas_requeridas if c not in df_input.columns]
        if faltantes: st.error(f"❌ Error: Faltan estas columnas: {', '.join(faltantes)}")
        else:
            st.write("👀 **Vista previa:**")
            st.markdown(renderizar_tabla_html(df_input[columnas_requeridas].head(3)), unsafe_allow_html=True)
            if st.button("🚀 Iniciar Agente Híbrido"):
                conn = sqlite3.connect(DB_PATH)
                try: ids_existentes = pd.read_sql_query("SELECT id_sucursal FROM sucursales", conn)['id_sucursal'].tolist()
                except Exception: ids_existentes = []
                df_duplicados = df_input[df_input['id_sucursal'].isin(ids_existentes)]
                df_nuevos = df_input[~df_input['id_sucursal'].isin(ids_existentes)]
                st.session_state.df_duplicados = df_duplicados.copy()
                if df_nuevos.empty:
                    st.warning("⚠️ Las sucursales ya existen en la Base de Datos.")
                    st.session_state.geo_procesado = True
                    conn.close(); st.rerun()
                exitosos, fallidos = [], []
                progreso = st.progress(0, text="Buscando coordenadas...")
                total_nuevos = len(df_nuevos)
                for i, (idx_row, row) in enumerate(df_nuevos.iterrows()):
                    marca, sucursal, localidad, estado = str(row['cliente_marca']).strip(), str(row['sucursal_nombre']).strip(), str(row['zona_localidad']).strip(), str(row['estado']).strip()
                    progreso.progress((i + 1) / total_nuevos, text=f"📍 Buscando: {sucursal}...")
                    lat, lng, dire, est_res, loc_res = buscar_datos_osm_hibrido(marca, sucursal, localidad, estado)
                    fila = {'id_sucursal': str(row['id_sucursal']).strip(), 'sucursal_nombre': sucursal.upper(), 'cliente_marca': marca.upper(), 'latitud': lat, 'longitud': lng, 'estado': est_res.upper() if est_res else estado.upper(), 'zona_localidad': loc_res.upper() if loc_res else localidad.upper(), 'direccion_completa': dire if dire else "NO ENCONTRADA", 'estatus_visita': 'PENDIENTE', 'tipo_visita': 'STANDARD'}
                    if lat is not None and lng is not None: exitosos.append(fila)
                    else: fallidos.append(fila)
                conn.close()
                progreso.empty()
                st.session_state.df_exitosos = pd.DataFrame(exitosos)
                st.session_state.df_cuarentena = pd.DataFrame(fallidos)
                st.session_state.geo_procesado = True
                st.rerun()

    if st.session_state.geo_procesado:
        if not st.session_state.df_duplicados.empty:
            st.warning(f"⚠️ {len(st.session_state.df_duplicados)} ignoradas (Ya existen).")
        c1, c2 = st.columns(2)
        with c1: st.success(f"✅ {len(st.session_state.df_exitosos)} Enriquecidas")
        with c2: st.error(f"🚨 {len(st.session_state.df_cuarentena)} en Cuarentena")
        if not st.session_state.df_cuarentena.empty:
            st.markdown("### 🏥 Cuarentena Manual")
            df_editado = st.data_editor(st.session_state.df_cuarentena[['id_sucursal', 'cliente_marca', 'sucursal_nombre', 'latitud', 'longitud', 'direccion_completa']], num_rows="dynamic", use_container_width=True)
            if st.button("💾 Rescatar"):
                rescatados, siguen_mal = [], []
                df_completo = st.session_state.df_cuarentena.copy()
                for i, row in df_editado.iterrows():
                    lat_val, lon_val, dir_val = row['latitud'], row['longitud'], row['direccion_completa']
                    if pd.notna(lat_val) and pd.notna(lon_val) and str(lat_val).strip() != "":
                        fila = df_completo.iloc[i].copy(); fila['latitud'], fila['longitud'], fila['direccion_completa'] = float(lat_val), float(lon_val), str(dir_val)
                        rescatados.append(fila.to_dict())
                    else: siguen_mal.append(df_completo.iloc[i].to_dict())
                if rescatados:
                    st.session_state.df_exitosos = pd.concat([st.session_state.df_exitosos, pd.DataFrame(rescatados)], ignore_index=True)
                st.session_state.df_cuarentena = pd.DataFrame(siguen_mal)
                st.rerun()
        if not st.session_state.df_exitosos.empty:
            st.markdown("### 🚀 Acciones Finales")
            st.markdown(renderizar_tabla_html(st.session_state.df_exitosos), unsafe_allow_html=True)
            col_act1, col_act2 = st.columns(2)
            with col_act1:
                output = io.BytesIO()
                with pd.ExcelWriter(output, engine='openpyxl') as writer: st.session_state.df_exitosos.to_excel(writer, index=False)
                st.download_button(label="💾 Guardar .xlsx", data=output.getvalue(), file_name="Base_Clientes.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
            with col_act2:
                if st.button("⚡ Cargar a Base de Datos"):
                    inyectar_a_base_maestra_11_campos(st.session_state.df_exitosos)
                    st.session_state.df_exitosos = pd.DataFrame(); st.session_state.geo_procesado = False
        st.write("---")
        if st.button("🔄 Reiniciar Módulo"):
            st.session_state.geo_procesado = False; st.rerun()