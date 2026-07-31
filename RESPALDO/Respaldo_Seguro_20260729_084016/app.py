# app.py
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import sqlite3
import pandas as pd
import requests
import math
import io
import urllib.parse
import re

try:
    import folium
    from streamlit_folium import st_folium
except ImportError:
    import subprocess
    with st.spinner("🔧 Configurando componentes cartográficos... Espere un momento."):
        subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit-folium", "folium"])
    import folium
    from streamlit_folium import st_folium

# Importaciones de los módulos del ecosistema
from datos import inicializar_base_datos, importar_maestro_sucursales, actualizar_estatus_sucursales, reiniciar_estatus_visitas

# Soporte flexible para la ubicación de simulacion.py (raíz o dentro de core/)
try:
    from simulacion import simular_ruta_del_dia, calcular_distancia_haversine
except ImportError:
    from core.simulacion import simular_ruta_del_dia, calcular_distancia_haversine

# Configuración inicial de la página
st.set_page_config(page_title="RUTAS-QSR Dashboard", layout="wide", initial_sidebar_state="expanded")
inicializar_base_datos()

# Variables de estado (Session State)
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
    st.session_state.radial_centro = (19.549732, -99.236967)
    st.session_state.radial_km = 10.0

if 'geo_procesado' not in st.session_state:
    st.session_state.geo_procesado = False
    st.session_state.df_exitosos = pd.DataFrame()
    st.session_state.df_cuarentena = pd.DataFrame()

# Estilos CSS personalizados
st.markdown("""
 <style>
 .main h1 { color: #002F6C; font-weight: 700; font-size: 1.8rem; }
 .stButton>button { background-color: #002F6C; color: white; border-radius: 6px; border: none; padding: 0.5rem 1rem; font-weight: bold; width: 100%; }
 .stButton>button:hover { background-color: #004B93; color: white; }
 div[data-testid="stExpander"] { border: 1px solid #002F6C; border-radius: 6px; }
 div[data-testid="stMetric"] { background-color: #f0f4f8; padding: 10px; border-radius: 6px; border-left: 5px solid #002F6C; }
 table.dataframe-renderizada { width: 100% !important; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; margin: 10px 0; }
 table.dataframe-renderizada th { background-color: #002F6C !important; color: white !important; font-weight: bold; padding: 10px; text-align: left; }
 table.dataframe-renderizada td { padding: 8px 10px; border-bottom: 1px solid #e0e0e0; white-space: normal; word-wrap: break-word; }
 .contenedor-tabla-scroll { width: 100%; max-height: 420px; overflow-x: auto; overflow-y: auto; border: 1px solid #e0e0e0; border-radius: 6px; margin-bottom: 15px; }
 </style>
""", unsafe_allow_html=True)

st.title("🚗 Panel de Control Logístico | RUTAS-QSR")
st.caption("Ecosistema Asistido por Agentes de Campo — División QSR Ecolab")

# Función para renderizar tablas en HTML puro (Anti-Flickering)
def mostrar_tabla_html(df):
    if df is None or df.empty:
        st.warning("⚠️ No hay datos registrados para mostrar.")
        return
    html_tabla = df.to_html(index=False, classes="dataframe-renderizada", escape=False)
    st.markdown(f'<div class="contenedor-tabla-scroll">{html_tabla}</div>', unsafe_allow_html=True)

# BARRA LATERAL
st.sidebar.header("📁 Importación Masiva")
uploaded_file = st.sidebar.file_uploader("Arrastra o selecciona la Base Maestra (.xlsx, .csv)", type=["xlsx", "csv"])

if uploaded_file is not None:
    with st.spinner("Procesando base incremental..."):
        total_filas = importar_maestro_sucursales(uploaded_file, uploaded_file.name)
        st.sidebar.success(f"¡Carga Exitosa! {total_filas} registros mapeados.")

