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
import streamlit.components.v1 as components

try:
    import plotly.express as px
except ImportError:
    st.error("⚠️ Falta instalar Plotly. Abre tu terminal y ejecuta: pip install plotly")
    st.stop()

# 🚀 MOTOR DE IA: GROQ (GRATIS) & PDF
try:
    from openai import OpenAI
    from fpdf import FPDF
except ImportError:
    st.error("⚠️ Faltan los motores de IA y PDF. Abre tu terminal y ejecuta: pip install openai fpdf2")
    st.stop()

# 🌟 CONFIGURACIÓN INICIAL
st.set_page_config(page_title="RUTAS-QSR Dashboard", layout="wide", initial_sidebar_state="expanded")
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# ☁️ HERRAMIENTAS CLOUD
from datos import cargar_inventario_maestro, obtener_sucursales_pendientes, inyectar_nuevas_sucursales, actualizar_estatus_sucursal

try:
    from core.simulacion import simular_ruta_del_dia, calcular_distancia_haversine
except ImportError:
    from simulacion import simular_ruta_del_dia, calcular_distancia_haversine

try:
    from core.motor_logistico import generar_clusters_geograficos, optimizar_secuencia_por_proximidad
except ImportError:
    from motor_logistico import generar_clusters_geograficos, optimizar_secuencia_por_proximidad

# 🛡️ BLINDAJE DE SESIÓN Y SEGURIDAD
if 'auth_inventario' not in st.session_state:
    st.session_state.auth_inventario = False

if 'diaria_simulada' not in st.session_state:
    st.session_state.diaria_simulada = False
    st.session_state.diaria_visitas_final = []
    st.session_state.diaria_puntos_mapa = []
    st.session_state.diaria_coords_viaje = []
    st.session_state.diaria_ruta_n = 1
    st.session_state.diaria_alcaldia = ""

if 'radial_simulada' not in st.session_state:
    st.session_state.radial_simulada = False
    st.session_state.radial_visitas_final = []
    st.session_state.radial_puntos_mapa = []
    st.session_state.radial_coords_viaje = []
    st.session_state.radial_pivote = ""
    st.session_state.radial_lat_piv = 0.0
    st.session_state.radial_lon_piv = 0.0
    st.session_state.radial_radio = 0.0

if 'custom_simulada' not in st.session_state:
    st.session_state.custom_simulada = False
    st.session_state.custom_visitas_final = []
    st.session_state.custom_puntos_mapa = []
    st.session_state.custom_coords_viaje = []

if 'geo_procesado' not in st.session_state:
    st.session_state.geo_procesado = False
    st.session_state.df_exitosos = pd.DataFrame()
    st.session_state.df_cuarentena = pd.DataFrame()
    st.session_state.df_duplicados = pd.DataFrame()

# 🎨 ESTILOS CSS
st.markdown("""
    <style>
    .main h1 { color: #002F6C; font-weight: 700; font-size: 1.8rem; }
    .stButton>button { background-color: #002F6C; color: white; border-radius: 6px; border: none; padding: 0.5rem 1rem; font-weight: bold; width: 100%; }
    .stButton>button:hover { background-color: #004B93; color: white; }
    div[data-testid="stExpander"] { border: 1px solid #002F6C; border-radius: 6px; }
    div[data-testid="stMetric"] { background-color: #f0f4f8; padding: 10px; border-radius: 6px; border-left: 5px solid #002F6C; }
    table.dataframe-renderizada { width: 100% !important; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; margin: 10px 0; }
    table.dataframe-renderizada th { background-color: #002F6C !important; color: white !important; font-weight: bold; padding: 10px; text-align: left; white-space: nowrap; }
    table.dataframe-renderizada td { padding: 8px 10px; border-bottom: 1px solid #e0e0e0; white-space: nowrap; }
    .contenedor-tabla-scroll { width: 100%; overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 4px; margin-bottom: 15px; background-color: white; }
    </style>
""", unsafe_allow_html=True)

st.title("🚗 Panel de Control Logístico | RUTAS-QSR")

def renderizar_tabla_html(df):
    if df is None or df.empty: return ""
    return f'<div class="contenedor-tabla-scroll">{df.to_html(classes="dataframe-renderizada", index=False, escape=False)}</div>'

def renderizar_mapa_seguro(mapa_folium, alto=450):
    mapa_html = mapa_folium._repr_html_()
    components.html(mapa_html, height=alto, scrolling=True)

def generar_link_google_maps(puntos_coords):
    if not puntos_coords or len(puntos_coords) < 1:
        return "#"
    base_url = "https://www.google.com/maps/dir/"
    segmentos = [f"{lat},{lon}" for lat, lon in puntos_coords]
    return base_url + "/".join(segmentos)

def buscar_datos_osm_hibrido(marca, sucursal, localidad, estado):
    headers = {'User-Agent': 'RutasQSR_HybridAgent/1.0'}
    consultas = [f"{marca} {sucursal} {localidad} {estado} Mexico", f"{marca} {sucursal} {estado} Mexico", f"{marca} {sucursal} Mexico"]
    for query in consultas:
        q_str = re.sub(' +', ' ', query).strip()
        url = f"https://nominatim.openstreetmap.org/search?q={urllib.parse.quote(q_str)}&format=json&limit=1&addressdetails=1"
        try:
            time.sleep(1.2)
            res = requests.get(url, headers=headers, timeout=10).json()
            if res:
                data = res[0]
                lat, lng = float(data['lat']), float(data['lon'])
                direccion = data.get('display_name', f"{sucursal}, {localidad}")
                addr = data.get('address', {})
                est_res = addr.get('state', '').upper()
                loc_res = addr.get('city', addr.get('town', addr.get('municipality', localidad))).upper()
                return lat, lng, direccion, est_res if est_res else estado, loc_res if loc_res else localidad
        except: pass
    return None, None, None, None, None

def obtener_ruta_vial_real(puntos_coordenadas):
    if len(puntos_coordenadas) < 2: return puntos_coordenadas
    locs = ";".join([f"{lon},{lat}" for lat, lon in puntos_coordenadas])
    try:
        r = requests.get(f"http://router.project-osrm.org/route/v1/driving/{locs}?overview=full&geometries=geojson", timeout=5)
        if r.status_code == 200 and 'routes' in r.json() and r.json()['routes']:
            return [[lat, lon] for lon, lat in r.json()['routes'][0]['geometry']['coordinates']]
    except: pass
    return puntos_coordenadas

def crear_mapa_base(puntos_marcadores, ruta_linea=None, color_linea="#002F6C"):
    if not puntos_marcadores: 
        return folium.Map(location=[19.4326, -99.1332], zoom_start=11)
    
    m = folium.Map(location=[float(puntos_marcadores[0]['lat']), float(puntos_marcadores[0]['lon'])], zoom_start=11)
    lats, lons = [], []
    
    for p in puntos_marcadores:
        lat_f, lon_f = float(p['lat']), float(p['lon'])
        lats.append(lat_f); lons.append(lon_f)
        if p['idx'] == 0:
            c, i, txt = "red", "home", f"<b>{p['name']}</b><br>Punto de Partida"
        elif p['idx'] == "Pivote":
            c, i, txt = "purple", "star", f"<b>{p['name']}</b><br>Centro Radial"
        else:
            c, i, txt = "blue", "info-sign", f"<b>{p['name']}</b><br>Orden: {p['idx']}"
        folium.Marker(location=[lat_f, lon_f], popup=txt, icon=folium.Icon(color=c, icon=i)).add_to(m)
        
    if ruta_linea and len(ruta_linea) > 1:
        coords_limpias = [[float(coord[0]), float(coord[1])] for coord in ruta_linea]
        folium.PolyLine(coords_limpias, color=color_linea, weight=4.5, opacity=0.85).add_to(m)
        for coord in coords_limpias: 
            lats.append(coord[0])
            lons.append(coord[1])
            
    if lats and lons: 
        m.fit_bounds([[min(lats), min(lons)], [max(lats), max(lons)]])
    return m

st.sidebar.header("☁️ Ecosistema Cloud Activo")
st.sidebar.info("Tu base de datos ahora está sincronizada en tiempo real con Google Sheets.")

modulo_principal = st.radio(
    "Selecciona Módulo de Trabajo:", 
    [
        "🗺️ Planeación y Ruteo Inteligente", 
        "📋 Control de Inventario y Visitas", 
        "📊 Dashboard de KPIs y Analítica Ejecutiva"
    ], 
    horizontal=True
)