# FUNCIONES AUXILIARES DE RUTEOS Y BÚSQUEDA HÍBRIDA
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
    conn = sqlite3.connect("data/rutas_qsr.db")
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
        'STANDARD'
    FROM temp_homologacion t
    """)
    conn.commit()
    conn.close()

def optimizar_secuencia_por_proximidad(inicio_lat, inicio_lon, sucursales_pool):
    ordenado = []
    restantes = sucursales_pool.copy()
    curr_lat, curr_lon = inicio_lat, inicio_lon
    
    while restantes:
        s_elegida = min(restantes, key=lambda s: math.sqrt((float(s['latitud']) - curr_lat)**2 + (float(s['longitud']) - curr_lon)**2))
        ordenado.append(s_elegida)
        restantes.remove(s_elegida)
        curr_lat, curr_lon = float(s_elegida['latitud']), float(s_elegida['longitud'])
        
    return ordenado

def generar_clusters_geograficos(inicio_lat, inicio_lon, sucursales_pool, visitas_por_ruta):
    pool = [s for s in sucursales_pool if str(s.get('estatus_visita', 'PENDIENTE')).upper() != 'COMPLETADA']
    if not pool: return []
    
    N = len(pool)
    K = max(1, math.ceil(N / visitas_por_ruta))
    
    centroids = [min(pool, key=lambda s: math.sqrt((float(s['latitud']) - inicio_lat)**2 + (float(s['longitud']) - inicio_lon)**2))]
    
    while len(centroids) < K and len(centroids) < N:
        best_cand = max(pool, key=lambda s: min(math.sqrt((float(s['latitud']) - float(c['latitud']))**2 + (float(s['longitud']) - float(c['longitud']))**2) for c in centroids))
        if best_cand not in centroids:
            centroids.append(best_cand)
        else:
            break
            
    clusters = [[] for _ in range(len(centroids))]
    restantes = pool.copy()
    
    for i, c in enumerate(centroids):
        if c in restantes:
            clusters[i].append(c)
            restantes.remove(c)
            
    while restantes:
        for i in range(len(centroids)):
            if len(clusters[i]) >= visitas_por_ruta or not restantes: 
                continue
            
            c_lat, c_lon = float(centroids[i]['latitud']), float(centroids[i]['longitud'])
            s_cercana = min(restantes, key=lambda s: math.sqrt((float(s['latitud']) - c_lat)**2 + (float(s['longitud']) - c_lon)**2))
            clusters[i].append(s_cercana)
            restantes.remove(s_cercana)
            
    return [optimizar_secuencia_por_proximidad(inicio_lat, inicio_lon, clus) for clus in clusters if clus]

def obtener_ruta_vial_real(puntos_coordenadas):
    if len(puntos_coordenadas) < 2: return puntos_coordenadas
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

def crear_mapa_base(puntos_marcadores, ruta_linea=None, color_linea="#002F6C", centro_circulo=None, radio_km=None):
    if not puntos_marcadores and not centro_circulo:
        return folium.Map(location=[19.4326, -99.1332], zoom_start=11)
        
    centro_lat = centro_circulo[0] if centro_circulo else puntos_marcadores[0]['lat']
    centro_lon = centro_circulo[1] if centro_circulo else puntos_marcadores[0]['lon']
    
    m = folium.Map(location=[centro_lat, centro_lon], zoom_start=11)
    
    if centro_circulo and radio_km:
        folium.Circle(
            location=[centro_circulo[0], centro_circulo[1]],
            radius=radio_km * 1000,
            color="#FF4B4B",
            fill=True,
            fill_color="#FF4B4B",
            fill_opacity=0.1,
            popup=f"Radio de cobertura: {radio_km} km"
        ).add_to(m)
        folium.Marker(
            location=[centro_circulo[0], centro_circulo[1]],
            popup="<b>PUNTO BASE / ORIGEN RADIAL</b>",
            icon=folium.Icon(color="red", icon="home")
        ).add_to(m)
        
    for p in puntos_marcadores:
        folium.Marker(
            location=[p['lat'], p['lon']],
            popup=f"<b>{p['name']}</b><br>Orden: {p['idx']}",
            icon=folium.Icon(color="blue")
        ).add_to(m)
        
    if ruta_linea and len(ruta_linea) > 1:
        folium.PolyLine(ruta_linea, color=color_linea, weight=4.5, opacity=0.85).add_to(m)
        
    return m

# NAVEGACIÓN PRINCIPAL
modulo_principal = st.radio("Selecciona Módulo de Trabajo:", ["🗺️ Planeación y Ruteo Inteligente", "📋 Control de Inventario y Visitas", "📥 Agente Enriquecedor de Nuevos Clientes"], horizontal=True)

# 1. MÓDULO: PLANEACIÓN Y RUTEO INTELIGENTE
if modulo_principal == "🗺️ Planeación y Ruteo Inteligente":
    df_marcas_maestras, df_estados_maestros = pd.DataFrame(), pd.DataFrame()
    try:
        conn = sqlite3.connect("data/rutas_qsr.db")
        df_marcas_maestras = pd.read_sql_query("SELECT DISTINCT cliente_marca FROM sucursales WHERE cliente_marca IS NOT NULL ORDER BY cliente_marca", conn)
        df_estados_maestros = pd.read_sql_query("SELECT DISTINCT estado FROM sucursales WHERE estado IS NOT NULL AND estado != '' ORDER BY estado", conn)
        conn.close()
    except Exception as e:
        st.error(f"🚨 Error al conectar base de datos: {e}")

    if df_estados_maestros.empty:
        st.warning("⚠️ Base vacía. Sube una plantilla válida en el Agente Enriquecedor.")
    else:
        estados_disponibles = df_estados_maestros['estado'].tolist()
        st.markdown("### 🏢 Opciones de Ruteo Inteligente")
        tab_vrp, tab_radial = st.tabs(["⚡ Circuitos Automáticos (VRP Global)", "🎯 Diseñador Radial"])
        
        # TAB 1: VRP GLOBAL
        with tab_vrp:
            visitas_jornada = st.slider("Objetivo de visitas por jornada:", min_value=4, max_value=8, value=6)
            hora_inicio_diaria = st.select_slider("Hora de Inicio:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00")
            zona_general_elegida = st.selectbox("Zona General:", estados_disponibles)
            
            conn = sqlite3.connect("data/rutas_qsr.db")
            df_selector_diario = pd.read_sql_query("SELECT DISTINCT zona_localidad FROM sucursales WHERE estado = ? AND zona_localidad IS NOT NULL", conn, params=[str(zona_general_elegida)])
            conn.close()

            if not df_selector_diario.empty:
                opciones_localidades = ["TODAS LAS LOCALIDADES"] + df_selector_diario['zona_localidad'].tolist()
                alcaldia_elegida = st.selectbox("Alcaldía objetivo:", opciones_localidades, index=0)
                
                conn = sqlite3.connect("data/rutas_qsr.db")
                q_cnt = "SELECT COUNT(*) as total FROM sucursales WHERE " + ("estado = ?" if alcaldia_elegida == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?") + " AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')"
                p_cnt = [str(zona_general_elegida)] if alcaldia_elegida == "TODAS LAS LOCALIDADES" else [str(alcaldia_elegida), str(zona_general_elegida)]
                total_tiendas_zona = pd.read_sql_query(q_cnt, conn, params=p_cnt)['total'].values[0]
                conn.close()
                
                if total_tiendas_zona > 0:
                    total_rutas_calculadas = max(1, math.ceil(total_tiendas_zona / visitas_jornada))
                    ruta_elegida = st.selectbox(f"Circuitos Disponibles ({total_tiendas_zona} PENDIENTES):", list(range(1, total_rutas_calculadas + 1)))
                    
                    if st.button("🗺️ Desplegar Circuito Diario"):
                        conn = sqlite3.connect("data/rutas_qsr.db")
                        q_pool = "SELECT * FROM sucursales WHERE " + ("estado = ?" if alcaldia_elegida == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?") + " AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')"
                        df_pool_sec = pd.read_sql_query(q_pool, conn, params=p_cnt)
                        conn.close()
                        
                        if not df_pool_sec.empty:
                            lat_c, lon_c = 19.549732, -99.236967
                            rutas_maestras = generar_clusters_geograficos(lat_c, lon_c, df_pool_sec.to_dict(orient='records'), visitas_jornada)
                            
                            if rutas_maestras:
                                bloque_de_visitas = rutas_maestras[int(ruta_elegida) - 1] if int(ruta_elegida) <= len(rutas_maestras) else []
                                visitas_calc, _, _ = simular_ruta_del_dia(bloque_de_visitas, hora_inicio_diaria, len(bloque_de_visitas), False, "Base", (lat_c, lon_c))
                                
                                if visitas_calc:
                                    st.session_state.diaria_simulada = True
                                    st.session_state.diaria_alcaldia = alcaldia_elegida
                                    st.session_state.diaria_ruta_n = int(ruta_elegida)
                                    st.session_state.diaria_visitas_final = []
                                    st.session_state.diaria_puntos_mapa = []
                                    st.session_state.diaria_coords_viaje = [(lat_c, lon_c)]
                                    
                                    for idx, v in enumerate(visitas_calc):
                                        orig = next(item for item in bloque_de_visitas if item['id_sucursal'] == v['ID Sucursal'])
                                        st.session_state.diaria_visitas_final.append({
                                            "ID": orig['id_sucursal'], 
                                            "Sec": v["Secuencia"], 
                                            "Marca": orig['cliente_marca'], 
                                            "Sucursal": v["Nombre Sucursal"], 
                                            "Dirección": v["Dirección"], 
                                            "Llegada": v["ETA Llegada"],
                                            "Salida": v.get("Hora Salida", "N/A")
                                        })
                                        st.session_state.diaria_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {v['Nombre Sucursal']}", "idx": idx+1})
                                        st.session_state.diaria_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))
                            else:
                                st.warning("⚠️ No se pudieron generar grupos geográficos estables.")
                else:
                    st.success("✅ Todas las tiendas en este cuadrante se encuentran COMPLETADAS.")

        if st.session_state.diaria_simulada:
            st.write("---")
            st.markdown(f"### 📋 Itinerario — {st.session_state.diaria_alcaldia}")
            mostrar_tabla_html(pd.DataFrame(st.session_state.diaria_visitas_final))
            
            ids_en_ruta = [item["ID"] for item in st.session_state.diaria_visitas_final]
            completadas_sel = st.multiselect("Selecciona tiendas completadas:", options=ids_en_ruta, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.diaria_visitas_final if item["ID"] == x))
            if st.button("💾 Guardar Seleccionadas como COMPLETADAS"):
                actualizar_estatus_sucursales(completadas_sel, "COMPLETADA")
                st.session_state.diaria_simulada = False
                st.rerun()
            st_folium(crear_mapa_base(st.session_state.diaria_puntos_mapa, obtener_ruta_vial_real(st.session_state.diaria_coords_viaje)), width=1200, height=400, key="mapa_vrp_active")

        # TAB 2: DISEÑADOR RADIAL (PROGRAMADO Y TOTALMENTE OPERATIVO)
        with tab_radial:
            st.markdown("#### 🎯 Generador de Cobertura Radial por Radio de Distancia")
            col_rad1, col_rad2, col_rad3 = st.columns([2, 2, 2])
            
            with col_rad1:
                origen_rad = st.selectbox(
                    "Origen del Centro Radial:",
                    ["CASA (ATIZAPÁN)", "TRABAJO (ECOLAB)", "COORDINADAS PERSONALIZADAS"]
                )
                if origen_rad == "CASA (ATIZAPÁN)":
                    lat_rad_c, lon_rad_c = 19.553985, -99.242164
                elif origen_rad == "TRABAJO (ECOLAB)":
                    lat_rad_c, lon_rad_c = 19.364200, -99.260500
                else:
                    lat_rad_c = st.number_input("Latitud Centro:", value=19.549732, format="%.6f")
                    lon_rad_c = st.number_input("Longitud Centro:", value=-99.236967, format="%.6f")
                    
            with col_rad2:
                radio_km_sel = st.slider("Radio Máximo de Cobertura (KM):", min_value=2.0, max_value=30.0, value=10.0, step=1.0)
                max_tiendas_rad = st.slider("Límite Máximo de Tiendas:", min_value=3, max_value=10, value=6)
                
            with col_rad3:
                hora_inicio_radial = st.select_slider("Hora de Inicio Jornada:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00")
                
            if st.button("🎯 Calcular Circuito Radial"):
                conn = sqlite3.connect("data/rutas_qsr.db")
                df_radial_pool = pd.read_sql_query(
                    "SELECT * FROM sucursales WHERE latitud IS NOT NULL AND longitud IS NOT NULL AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')", 
                    conn
                )
                conn.close()
                
                if df_radial_pool.empty:
                    st.warning("⚠️ No hay tiendas pendientes en la base de datos.")
                else:
                    df_radial_pool['DIST_CENTRO'] = df_radial_pool.apply(
                        lambda row: calcular_distancia_haversine(lat_rad_c, lon_rad_c, float(row['latitud']), float(row['longitud'])),
                        axis=1
                    )
                    df_en_radio = df_radial_pool[df_radial_pool['DIST_CENTRO'] <= radio_km_sel].copy()
                    
                    if df_en_radio.empty:
                        st.warning(f"⚠️ No se encontraron sucursales dentro del radio de {radio_km_sel} km desde el punto seleccionado.")
                    else:
                        df_filtradas = df_en_radio.nsmallest(max_tiendas_rad, 'DIST_CENTRO')
                        tiendas_list = df_filtradas.to_dict(orient='records')
                        tiendas_ordenadas = optimizar_secuencia_por_proximidad(lat_rad_c, lon_rad_c, tiendas_list)
                        
                        visitas_calc, _, _ = simular_ruta_del_dia(tiendas_ordenadas, hora_inicio_radial, len(tiendas_ordenadas), False, "Base", (lat_rad_c, lon_rad_c))
                        
                        if visitas_calc:
                            st.session_state.radial_simulada = True
                            st.session_state.radial_centro = (lat_rad_c, lon_rad_c)
                            st.session_state.radial_km = radio_km_sel
                            st.session_state.radial_visitas_final = []
                            st.session_state.radial_puntos_mapa = []
                            st.session_state.radial_coords_viaje = [(lat_rad_c, lon_rad_c)]
                            
                            for idx, v in enumerate(visitas_calc):
                                orig = next(item for item in tiendas_ordenadas if item['id_sucursal'] == v['ID Sucursal'])
                                st.session_state.radial_visitas_final.append({
                                    "ID": orig['id_sucursal'],
                                    "Sec": v["Secuencia"],
                                    "Marca": orig['cliente_marca'],
                                    "Sucursal": v["Nombre Sucursal"],
                                    "Dirección": v["Dirección"],
                                    "Llegada": v["ETA Llegada"],
                                    "Salida": v.get("Hora Salida", "N/A"),
                                    "Dist. a Centro (km)": f"{orig['DIST_CENTRO']:.2f}"
                                })
                                st.session_state.radial_puntos_mapa.append({
                                    "lat": float(orig['latitud']),
                                    "lon": float(orig['longitud']),
                                    "name": f"[{orig['cliente_marca']}] {v['Nombre Sucursal']}",
                                    "idx": idx+1
                                })
                                st.session_state.radial_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))

        if st.session_state.radial_simulada:
            st.write("---")
            st.markdown(f"### 🎯 Itinerario Radial ({st.session_state.radial_km} KM)")
            mostrar_tabla_html(pd.DataFrame(st.session_state.radial_visitas_final))
            
            ids_rad_en_ruta = [item["ID"] for item in st.session_state.radial_visitas_final]
            completadas_rad_sel = st.multiselect(
                "Selecciona tiendas completadas:", 
                options=ids_rad_en_ruta, 
                format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.radial_visitas_final if item["ID"] == x),
                key="multi_radial"
            )
            if st.button("💾 Guardar Seleccionadas como COMPLETADAS", key="btn_radial_save"):
                actualizar_estatus_sucursales(completadas_rad_sel, "COMPLETADA")
                st.session_state.radial_simulada = False
                st.rerun()
                
            st_folium(
                crear_mapa_base(
                    st.session_state.radial_puntos_mapa, 
                    obtener_ruta_vial_real(st.session_state.radial_coords_viaje),
                    color_linea="#FF4B4B",
                    centro_circulo=st.session_state.radial_centro,
                    radio_km=st.session_state.radial_km
                ), 
                width=1200, 
                height=400, 
                key="mapa_radial_active"
            )

# 2. MÓDULO: CONTROL DE INVENTARIO Y VISITAS
elif modulo_principal == "📋 Control de Inventario Y Visitas":
    st.markdown("### 📋 Módulo Administrativo de Inventario")
    try:
        conn = sqlite3.connect("data/rutas_qsr.db")
        df_inv = pd.read_sql_query("SELECT id_sucursal, cliente_marca, sucursal_nombre, estado, zona_localidad, estatus_visita, fecha_ultima_visita FROM sucursales ORDER BY estado", conn)
        conn.close()
    except Exception:
        df_inv = pd.DataFrame()
        
    if df_inv.empty:
        st.warning("⚠️ La base de datos está vacía.")
    else:
        mostrar_tabla_html(df_inv)
            
        lista_estados_limpia = sorted(df_inv['estado'].dropna().astype(str).unique().tolist())
        est_reset = st.selectbox("Estado a reiniciar:", ["TODOS LOS ESTADOS"] + lista_estados_limpia)
        if st.button("🚨 Reiniciar Estatus a PENDIENTE"):
            reiniciar_estatus_visitas(None if est_reset == "TODOS LOS ESTADOS" else est_reset)
            st.rerun()

# 3. MÓDULO: AGENTE ENRIQUECEDOR DE NUEVOS CLIENTES
elif modulo_principal == "📥 Agente Enriquecedor de Nuevos Clientes":
    st.markdown("### 📥 Agente Híbrido de Enriquecimiento (6 Campos Base)")
    excel_crudo = st.file_uploader("Sube la base de datos del cliente (.csv o .xlsx)", type=["xlsx", "csv"])
    
    if excel_crudo and not st.session_state.geo_procesado:
        if excel_crudo.name.lower().endswith('.csv'):
            df_input = pd.read_csv(excel_crudo)
        else:
            df_input = pd.read_excel(excel_crudo)
            
        df_input.columns = df_input.columns.str.strip().str.lower()
        columnas_requeridas = ['id_sucursal', 'sucursal_nombre', 'cliente_marca', 'franquicia', 'zona_localidad', 'estado']
        faltantes = [c for c in columnas_requeridas if c not in df_input.columns]
        
        if faltantes:
            st.error(f"❌ Error: Al archivo le faltan las columnas: {', '.join(faltantes)}")
        else:
            st.markdown("##### 🔍 Vista previa de la base cargada (primeros 3 registros)")
            mostrar_tabla_html(df_input[columnas_requeridas].head(3))
            
            if st.button("🚀 Iniciar Agente Híbrido"):
                conn = sqlite3.connect("data/rutas_qsr.db")
                try:
                    ids_existentes = pd.read_sql_query("SELECT id_sucursal FROM sucursales", conn)['id_sucursal'].tolist()
                except Exception:
                    ids_existentes = []
                conn.close()
                
                df_nuevos = df_input[~df_input['id_sucursal'].isin(ids_existentes)]
                if df_nuevos.empty:
                    st.warning("⚠️ Todos los registros ya se encuentran ingresados.")
                else:
                    exitosos, fallidos = [], []
                    progreso = st.progress(0, text="Buscando en Nominatim API...")
                    
                    for i, (idx_row, row) in enumerate(df_nuevos.iterrows()):
                        lat, lng, dire, est_res, loc_res = buscar_datos_osm_hibrido(row['cliente_marca'], row['sucursal_nombre'], row['zona_localidad'], row['estado'])
                        fila = {
                            'id_sucursal': str(row['id_sucursal']).upper(),
                            'sucursal_nombre': str(row['sucursal_nombre']).upper(),
                            'cliente_marca': str(row['cliente_marca']).upper(),
                            'latitud': lat, 'longitud': lng,
                            'estado': est_res.upper() if est_res else str(row['estado']).upper(),
                            'zona_localidad': loc_res.upper() if loc_res else str(row['zona_localidad']).upper(),
                            'direccion_completa': dire if dire else "NO ENCONTRADA",
                            'estatus_visita': 'PENDIENTE', 'tipo_visita': 'STANDARD'
                        }
                        if lat and lng: exitosos.append(fila)
                        else: fallidos.append(fila)
                    
                    st.session_state.df_exitosos = pd.DataFrame(exitosos)
                    st.session_state.df_cuarentena = pd.DataFrame(fallidos)
                    st.session_state.geo_procesado = True
                    st.rerun()

    if st.session_state.geo_procesado:
        if not st.session_state.df_cuarentena.empty:
            st.markdown("### 🏥 Tabla de Cuarentena (Atención Manual)")
            df_editado = st.data_editor(
                st.session_state.df_cuarentena[['id_sucursal', 'cliente_marca', 'sucursal_nombre', 'latitud', 'longitud', 'direccion_completa']],
                height=350,
                num_rows="dynamic",
                use_container_width=True,
                hide_index=True
            )
        
        if not st.session_state.df_exitosos.empty:
            if st.button("⚡ Cargar a Base de Datos"):
                inyectar_a_base_maestra_11_campos(st.session_state.df_exitosos)
                st.success("¡Base integrada perfectamente!")
                st.session_state.geo_procesado = False
                st.rerun()