if modulo_principal == "🗺️ Planeación y Ruteo Inteligente":
    with st.spinner("Descargando mapa logístico desde la nube..."):
        df_full = cargar_inventario_maestro()
    
    if df_full.empty or 'estado' not in df_full.columns:
        st.warning("⚠️ La base de datos en Google Sheets está vacía o mal estructurada.")
    else:
        estados_disponibles = sorted([str(e) for e in df_full['estado'].dropna().unique() if str(e).strip() != ''])
        st.markdown("### 🏢 Opciones de Ruteo Inteligente")
        
        tab_vrp, tab_radial, tab_custom = st.tabs([
            "⚡ Circuitos Automáticos (VRP Global)", 
            "🎯 Diseñador Radial", 
            "🔧 Rutas Personalizables (Libres)"
        ])
        
        with tab_vrp:
            visitas_jornada = st.slider("Objetivo de visitas por jornada:", 4, 12, 6)
            hora_inicio_diaria = st.select_slider("Hora de Inicio:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00")
            
            st.markdown("#### 📍 Configuración de Salida")
            opcion_origen = st.radio("Punto de Partida:", ["🏠 CASA", "🏢 ECOLAB (Cuautitlán)", "📍 Personalizado"], horizontal=True)
            lat_c, lon_c, nombre_origen_final = 19.549965629588566, -99.23691334673492, "🏠 CASA"
            if opcion_origen == "🏢 ECOLAB (Cuautitlán)":
                lat_c, lon_c, nombre_origen_final = 19.655381063145374, -99.19368263138871, "🏢 ECOLAB (Cuautitlán)"
            elif opcion_origen == "📍 Personalizado":
                col_p1, col_p2 = st.columns(2)
                with col_p1: nombre_origen_final = st.text_input("Nombre del Hotel / Origen:", value="Hotel Guanajuato")
                with col_p2: coord_input = st.text_input("Pegar Latitud, Longitud (Ej: 21.0181, -101.2580):", value="")
                if coord_input:
                    try: lat_c, lon_c = map(float, coord_input.split(",")); st.success(f"✅ Satélite fijado: {lat_c}, {lon_c}")
                    except: st.error("⚠️ Formato inválido.")
            
            st.markdown("---")
            zona_general_elegida = st.selectbox("Zona General:", estados_disponibles)
            df_loc_full = df_full[df_full['estado'] == zona_general_elegida]
            lista_locs = sorted([str(l) for l in df_loc_full['zona_localidad'].dropna().unique() if str(l).strip() != ''])
            
            if lista_locs:
                alcaldia_elegida = st.selectbox("Alcaldía objetivo:", ["TODAS LAS LOCALIDADES"] + lista_locs, index=0)
                
                df_pendientes = obtener_sucursales_pendientes()
                if alcaldia_elegida == "TODAS LAS LOCALIDADES":
                    df_pool_sec = df_pendientes[df_pendientes['estado'] == zona_general_elegida]
                else:
                    df_pool_sec = df_pendientes[(df_pendientes['estado'] == zona_general_elegida) & (df_pendientes['zona_localidad'] == alcaldia_elegida)]
                
                if not df_pool_sec.empty:
                    total_rutas = max(1, math.ceil(len(df_pool_sec) / visitas_jornada))
                    ruta_elegida = st.selectbox(f"Circuitos ({len(df_pool_sec)} PENDIENTES):", list(range(1, total_rutas + 1)))
                    if st.button("🗺️ Desplegar Circuito Diario"):
                        rutas_maestras = generar_clusters_geograficos(lat_c, lon_c, df_pool_sec.to_dict(orient='records'), visitas_jornada)
                        bloque = rutas_maestras[int(ruta_elegida) - 1] if rutas_maestras else []
                        visitas_calc, _, _ = simular_ruta_del_dia(bloque, hora_inicio_diaria, len(bloque), False, "Base", (lat_c, lon_c))
                        if visitas_calc:
                            st.session_state.diaria_simulada = True; st.session_state.diaria_alcaldia = alcaldia_elegida
                            st.session_state.diaria_visitas_final = []; st.session_state.diaria_coords_viaje = [(lat_c, lon_c)]
                            st.session_state.diaria_puntos_mapa = [{"lat": lat_c, "lon": lon_c, "name": f"📍 ORIGEN ({nombre_origen_final})", "idx": 0}]
                            tiendas_incluidas = 0
                            for idx, v in enumerate(visitas_calc):
                                orig = next(item for item in bloque if str(item['id_sucursal']) == str(v.get('ID Sucursal', v.get('ID', ''))))
                                h_llegada, h_salida = v.get("ETA Llegada", ""), v.get("ETA Salida", v.get("Hora Salida", ""))
                                if h_salida > "19:00":
                                    st.error(f"🛑 Corte Estricto: La ruta se detuvo antes de {orig['sucursal_nombre']}. La salida proyectada ({h_salida}) supera las 19:00 hrs.")
                                    break
                                if h_salida > "18:00": st.warning(f"⚠️ Excepción Operativa: La sucursal {orig['sucursal_nombre']} terminaría a las {h_salida} hrs.")
                                st.session_state.diaria_visitas_final.append({
                                    "ID": orig['id_sucursal'], "Sec": tiendas_incluidas + 1, "Marca": orig['cliente_marca'], 
                                    "Sucursal": orig['sucursal_nombre'], "Llegada": h_llegada, "Salida": h_salida, 
                                    "Dirección": orig['direccion_completa'], "Histórico Visitas": orig['visitas_realizadas']
                                })
                                st.session_state.diaria_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {orig['sucursal_nombre']}", "idx": tiendas_incluidas + 1})
                                st.session_state.diaria_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))
                                tiendas_incluidas += 1
                else: st.success("✅ Todas las tiendas en esta zona ya están COMPLETADAS.")

            if st.session_state.diaria_simulada:
                st.write("---\n### 📋 Itinerario Diario")
                st.markdown(renderizar_tabla_html(pd.DataFrame(st.session_state.diaria_visitas_final)), unsafe_allow_html=True)
                
                link_gmaps_diario = generar_link_google_maps(st.session_state.diaria_coords_viaje)
                st.markdown(f'<a href="{link_gmaps_diario}" target="_blank"><button style="background-color:#1E88E5; color:white; padding:10px 20px; border:none; border-radius:5px; font-weight:bold; cursor:pointer; width:100%;">🗺️ Abrir Ruta Completa en Google Maps</button></a>', unsafe_allow_html=True)
                st.write("")

                ids_en_ruta = [item["ID"] for item in st.session_state.diaria_visitas_final]
                completadas_sel = st.multiselect("Marcar completadas (Se sumará +1 a su histórico):", options=ids_en_ruta, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.diaria_visitas_final if item["ID"] == x))
                if st.button("☁️ Guardar Seleccionadas como COMPLETADAS"):
                    with st.spinner("Subiendo actualizaciones a la nube..."):
                        for id_s in completadas_sel:
                            actualizar_estatus_sucursal(id_s, "COMPLETADA")
                    st.session_state.diaria_simulada = False; st.rerun()
                
                mapa_diario = crear_mapa_base(st.session_state.diaria_puntos_mapa, obtener_ruta_vial_real(st.session_state.diaria_coords_viaje))
                renderizar_mapa_seguro(mapa_diario, alto=450)

        with tab_radial:
            col_rv1, col_rv2 = st.columns(2)
            with col_rv1: visitas_jornada_rad = st.slider("Objetivo visitas:", 4, 12, 6, key="rad_visitas")
            with col_rv2: hora_inicio_diaria_rad = st.select_slider("Hora Inicio:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00", key="rad_hora")

            st.markdown("#### 📍 Configuración de Salida")
            opcion_origen_rad = st.radio("Punto Partida:", ["🏠 CASA", "🏢 ECOLAB", "📍 Personalizado"], horizontal=True, key="rad_origen")
            lat_c_rad, lon_c_rad, nombre_origen_rad_final = 19.549965629588566, -99.23691334673492, "🏠 CASA"
            if opcion_origen_rad == "🏢 ECOLAB":
                lat_c_rad, lon_c_rad, nombre_origen_rad_final = 19.655381063145374, -99.19368263138871, "🏢 ECOLAB (Cuautitlán)"
            elif opcion_origen_rad == "📍 Personalizado":
                col_pr1, col_pr2 = st.columns(2)
                with col_pr1: nombre_origen_rad_final = st.text_input("Nombre Hotel/Origen:", value="Hotel Gto", key="rad_nombre")
                with col_pr2: coord_input_rad = st.text_input("Latitud, Longitud:", value="", key="rad_coord")
                if coord_input_rad:
                    try: lat_c_rad, lon_c_rad = map(float, coord_input_rad.split(",")); st.success(f"✅ Satélite fijado.")
                    except: pass
            
            st.markdown("---")
            zona_general_rad = st.selectbox("Zona (Estado):", estados_disponibles, key="rad_zona")
            df_loc_rad_full = df_full[df_full['estado'] == zona_general_rad]
            lista_locs_rad = sorted([str(l) for l in df_loc_rad_full['zona_localidad'].dropna().unique() if str(l).strip() != ''])
            
            if lista_locs_rad:
                alcaldia_rad = st.selectbox("Localidad:", ["TODAS"] + lista_locs_rad, key="rad_alc")
                
                df_all_pending = obtener_sucursales_pendientes()
                if alcaldia_rad == "TODAS":
                    df_pivotes_pool = df_all_pending[df_all_pending['estado'] == zona_general_rad]
                else:
                    df_pivotes_pool = df_all_pending[(df_all_pending['estado'] == zona_general_rad) & (df_all_pending['zona_localidad'] == alcaldia_rad)]
                
                if not df_pivotes_pool.empty:
                    col1, col2 = st.columns([2, 1])
                    with col1: tienda_pivote_nombre = st.selectbox("Pivote (Centro Radar):", df_pivotes_pool['sucursal_nombre'].tolist(), key="rad_piv")
                    with col2: 
                        radio_km = st.slider("Radio (Km):", min_value=5.0, max_value=100.0, value=15.0, step=5.0, key="rad_km")
                    if st.button("🔍 Escanear Perímetro y Generar Ruta", key="btn_rad"):
                        pivote = df_pivotes_pool[df_pivotes_pool['sucursal_nombre'] == tienda_pivote_nombre].iloc[0]
                        lat_pivote, lon_pivote = float(pivote['latitud']), float(pivote['longitud'])
                        atrapadas = [row.to_dict() for idx, row in df_all_pending.iterrows() if row['sucursal_nombre'] != tienda_pivote_nombre and calcular_distancia_haversine(lat_pivote, lon_pivote, float(row['latitud']), float(row['longitud'])) <= radio_km]
                        if atrapadas:
                            bloque = optimizar_secuencia_por_proximidad(lat_c_rad, lon_c_rad, atrapadas)[:visitas_jornada_rad]
                            visitas_calc, _, _ = simular_ruta_del_dia(bloque, hora_inicio_diaria_rad, len(bloque), False, "Base", (lat_c_rad, lon_c_rad))
                            if visitas_calc:
                                st.session_state.radial_simulada = True; st.session_state.radial_pivote = tienda_pivote_nombre
                                st.session_state.radial_lat_piv, st.session_state.radial_lon_piv, st.session_state.radial_radio = lat_pivote, lon_pivote, radio_km
                                st.session_state.radial_visitas_final = []; st.session_state.radial_coords_viaje = [(lat_c_rad, lon_c_rad)]
                                
                                st.session_state.radial_puntos_mapa = [
                                    {"lat": lat_c_rad, "lon": lon_c_rad, "name": f"📍 ORIGEN", "idx": 0}, 
                                    {"lat": lat_pivote, "lon": lon_pivote, "name": f"🌟 PIVOTE: {tienda_pivote_nombre}", "idx": "Pivote"}
                                ]
                                
                                tiend_inc = 0
                                for idx, v in enumerate(visitas_calc):
                                    orig = next(item for item in bloque if str(item['id_sucursal']) == str(v.get('ID', v.get('ID Sucursal', ''))))
                                    hl, hs = v.get("ETA Llegada", ""), v.get("ETA Salida", v.get("Hora Salida", ""))
                                    if hs > "19:00": st.error(f"🛑 Corte Estricto antes de {orig['sucursal_nombre']}. Supera las 19:00."); break
                                    if hs > "18:00": st.warning(f"⚠️ Excepción Operativa: {orig['sucursal_nombre']} terminaría a las {hs} hrs.")
                                    st.session_state.radial_visitas_final.append({
                                        "ID": orig['id_sucursal'], "Sec": tiend_inc+1, "Marca": orig['cliente_marca'], 
                                        "Sucursal": orig['sucursal_nombre'], "Llegada": hl, "Salida": hs, 
                                        "Dirección": orig['direccion_completa'], "Histórico Visitas": orig['visitas_realizadas']
                                    })
                                    st.session_state.radial_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {orig['sucursal_nombre']}", "idx": tiend_inc+1})
                                    st.session_state.radial_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))
                                    tiend_inc += 1
            if st.session_state.radial_simulada:
                st.markdown(renderizar_tabla_html(pd.DataFrame(st.session_state.radial_visitas_final)), unsafe_allow_html=True)
                
                link_gmaps_radial = generar_link_google_maps(st.session_state.radial_coords_viaje)
                st.markdown(f'<a href="{link_gmaps_radial}" target="_blank"><button style="background-color:#1E88E5; color:white; padding:10px 20px; border:none; border-radius:5px; font-weight:bold; cursor:pointer; width:100%;">🗺️ Abrir Ruta Radial en Google Maps</button></a>', unsafe_allow_html=True)
                st.write("")

                ids_en_ruta = [item["ID"] for item in st.session_state.radial_visitas_final]
                completadas_sel = st.multiselect("Marcar completadas (+1 visita):", options=ids_en_ruta, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.radial_visitas_final if item["ID"] == x))
                if st.button("☁️ Guardar Seleccionadas como COMPLETADAS", key="btn_save_rad"):
                    with st.spinner("Sincronizando con Google Sheets..."):
                        for id_s in completadas_sel:
                            actualizar_estatus_sucursal(id_s, "COMPLETADA")
                    st.session_state.radial_simulada = False
                    st.rerun()
                mapa_rad = crear_mapa_base(st.session_state.radial_puntos_mapa, obtener_ruta_vial_real(st.session_state.radial_coords_viaje))
                folium.Circle(location=[st.session_state.radial_lat_piv, st.session_state.radial_lon_piv], radius=st.session_state.radial_radio * 1000, color='red', weight=2, fill=True, fillOpacity=0.1).add_to(mapa_rad)
                
                renderizar_mapa_seguro(mapa_rad, alto=450)

        with tab_custom:
            st.markdown("### 🔧 Diseñador de Rutas Personalizables (Libre de Historial)")
            st.info("Este diseñador radial te permite generar rutas sin restricciones: ignora el estatus previo de visitas y te permite agregar, quitar o modificar sucursales libremente.")
            
            col_cu1, col_cu2 = st.columns(2)
            with col_cu1: objetivo_visitas_custom = st.slider("Objetivo de visitas (Default 6):", 1, 20, 6, key="custom_obj")
            with col_cu2: hora_inicio_custom = st.select_slider("Hora de Inicio:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00", key="custom_hora")

            st.markdown("#### 📍 Configuración de Salida")
            opcion_origen_custom = st.radio("Punto Partida:", ["🏠 CASA", "🏢 ECOLAB", "📍 Personalizado"], horizontal=True, key="custom_orig_opt")
            lat_c_cust, lon_c_cust, nombre_origen_cust_final = 19.549965629588566, -99.23691334673492, "🏠 CASA"
            if opcion_origen_custom == "🏢 ECOLAB":
                lat_c_cust, lon_c_cust, nombre_origen_cust_final = 19.655381063145374, -99.19368263138871, "🏢 ECOLAB (Cuautitlán)"
            elif opcion_origen_custom == "📍 Personalizado":
                col_cu_p1, col_cu_p2 = st.columns(2)
                with col_cu_p1: nombre_origen_cust_final = st.text_input("Nombre Hotel/Origen:", value="Hotel Base", key="custom_nom_orig")
                with col_cu_p2: coord_input_cust = st.text_input("Latitud, Longitud:", value="", key="custom_coord_orig")
                if coord_input_cust:
                    try: lat_c_cust, lon_c_cust = map(float, coord_input_cust.split(",")); st.success("✅ Satélite fijado.")
                    except: pass
            
            st.markdown("---")
            zona_general_cust = st.selectbox("Zona (Estado):", estados_disponibles, key="custom_zona")
            df_loc_cust_full = df_full[df_full['estado'] == zona_general_cust]
            lista_locs_cust = sorted([str(l) for l in df_loc_cust_full['zona_localidad'].dropna().unique() if str(l).strip() != ''])
            
            if lista_locs_cust:
                alcaldia_cust = st.selectbox("Localidad:", ["TODAS"] + lista_locs_cust, key="custom_alc")
                
                if alcaldia_cust == "TODAS":
                    df_all_sucursales_zona = df_full[df_full['estado'] == zona_general_cust]
                else:
                    df_all_sucursales_zona = df_full[(df_full['estado'] == zona_general_cust) & (df_full['zona_localidad'] == alcaldia_cust)]
                
                if not df_all_sucursales_zona.empty:
                    col_piv1, col_piv2 = st.columns([2, 1])
                    with col_piv1: pivote_custom_nombre = st.selectbox("Pivote (Centro Radar Base):", df_all_sucursales_zona['sucursal_nombre'].tolist(), key="custom_piv")
                    with col_piv2: 
                        radio_km_cust = st.slider("Radio Ideal (Km):", min_value=5.0, max_value=100.0, value=20.0, step=5.0, key="custom_km")
                    
                    pivote_obj = df_all_sucursales_zona[df_all_sucursales_zona['sucursal_nombre'] == pivote_custom_nombre].iloc[0]
                    lat_piv_c, lon_piv_c = float(pivote_obj['latitud']), float(pivote_obj['longitud'])
                    
                    sugeridas_radio = [row.to_dict() for idx, row in df_all_sucursales_zona.iterrows() if row['sucursal_nombre'] != pivote_custom_nombre and calcular_distancia_haversine(lat_piv_c, lon_piv_c, float(row['latitud']), float(row['longitud'])) <= radio_km_cust]
                    
                    st.markdown("#### 🛠️ Editor y Selector Manual de Ruta")
                    st.info("Puedes modificar la lista de abajo libremente: quita las que no quieras o agrega más sucursales de la zona senza restricciones.")
                    
                    ids_sugeridos_defaults = [s['id_sucursal'] for s in optimizar_secuencia_por_proximidad(lat_c_cust, lon_c_cust, sugeridas_radio)[:objetivo_visitas_custom]]
                    
                    sucursales_seleccionadas_ids = st.multiselect(
                        "Sucursales incluidas en la ruta (Ordenadas o editables):",
                        options=df_all_sucursales_zona['id_sucursal'].tolist(),
                        default=ids_sugeridos_defaults,
                        format_func=lambda x: f"[{df_all_sucursales_zona[df_all_sucursales_zona['id_sucursal']==x]['cliente_marca'].values[0]}] {df_all_sucursales_zona[df_all_sucursales_zona['id_sucursal']==x]['sucursal_nombre'].values[0]}"
                    )
                    
                    if st.button("🚀 Generar Ruta Personalizada y Mapa Vial", key="btn_custom_generar"):
                        if not sucursales_seleccionadas_ids:
                            st.warning("⚠️ Debes seleccionar al menos una sucursal para la ruta.")
                        else:
                            bloque_custom = [df_all_sucursales_zona[df_all_sucursales_zona['id_sucursal'] == sid].iloc[0].to_dict() for sid in sucursales_seleccionadas_ids]
                            bloque_optimizado = optimizar_secuencia_por_proximidad(lat_c_cust, lon_c_cust, bloque_custom)
                            visitas_calc_c, _, _ = simular_ruta_del_dia(bloque_optimizado, hora_inicio_custom, len(bloque_optimizado), False, "Base", (lat_c_cust, lon_c_cust))
                            
                            if visitas_calc_c:
                                st.session_state.custom_simulada = True
                                st.session_state.custom_visitas_final = []
                                st.session_state.custom_coords_viaje = [(lat_c_cust, lon_c_cust)]
                                st.session_state.custom_puntos_mapa = [
                                    {"lat": lat_c_cust, "lon": lon_c_cust, "name": f"📍 ORIGEN ({nombre_origen_cust_final})", "idx": 0},
                                    {"lat": lat_piv_c, "lon": lon_piv_c, "name": f"🌟 PIVOTE: {pivote_custom_nombre}", "idx": "Pivote"}
                                ]
                                
                                for tiend_idx, v in enumerate(visitas_calc_c):
                                    orig = next(item for item in bloque_optimizado if str(item['id_sucursal']) == str(v.get('ID', v.get('ID Sucursal', ''))))
                                    hl, hs = v.get("ETA Llegada", ""), v.get("ETA Salida", v.get("Hora Salida", ""))
                                    st.session_state.custom_visitas_final.append({
                                        "ID": orig['id_sucursal'], "Sec": tiend_idx+1, "Marca": orig['cliente_marca'], 
                                        "Sucursal": orig['sucursal_nombre'], "Llegada": hl, "Salida": hs, 
                                        "Dirección": orig['direccion_completa'], "Histórico Visitas": orig['visitas_realizadas']
                                    })
                                    st.session_state.custom_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {orig['sucursal_nombre']}", "idx": tiend_idx+1})
                                    st.session_state.custom_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))
                
                if st.session_state.custom_simulada:
                    st.write("---")
                    st.markdown("### 📋 Itinerario de la Ruta Personalizada")
                    st.markdown(renderizar_tabla_html(pd.DataFrame(st.session_state.custom_visitas_final)), unsafe_allow_html=True)
                    
                    link_gmaps_custom = generar_link_google_maps(st.session_state.custom_coords_viaje)
                    st.markdown(f'<a href="{link_gmaps_custom}" target="_blank"><button style="background-color:#1E88E5; color:white; padding:10px 20px; border:none; border-radius:5px; font-weight:bold; cursor:pointer; width:100%;">🗺️ Abrir Ruta Personalizada en Google Maps</button></a>', unsafe_allow_html=True)
                    st.write("")

                    mapa_cust = crear_mapa_base(st.session_state.custom_puntos_mapa, obtener_ruta_vial_real(st.session_state.custom_coords_viaje))
                    folium.Circle(location=[lat_piv_c, lon_piv_c], radius=radio_km_cust * 1000, color='purple', weight=2, fill=True, fillOpacity=0.08).add_to(mapa_cust)
                    
                    renderizar_mapa_seguro(mapa_cust, alto=450)

# ==========================================
# 🔒 MÓDULO DE INVENTARIO CON CONTRASEÑA
# ==========================================
elif modulo_principal == "📋 Control de Inventario y Visitas":
    st.markdown("### 📋 Módulo Administrativo de Inventario")
    
    if not st.session_state.auth_inventario:
        st.warning("🔒 Acceso Restringido. Esta sección es exclusiva para Administradores.")
        col_pwd1, col_pwd2 = st.columns([2, 1])
        with col_pwd1:
            pwd_input = st.text_input("Ingresa la contraseña maestra:", type="password")
        with col_pwd2:
            st.write("")
            st.write("")
            if st.button("🔑 Desbloquear Panel"):
                # ---> AQUÍ ESTÁ TU CONTRASEÑA (Cámbiala si lo deseas) <---
                if pwd_input == "QsrAdmin2024!":
                    st.session_state.auth_inventario = True
                    st.rerun()
                elif pwd_input != "":
                    st.error("❌ Contraseña incorrecta.")
    else:
        # Botón para cerrar sesión por seguridad
        col_btn1, col_btn2 = st.columns([3, 1])
        with col_btn2:
            if st.button("🔒 Cerrar Sesión Segura"):
                st.session_state.auth_inventario = False
                st.rerun()
        
        st.write("---")
        # --- CONTENIDO ORIGINAL DESBLOQUEADO ---
        tab_vista, tab_edicion = st.tabs(["👁️ Vista General", "✏️ Editor Maestro de Base de Datos"])
        with tab_vista:
            with st.spinner("Consultando Google Sheets..."):
                df_inv = cargar_inventario_maestro()
                if not df_inv.empty:
                    st.markdown(renderizar_tabla_html(df_inv[['id_sucursal', 'cliente_marca', 'sucursal_nombre', 'estado', 'zona_localidad', 'estatus_visita', 'visitas_realizadas']]), unsafe_allow_html=True)
        with tab_edicion:
            st.info("☁️ **MODO CLOUD ACTIVO**: Para proteger la integridad de tus datos y evitar errores en la nube, la edición masiva o eliminación de registros se realiza directamente en tu archivo de Google Sheets.")
            st.markdown("[🔗 **HAZ CLIC AQUÍ PARA ABRIR TU BASE DE DATOS EN GOOGLE SHEETS**](https://docs.google.com/spreadsheets/d/1ckxKCRYrRdUAL6-jS0sfmgeTWt_-0b5bDzPky6etgbs/edit?usp=drive_web)", unsafe_allow_html=True)
            st.write("*(Los cambios que guardes allá se reflejarán en esta aplicación y en tu celular al instante).*")

elif modulo_principal == "📊 Dashboard de KPIs y Analítica Ejecutiva":
    st.markdown("### 📊 Dashboard Ejecutivo")
    
    try:
        from etl_kpis import extraer_y_transformar_datos, DB_KPIS
    except ImportError:
        st.error("⚠️ No se encontró el módulo `etl_kpis.py`.")
        st.stop()

    st.sidebar.markdown("---")
    st.sidebar.markdown("### 💰 Variables Financieras")
    var_rendimiento = st.sidebar.number_input("Rendimiento (Km/L):", min_value=5.0, value=12.0, step=0.5)
    var_costo_litro = st.sidebar.number_input("Gasolina ($/L):", min_value=15.0, value=24.50, step=0.5)
    var_costo_mto = st.sidebar.number_input("Servicio (cada 15k):", min_value=1000.0, value=3500.0, step=100.0)
    var_sueldo_hora = st.sidebar.number_input("Sueldo FSM ($/Hr):", min_value=30.0, value=60.0, step=5.0)

    if st.sidebar.button("🔄 Recalcular Data Mart", type="primary"):
        with st.spinner("Procesando ETL..."):
            try:
                extraer_y_transformar_datos(rendimiento_km_l=var_rendimiento, costo_litro=var_costo_litro, costo_mto_15k=var_costo_mto, sueldo_hora=var_sueldo_hora)
                st.sidebar.success("✅ Actualizado.")
                time.sleep(1)
                st.rerun()
            except sqlite3.OperationalError:
                st.error("⚠️ Tu archivo `etl_kpis.py` aún intenta leer la base de datos vieja (SQLite). ¡Necesitamos refactorizar ese archivo a GSheets también!")
                st.stop()

    if not os.path.exists(DB_KPIS):
        st.info("ℹ️ No hay datos. Haz clic en 'Recalcular Data Mart'.")
    else:
        conn_kpi = sqlite3.connect(DB_KPIS)
        try:
            df_finanzas = pd.read_sql_query("SELECT * FROM kpis_financieros ORDER BY fecha_calculo DESC LIMIT 1", conn_kpi)
            df_avance = pd.read_sql_query("SELECT * FROM kpis_avance_operativo", conn_kpi)
        except:
            df_finanzas = pd.DataFrame(); df_avance = pd.DataFrame()
        conn_kpi.close()

        if not df_finanzas.empty and not df_avance.empty:
            
            tab_volumen, tab_finanzas, tab_ia = st.tabs(["🗺️ Operación y Cobertura (Gráficos)", "💰 Rentabilidad y Costos", "🤖 Briefing Ejecutivo (IA & PDF)"])

            with tab_volumen:
                df_avance['visitas_realizadas'] = pd.to_numeric(df_avance['visitas_realizadas']).fillna(0).astype(int)
                
                def clasificar_cumplimiento(v):
                    if v == 0: return '0 Visitas (Riesgo)'
                    elif v == 1: return '1 Visita (Progreso)'
                    else: return '2+ Visitas (Meta Lograda)'
                
                df_avance['Estado_Cumplimiento'] = df_avance['visitas_realizadas'].apply(clasificar_cumplimiento)
                colores_semaforo = {'0 Visitas (Riesgo)': '#ff4b4b', '1 Visita (Progreso)': '#ffc107', '2+ Visitas (Meta Lograda)': '#00c853'}

                total_t = len(df_avance)
                tiendas_rojas = len(df_avance[df_avance['visitas_realizadas'] == 0])
                tiendas_amarillas = len(df_avance[df_avance['visitas_realizadas'] == 1])
                tiendas_verdes = len(df_avance[df_avance['visitas_realizadas'] >= 2])
                
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Total Sucursales Base", f"{total_t:,}")
                m2.metric("🔴 0 Visitas", f"{tiendas_rojas:,}")
                m3.metric("🟡 1 Visita", f"{tiendas_amarillas:,}")
                m4.metric("🟢 2+ Visitas", f"{tiendas_verdes:,}")
                
                st.write("---")

                col_g1, col_g2 = st.columns(2)
                
                with col_g1:
                    st.markdown("**Visitas Totales vs Faltantes (Proporción)**")
                    conteo = df_avance['Estado_Cumplimiento'].value_counts().reset_index()
                    conteo.columns = ['Estatus', 'Total']
                    fig_donut = px.pie(conteo, values='Total', names='Estatus', hole=0.5, color='Estatus', color_discrete_map=colores_semaforo)
                    fig_donut.update_traces(textposition='inside', textinfo='percent+label')
                    fig_donut.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
                    st.plotly_chart(fig_donut, use_container_width=True)

                with col_g2:
                    st.markdown("**🏆 Esfuerzo Operativo por Marca (Sunburst)**")
                    st.info("Distribución jerárquica de visitas y estatus por marca.")
                    
                    fig_sun_marca = px.sunburst(
                        df_avance, 
                        path=['cliente_marca', 'Estado_Cumplimiento'], 
                        values='visitas_realizadas',
                        color='Estado_Cumplimiento',
                        color_discrete_map=colores_semaforo,
                        maxdepth=2
                    )
                    fig_sun_marca.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=380)
                    st.plotly_chart(fig_sun_marca, use_container_width=True)

                st.write("---")
                
                st.markdown("**🗺️ Radar de Cobertura por Estado y Localidad**")
                
                df_sunburst = df_avance.copy()
                df_sunburst['Pais'] = 'MÉXICO'
                
                fig_sun = px.sunburst(df_sunburst, path=['Pais', 'estado', 'zona_localidad', 'Estado_Cumplimiento'], color='Estado_Cumplimiento', color_discrete_map=colores_semaforo, maxdepth=3)
                fig_sun.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=550)
                st.plotly_chart(fig_sun, use_container_width=True)

                st.markdown("### 🗂️ Explorador de Datos y Auditoría de Zonas")
                st.info("Filtra rápidamente por Estado y Localidad para ver el detalle de cada sucursal de la zona seleccionada.")
                
                col_f1, col_f2 = st.columns(2)
                lista_estados = sorted(df_avance['estado'].dropna().unique().tolist())
                with col_f1:
                    estado_elegido = st.selectbox("1️⃣ Filtrar por Estado:", ["TODOS LOS ESTADOS"] + lista_estados)
                
                if estado_elegido != "TODOS LOS ESTADOS":
                    lista_locs = sorted(df_avance[df_avance['estado'] == estado_elegido]['zona_localidad'].dropna().unique().tolist())
                else:
                    lista_locs = sorted(df_avance['zona_localidad'].dropna().unique().tolist())
                    
                with col_f2:
                    loc_elegida = st.selectbox("2️⃣ Filtrar por Localidad (Alcaldía):", ["TODAS LAS LOCALIDADES"] + lista_locs)
                
                df_filtrado = df_avance.copy()
                if estado_elegido != "TODOS LOS ESTADOS":
                    df_filtrado = df_filtrado[df_filtrado['estado'] == estado_elegido]
                if loc_elegida != "TODAS LAS LOCALIDADES":
                    df_filtrado = df_filtrado[df_filtrado['zona_localidad'] == loc_elegida]
                    
                st.dataframe(
                    df_filtrado[['id_sucursal', 'cliente_marca', 'sucursal_nombre', 'estado', 'zona_localidad', 'visitas_realizadas', 'Estado_Cumplimiento']], 
                    use_container_width=True, 
                    hide_index=True
                )

            with tab_finanzas:
                row_fin = df_finanzas.iloc[0]
                st.markdown("#### 💵 Impacto Financiero en las Visitas Históricas")
                
                c1, c2, c3, c4 = st.columns(4)
                with c1: st.metric("⛽ Gasto Gasolina Estimado", f"${row_fin['costo_gasolina_mxn']:,.2f}")
                with c2: st.metric("🛠️ Provisión Mantenimiento", f"${row_fin['costo_mantenimiento_mxn']:,.2f}")
                with c3: st.metric("💰 Costo Total por Km (TCO)", f"${row_fin['tco_por_km_mxn']:,.2f}/km")
                with c4: st.metric("💸 Costo de Traslado (Técnico)", f"${row_fin['costo_trafico_mxn']:,.2f}")

                st.write("---")
                col_t1, col_t2 = st.columns([1, 1])
                with col_t1:
                    st.markdown("**⏱️ Distribución del Tiempo Operativo**")
                    datos_tiempo = pd.DataFrame({"Categoría": ["Tiempo Efectivo (En Tienda)", "Tiempo Muerto (Traslado)"], "Horas": [row_fin['tiempo_efectivo_hrs'], row_fin['tiempo_traslado_hrs']]})
                    fig_time = px.pie(datos_tiempo, values='Horas', names='Categoría', color='Categoría', color_discrete_map={'Tiempo Efectivo (En Tienda)':'#1976D2', 'Tiempo Muerto (Traslado)':'#B0BEC5'}, hole=0.4)
                    fig_time.update_traces(textposition='inside', textinfo='percent+label')
                    fig_time.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
                    st.plotly_chart(fig_time, use_container_width=True)
                    
                with col_t2:
                     st.info(f"""
                     **Resumen General del Periodo:**
                     * **Horas Trabajadas en Tienda:** {row_fin['tiempo_efectivo_hrs']} hrs (Genera Valor)
                     * **Horas al Volante (Tráfico):** {row_fin['tiempo_traslado_hrs']} hrs (Costo Hundido)
                     * **Total Visitas Completadas:** {row_fin['total_visitas']} tiendas
                     * **Distancia Total Recorrida:** {row_fin['distancia_total_km']} km
                     """)

            with tab_ia:
                st.markdown("### 📊 Dashboard Integral & Briefing Gerencial (C-Level)")
                st.write("Panel de resumen ejecutivo con visuales integrales y redacción analítica por Inteligencia Artificial listo para entrega directiva.")
                
                st.markdown("---")
                st.markdown("#### 🎯 Panel de Control Ejecutivo (KPI Scorecards Visuales)")
                
                df_avance['visitas_realizadas'] = pd.to_numeric(df_avance['visitas_realizadas']).fillna(0).astype(int)
                def clasificar_cumplimiento(v):
                    if v == 0: return '0 Visitas (Riesgo)'
                    elif v == 1: return '1 Visita (Progreso)'
                    else: return '2+ Visitas (Meta Lograda)'
                df_avance['Estado_Cumplimiento'] = df_avance['visitas_realizadas'].apply(clasificar_cumplimiento)
                colores_semaforo = {'0 Visitas (Riesgo)': '#ff4b4b', '1 Visita (Progreso)': '#ffc107', '2+ Visitas (Meta Lograda)': '#00c853'}

                row_fin = df_finanzas.iloc[0]
                total_historico = df_avance['visitas_realizadas'].sum()
                costo_total_op = row_fin['costo_gasolina_mxn'] + row_fin['costo_mantenimiento_mxn'] + row_fin['costo_trafico_mxn']
                tiendas_riesgo = len(df_avance[df_avance['visitas_realizadas'] == 0])
                tiendas_meta = len(df_avance[df_avance['visitas_realizadas'] >= 2])

                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.markdown("**1️⃣ Proporción de Cobertura en Sucursales**")
                    conteo_res = df_avance['Estado_Cumplimiento'].value_counts().reset_index()
                    conteo_res.columns = ['Estatus', 'Total']
                    fig_res_donut = px.pie(conteo_res, values='Total', names='Estatus', hole=0.6, color='Estatus', color_discrete_map=colores_semaforo)
                    fig_res_donut.update_traces(textposition='inside', textinfo='percent+label')
                    fig_res_donut.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10), height=280)
                    st.plotly_chart(fig_res_donut, use_container_width=True)

                with col_d2:
                    st.markdown("**2️⃣ Esfuerzo Operativo por Marca (Sunburst)**")
                    fig_res_sun = px.sunburst(
                        df_avance, 
                        path=['cliente_marca', 'Estado_Cumplimiento'], 
                        values='visitas_realizadas',
                        color='Estado_Cumplimiento',
                        color_discrete_map=colores_semaforo,
                        maxdepth=2
                    )
                    fig_res_sun.update_layout(margin=dict(t=10, l=10, r=10, b=10), height=280)
                    st.plotly_chart(fig_res_sun, use_container_width=True)

                st.markdown("---")
                st.markdown("#### 📝 Redacción Analítica & Generación de Reporte PDF")
                
                api_key_input = st.text_input("🔑 Pega aquí tu API Key gratuita de Groq (gsk_...):", type="password")
                
                if st.button("📊 Generar Briefing Ejecutivo y PDF Directivo", type="primary"):
                    if not api_key_input:
                        st.warning("⚠️ Necesitas ingresar tu API Key gratuita de Groq.")
                    else:
                        with st.spinner("El Agente C-Level está redactando el Briefing y maquetando el PDF..."):
                            try:
                                prompt = f"""
                                Actúa como un Director de Operaciones Logísticas de nivel C-Level presentando un informe a la Dirección General.
                                Escribe un 'Briefing Ejecutivo Gerencial' formal y altamente estructurado para la empresa RUTAS-QSR.
                                
                                Datos Maestros del Periodo:
                                - Total de Sucursales Administradas: {len(df_avance)}
                                - Sumatoria Total de Visitas Realizadas: {total_historico}
                                - Sucursales en Riesgo Crítico (0 Visitas): {tiendas_riesgo}
                                - Sucursales con Meta Cumplida (2+ Visitas): {tiendas_meta}
                                - Gasto Total Operativo (TCO Gasolina + Mantenimiento + Sueldos en tráfico): ${costo_total_op:,.2f} MXN
                                - Horas invertidas en tráfico (Costo Hundido): {row_fin['tiempo_traslado_hrs']} hrs.
                                - Costo Total por Kilómetro (TCO): ${row_fin['tco_por_km_mxn']:,.2f} MXN/km
                                
                                Estructura Obligatoria del Briefing Directivo:
                                1. RESUMEN EJECUTIVO Y SCOREBOARD: Un párrafo analítico de alto nivel destacando el esfuerzo operativo global y la eficiencia de costos.
                                2. ANALISIS FINANCIERO Y EFICIENCIA LOGISTICA: Evaluación clara del impacto del TCO, el costo por kilómetro y las horas invertidas al volante en comparación con el valor generado en tienda.
                                3. MAPA DE RIESGOS OPERATIVOS: Severa llamada de atención sobre las {tiendas_riesgo} sucursales sin visitas y el impacto directo en la relación con las marcas.
                                4. PLAN ESTRATÉGICO 30-60-90 DÍAS (3 recomendaciones directas): Pasos tácticos con enfoque de ruteo inteligente y automatización para alcanzar el 100% de cobertura y reducir costos en campo.
                                
                                REGLA CRÍTICA: Tono directivo, asertivo, cuantitativo y formal. No utilices asteriscos (*) ni formato Markdown extraño. Presenta secciones limpias separadas por saltos de línea claros.
                                """
                                
                                client = OpenAI(base_url="https://api.groq.com/openai/v1", api_key=api_key_input)
                                response = client.chat.completions.create(
                                    model="llama-3.3-70b-versatile",
                                    messages=[{"role": "user", "content": prompt}],
                                    temperature=0.7
                                )
                                texto_ia = response.choices[0].message.content
                                
                                st.success("✅ Briefing Ejecutivo generado con éxito.")
                                
                                st.markdown("---")
                                st.markdown(f"""
                                    <div style="background-color: #f0f4f8; padding: 20px; border-radius: 8px; border-left: 6px solid #002F6C;">
                                        <h3 style="color: #002F6C; margin-top: 0;">📋 REPORTE GERENCIAL C-LEVEL | RUTAS-QSR</h3>
                                        <p style="white-space: pre-line; color: #333333; font-size: 14px; font-family: Arial, sans-serif;">{texto_ia}</p>
                                    </div>
                                """, unsafe_allow_html=True)
                                st.markdown("---")
                                
                                pdf = FPDF()
                                pdf.add_page()
                                pdf.set_font("Arial", 'B', 15)
                                pdf.set_text_color(0, 47, 108)
                                pdf.cell(200, 10, txt="RUTAS-QSR | BRIEFING EJECUTIVO GERENCIAL", ln=True, align='C')
                                pdf.set_font("Arial", 'I', 10)
                                pdf.set_text_color(100, 100, 100)
                                pdf.cell(200, 6, txt="Dashboard Integral de KPIs y Analisis de Cobertura Operativa", ln=True, align='C')
                                pdf.ln(6)
                                
                                pdf.set_font("Arial", 'B', 11)
                                pdf.set_fill_color(0, 47, 108)
                                pdf.set_text_color(255, 255, 255)
                                pdf.cell(190, 8, txt="  DASHBOARD INTEGRAL - KPI SCORECARDS VISUALES", ln=True, fill=True)
                                pdf.ln(4)
                                
                                pdf.set_fill_color(240, 244, 248)
                                pdf.set_text_color(0, 47, 108)
                                pdf.set_font("Arial", 'B', 10)
                                pdf.cell(92, 7, txt="  VOLUMEN DE INFRAESTRUCTURA", border=1, fill=True)
                                pdf.cell(6, 7, txt="", border=0)
                                pdf.cell(92, 7, txt="  ESFUERZO OPERATIVO", border=1, fill=True, ln=True)
                                
                                pdf.set_font("Arial", size=10)
                                pdf.set_text_color(51, 51, 51)
                                pdf.cell(92, 6, txt=f"  Total Sucursales Base: {len(df_avance)}", border=1)
                                pdf.cell(6, 6, txt="", border=0)
                                pdf.cell(92, 6, txt=f"  Visitas Históricas Totales: {total_historico}", border=1, ln=True)
                                pdf.ln(3)
                                
                                pdf.set_font("Arial", 'B', 10)
                                pdf.set_text_color(180, 0, 0)
                                pdf.cell(92, 7, txt="  ZONA DE RIESGO CRITICO", border=1, fill=True)
                                pdf.cell(6, 7, txt="", border=0)
                                pdf.set_text_color(0, 150, 50)
                                pdf.cell(92, 7, txt="  METAS LOGRADAS", border=1, fill=True, ln=True)
                                
                                pdf.set_font("Arial", size=10)
                                pdf.set_text_color(51, 51, 51)
                                pdf.cell(92, 6, txt=f"  Sucursales con 0 Visitas: {tiendas_riesgo}", border=1)
                                pdf.cell(6, 6, txt="", border=0)
                                pdf.cell(92, 6, txt=f"  Sucursales con 2+ Visitas: {tiendas_meta}", border=1, ln=True)
                                pdf.ln(3)
                                
                                pdf.set_font("Arial", 'B', 10)
                                pdf.set_text_color(0, 47, 108)
                                pdf.cell(190, 7, txt="  IMPACTO FINANCIERO Y TCO", border=1, fill=True, ln=True)
                                pdf.set_font("Arial", size=10)
                                pdf.cell(95, 6, txt=f"  Gasto Operativo Total: ${costo_total_op:,.2f} MXN", border=1)
                                pdf.cell(95, 6, txt=f"  Costo por Kilometro (TCO): ${row_fin['tco_por_km_mxn']:,.2f} MXN/km", border=1, ln=True)
                                pdf.ln(8)
                                
                                pdf.set_font("Arial", 'B', 11)
                                pdf.set_text_color(0, 47, 108)
                                pdf.cell(190, 8, txt="  ANALISIS ESTRATEGICO Y PLAN DE ACCION C-LEVEL", ln=True)
                                pdf.ln(2)
                                
                                pdf.set_font("Arial", size=10)
                                pdf.set_text_color(51, 51, 51)
                                texto_limpio = texto_ia.encode('latin-1', 'replace').decode('latin-1')
                                pdf.multi_cell(0, 6, txt=texto_limpio)
                                
                                raw_output = pdf.output()
                                if isinstance(raw_output, bytearray):
                                    pdf_bytes = bytes(raw_output)
                                elif isinstance(raw_output, str):
                                    pdf_bytes = raw_output.encode('latin-1')
                                else:
                                    pdf_bytes = raw_output
                                
                                st.download_button(
                                    label="📥 Descargar Briefing Ejecutivo en PDF Directivo (Con Scorecards)",
                                    data=pdf_bytes,
                                    file_name="Briefing_Ejecutivo_Scorecards.pdf",
                                    mime="application/pdf"
                                )
                                
                            except Exception as e:
                                st.error(f"🚨 Hubo un error al generar el briefing: {e}")
        else:
             st.warning("No hay datos calculados. Haz clic en 'Recalcular y Actualizar Data Mart'.")