# app.py
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

import streamlit as st
import sqlite3
import pandas as pd
import requests
import math

try:
    import folium
    from streamlit_folium import st_folium
except ImportError:
    import subprocess
    with st.spinner("🔧 Configurando componentes cartográficos... Espere un momento."):
        subprocess.check_call([sys.executable, "-m", "pip", "install", "streamlit-folium", "folium"])
    import folium
    from streamlit_folium import st_folium

from datos import inicializar_base_datos, importar_maestro_sucursales, actualizar_estatus_sucursales, reiniciar_estatus_visitas
from core.simulacion import simular_ruta_del_dia, calcular_distancia_haversine

st.set_page_config(page_title="RUTAS-QSR Dashboard", layout="wide", initial_sidebar_state="expanded")
inicializar_base_datos()

# 🧠 MEMORIA DE CACHÉ INTERMEDIA
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

st.markdown("""
    <style>
    .main h1 { color: #002F6C; font-weight: 700; font-size: 1.8rem; }
    .stButton>button { background-color: #002F6C; color: white; border-radius: 6px; border: none; padding: 0.5rem 1rem; font-weight: bold; width: 100%; }
    .stButton>button:hover { background-color: #004B93; color: white; }
    div[data-testid="stExpander"] { border: 1px solid #002F6C; border-radius: 6px; }
    div[data-testid="stMetric"] { background-color: #f0f4f8; padding: 10px; border-radius: 6px; border-left: 5px solid #002F6C; }
    .link-ruta-completa { display: inline-block; background-color: #008B8B; color: white !important; padding: 8px 15px; border-radius: 6px; font-weight: bold; text-decoration: none; margin-top: 10px; margin-bottom: 20px; text-align: center; }
    table.dataframe-renderizada { width: 100% !important; border-collapse: collapse; font-family: Arial, sans-serif; font-size: 13px; margin: 10px 0; }
    table.dataframe-renderizada th { background-color: #002F6C !important; color: white !important; font-weight: bold; padding: 10px; text-align: left; white-space: nowrap; }
    table.dataframe-renderizada td { padding: 8px 10px; border-bottom: 1px solid #e0e0e0; white-space: nowrap; }
    .contenedor-tabla-scroll { width: 100%; overflow-x: auto; border: 1px solid #e0e0e0; border-radius: 4px; margin-bottom: 15px; }
    </style>
""", unsafe_allow_html=True)

st.title("🚗 Panel de Control Logístico | RUTAS-QSR")
st.caption("Ecosistema Asistido por Agentes de Campo — División QSR Ecolab")

# BARRA LATERAL
st.sidebar.header("📁 Importación Masiva")
uploaded_file = st.sidebar.file_uploader("Arrastra o selecciona la Base Maestra (.xlsx)", type=["xlsx"])

if uploaded_file is not None:
    with st.spinner("Procesando base incremental..."):
        total_filas, fsm_detectado = importar_maestro_sucursales(uploaded_file, uploaded_file.name)
        st.sidebar.success(f"¡Carga Exitosa! {total_filas} registros mapeados.")

df_fsms = pd.DataFrame(columns=['id_fsm', 'nombre_completo'])
if os.path.exists("data/fsm_rutas.db"):
    try:
        conn = sqlite3.connect("data/fsm_rutas.db")
        df_fsms = pd.read_sql_query("SELECT id_fsm, nombre_completo FROM fsm_perfiles", conn)
        conn.close()
    except Exception: pass

st.sidebar.header("👤 Perfil Operativo")
fsm_seleccionado = st.sidebar.selectbox("FSM Activo en la sesión:", df_fsms['id_fsm'].tolist() if not df_fsms.empty else ["JAVIER DOMINGUEZ DELGADILLO"])

# ============================================================
# FUNCIONES LOGÍSTICAS TSP Y VRP
# ============================================================
def optimizar_secuencia_por_proximidad(inicio_lat, inicio_lon, sucursales_pool):
    ordenado = []
    restantes = sucursales_pool.copy()
    curr_lat, curr_lon = inicio_lat, inicio_lon
    while restantes:
        mejor_idx = 0
        min_dist = float('inf')
        for idx, s in enumerate(restantes):
            d = math.sqrt((float(s['latitud']) - curr_lat)**2 + (float(s['longitud']) - curr_lon)**2)
            if d < min_dist:
                min_dist = d
                mejor_idx = idx
        s_elegida = restantes.pop(mejor_idx)
        ordenado.append(s_elegida)
        curr_lat, curr_lon = float(s_elegida['latitud']), float(s_elegida['longitud'])
    return ordenado

def generar_clusters_geograficos(inicio_lat, inicio_lon, sucursales_pool, visitas_por_ruta):
    """Motor VRP que ignora sucursales COMPLETADAS."""
    pool = [s for s in sucursales_pool if str(s.get('estatus_visita', 'PENDIENTE')).upper() != 'COMPLETADA']
    if not pool: return []
        
    N = len(pool)
    K = max(1, math.ceil(N / visitas_por_ruta))
    
    centroids = []
    min_dist_base = float('inf')
    first_idx = 0
    for idx, s in enumerate(pool):
        d = math.sqrt((float(s['latitud']) - inicio_lat)**2 + (float(s['longitud']) - inicio_lon)**2)
        if d < min_dist_base:
            min_dist_base, first_idx = d, idx
            
    centroids.append(pool[first_idx])
    
    while len(centroids) < K and len(centroids) < N:
        max_dist, best_cand_idx = -1, -1
        for idx, s in enumerate(pool):
            if s in centroids: continue
            min_d = min(math.sqrt((float(s['latitud']) - float(c['latitud']))**2 + (float(s['longitud']) - float(c['longitud']))**2) for c in centroids)
            if min_d > max_dist:
                max_dist, best_cand_idx = min_d, idx
        if best_cand_idx != -1: centroids.append(pool[best_cand_idx])
        else: break
            
    K = len(centroids)
    clusters = [[] for _ in range(K)]
    restantes = pool.copy()
    
    for i in range(K):
        c_store = centroids[i]
        clusters[i].append(c_store)
        restantes.remove(c_store)
        
    while restantes:
        for i in range(K):
            if len(clusters[i]) >= visitas_por_ruta or not restantes: continue
            c_lat, c_lon = float(centroids[i]['latitud']), float(centroids[i]['longitud'])
            marcas_en_cluster = [s['cliente_marca'] for s in clusters[i]]
            best_idx, min_score = -1, float('inf')
            
            for idx, s in enumerate(restantes):
                dist = math.sqrt((float(s['latitud']) - c_lat)**2 + (float(s['longitud']) - c_lon)**2)
                veces = marcas_en_cluster.count(s['cliente_marca'])
                score = dist * (1.0 + veces * 2.5)
                if score < min_score:
                    min_score, best_idx = score, idx
                    
            if best_idx != -1: clusters[i].append(restantes.pop(best_idx))
                
    return [optimizar_secuencia_por_proximidad(inicio_lat, inicio_lon, clus) for clus in clusters if clus]

def generar_ruta_radial_tactica(anchor_lat, anchor_lon, sucursales_pool, radio_max_km, max_visitas):
    candidatas = [s for s in sucursales_pool if str(s.get('estatus_visita', 'PENDIENTE')).upper() != 'COMPLETADA' and calcular_distancia_haversine(anchor_lat, anchor_lon, float(s['latitud']), float(s['longitud'])) <= radio_max_km]
    if not candidatas: return []
        
    seleccionadas, marcas_conteo, restantes = [], {}, candidatas.copy()
    curr_lat, curr_lon = anchor_lat, anchor_lon
    
    while restantes and len(seleccionadas) < max_visitas:
        best_idx, min_score = -1, float('inf')
        for idx, s in enumerate(restantes):
            dist_tramo = calcular_distancia_haversine(curr_lat, curr_lon, float(s['latitud']), float(s['longitud']))
            veces = marcas_conteo.get(s['cliente_marca'], 0)
            score = dist_tramo * (1.0 + veces * 2.5)
            if score < min_score:
                min_score, best_idx = score, idx
                
        if best_idx != -1:
            elegida = restantes.pop(best_idx)
            seleccionadas.append(elegida)
            marcas_conteo[elegida['cliente_marca']] = marcas_conteo.get(elegida['cliente_marca'], 0) + 1
            curr_lat, curr_lon = float(elegida['latitud']), float(elegida['longitud'])
            
    return optimizar_secuencia_por_proximidad(anchor_lat, anchor_lon, seleccionadas)

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
    except Exception: pass
    return puntos_coordenadas

def crear_mapa_base(puntos_marcadores, ruta_linea=None, color_linea="#002F6C"):
    if not puntos_marcadores: return folium.Map(location=[19.4326, -99.1332], zoom_start=11)
    m = folium.Map(location=[puntos_marcadores[0]['lat'], puntos_marcadores[0]['lon']], zoom_start=11)
    for p in puntos_marcadores:
        folium.Marker(location=[p['lat'], p['lon']], popup=f"<b>{p['name']}</b><br>Orden: {p['idx']}", icon=folium.Icon(color="blue")).add_to(m)
    if ruta_linea and len(ruta_linea) > 1:
        folium.PolyLine(ruta_linea, color=color_linea, weight=4.5, opacity=0.85).add_to(m)
    return m

def generar_link_google_maps_completo(coords_lista):
    if len(coords_lista) < 2: return ""
    origen, destino = f"{coords_lista[0][0]},{coords_lista[0][1]}", f"{coords_lista[-1][0]},{coords_lista[-1][1]}"
    if paradas := coords_lista[1:-1]:
        return f"https://www.google.com/maps/dir/?api=1&origin={origen}&destination={destino}&waypoints={'|'.join([f'{lat},{lon}' for lat, lon in paradas])}&travelmode=driving"
    return f"https://www.google.com/maps/dir/?api=1&origin={origen}&destination={destino}&travelmode=driving"

# ============================================================
# ESTUCTURA PRINCIPAL DEL DASHBOARD CON MODULOS PESTAÑAS
# ============================================================
st.header("⚙️ Centro de Operaciones Logísticas")
modulo_principal = st.radio("Selecciona Módulo de Trabajo:", ["🗺️ Planeación y Ruteo Inteligente", "📋 Control de Inventario y Visitas (Fase 2)"], horizontal=True)

if modulo_principal == "🗺️ Planeación y Ruteo Inteligente":
    tipo_ruta = st.selectbox("Tipo de Cobertura de la Jornada:", ["Diaria", "Semanal", "Regional"])

    if tipo_ruta == "Diaria":
        st.markdown("### 🏢 Opciones de Ruteo Inteligente")
        tab_vrp, tab_radial = st.tabs(["⚡ Circuitos Automáticos (VRP Global)", "🎯 Diseñador Radial a Medida (Burbuja)"])
        
        with tab_vrp:
            visitas_jornada = st.slider("Define el objetivo de visitas por jornada (Ruta):", min_value=4, max_value=8, value=6, key="sl_vrp")
            hora_inicio_diaria = st.select_slider("Hora de Inicio:", options=["08:00", "08:30", "09:00", "09:30", "10:00"], value="09:00", key="diaria_h")
            
            df_estados = pd.DataFrame()
            if os.path.exists("data/fsm_rutas.db"):
                conn = sqlite3.connect("data/fsm_rutas.db")
                df_estados = pd.read_sql_query("SELECT DISTINCT estado FROM sucursales WHERE estado IS NOT NULL ORDER BY estado", conn)
                conn.close()
                
            estados_list = df_estados['estado'].tolist() if not df_estados.empty else ["N/A"]
            zona_general_elegida = st.selectbox("Selecciona la Zona General:", estados_list, key="zona_general_diaria_sel")
            
            df_selector_diario = pd.DataFrame()
            if os.path.exists("data/fsm_rutas.db"):
                conn = sqlite3.connect("data/fsm_rutas.db")
                query_s = "SELECT DISTINCT zona_localidad FROM sucursales WHERE estado = ? AND zona_localidad IS NOT NULL AND zona_localidad != '' ORDER BY zona_localidad"
                df_selector_diario = pd.read_sql_query(query_s, conn, params=[str(zona_general_elegida)])
                conn.close()

            if not df_selector_diario.empty:
                opciones_localidades = ["TODAS LAS LOCALIDADES"] + [z for z in df_selector_diario['zona_localidad'].tolist() if "ZONA GENERAL" not in str(z).upper()]
                alcaldia_elegida = st.selectbox("Selecciona Alcaldía o Municipio objetivo:", opciones_localidades, index=0, key="alcaldia_diaria_sel")
                
                conn = sqlite3.connect("data/fsm_rutas.db")
                q_cnt = "SELECT COUNT(*) as total FROM sucursales WHERE " + ("estado = ?" if alcaldia_elegida == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?") + " AND (estatus_visita IS NULL OR estatus_visita != 'COMPLETADA')"
                p_cnt = [str(zona_general_elegida)] if alcaldia_elegida == "TODAS LAS LOCALIDADES" else [str(alcaldia_elegida), str(zona_general_elegida)]
                total_tiendas_zona = pd.read_sql_query(q_cnt, conn, params=p_cnt)['total'].values[0]
                conn.close()
                
                total_rutas_calculadas = max(1, math.ceil(total_tiendas_zona / visitas_jornada))
                listado_num_rutas = list(range(1, total_rutas_calculadas + 1))
                
                ruta_elegida = st.selectbox(f"Circuitos Disponibles ({total_tiendas_zona} Tiendas PENDIENTES):", listado_num_rutas, key="num_ruta_diaria_sel")
                
                if st.button("🗺️ Desplegar e Inteligenciar Circuito Diario", key="btn_vrp"):
                    conn = sqlite3.connect("data/fsm_rutas.db")
                    q_pool = "SELECT id_sucursal, sucursal_nombre, direccion_completa, latitud, longitud, tipo_visita, cliente_marca, estatus_visita FROM sucursales WHERE " + ("estado = ?" if alcaldia_elegida == "TODAS LAS LOCALIDADES" else "zona_localidad = ? AND estado = ?")
                    df_pool_sec = pd.read_sql_query(q_pool, conn, params=p_cnt)
                    conn.close()
                    
                    if not df_pool_sec.empty:
                        lat_c, lon_c = 19.549732, -99.236967
                        pool_lista = df_pool_sec.to_dict(orient='records')
                        rutas_maestras = generar_clusters_geograficos(lat_c, lon_c, pool_lista, visitas_jornada)
                        bloque_de_visitas = rutas_maestras[int(ruta_elegida) - 1] if int(ruta_elegida) <= len(rutas_maestras) else []
                        
                        visitas_calc, _, _ = simular_ruta_del_dia(bloque_de_visitas, hora_inicio_diaria, len(bloque_de_visitas), False, "Atizapán Base", (lat_c, lon_c))
                        
                        if visitas_calc:
                            st.session_state.diaria_simulada = True
                            st.session_state.diaria_alcaldia = alcaldia_elegida
                            st.session_state.diaria_ruta_n = int(ruta_elegida)
                            st.session_state.diaria_visitas_final = []
                            st.session_state.diaria_puntos_mapa = []
                            st.session_state.diaria_coords_viaje = [(lat_c, lon_c)]
                            
                            for idx, v in enumerate(visitas_calc):
                                orig = next(item for item in bloque_de_visitas if item['id_sucursal'] == v['ID Sucursal'])
                                url_gps = f"https://www.google.com/maps/dir/?api=1&destination={orig['latitud']},{orig['longitud']}&travelmode=driving"
                                st.session_state.diaria_visitas_final.append({
                                    "ID": orig['id_sucursal'], "Sec": v["Secuencia"], "Marca": orig['cliente_marca'], "Sucursal": v["Nombre Sucursal"], "Dirección": v["Dirección"], "ETA": v["ETA Llegada"], "Navegación": f'<a href="{url_gps}" target="_blank">🗺️ GPS</a>'
                                })
                                st.session_state.diaria_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {v['Nombre Sucursal']}", "idx": idx+1})
                                st.session_state.diaria_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))

            if st.session_state.diaria_simulada:
                st.write("---")
                st.markdown(f"### 📋 Itinerario — {st.session_state.diaria_alcaldia} (Circuito {st.session_state.diaria_ruta_n})")
                st.markdown(f'<div class="contenedor-tabla-scroll"><table class="dataframe-renderizada">{pd.DataFrame(st.session_state.diaria_visitas_final).to_html(escape=False, index=False, classes="dataframe-renderizada")}</table></div>', unsafe_allow_html=True)
                
                # 🎯 CHECKLIST / REGISTRO DE VISITAS COMPLETEDAS (OPCIÓN 2)
                st.subheader("✅ Registro Rápido de Visitas Completadas")
                ids_en_ruta = [item["ID"] for item in st.session_state.diaria_visitas_final]
                completadas_sel = st.multiselect("Selecciona las tiendas que completaste en esta jornada:", options=ids_en_ruta, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.diaria_visitas_final if item["ID"] == x))
                
                col_btn1, col_btn2 = st.columns(2)
                with col_btn1:
                    if st.button("💾 Guardar Visitas Seleccionadas como COMPLETADAS"):
                        actualizar_estatus_sucursales(completadas_sel, "COMPLETADA")
                        st.success(f"¡Se actualizaron {len(completadas_sel)} sucursales como COMPLETADAS! Ya no aparecerán en futuros ruteos.")
                        st.session_state.diaria_simulada = False
                        st.rerun()
                with col_btn2:
                    if st.button("🏁 Marcar TODO EL CIRCUITO como COMPLETADO"):
                        actualizar_estatus_sucursales(ids_en_ruta, "COMPLETADA")
                        st.success("¡Circuito completo registrado con éxito!")
                        st.session_state.diaria_simulada = False
                        st.rerun()

                st_folium(crear_mapa_base(st.session_state.diaria_puntos_mapa, obtener_ruta_vial_real(st.session_state.diaria_coords_viaje)), width=1200, height=400, key="mapa_vrp_active")

        with tab_radial:
            st.markdown("#### 🎯 Generador Táctico por Radio de Cobertura")
            col_rad1, col_rad2 = st.columns(2)
            
            df_todas_sucursales = pd.DataFrame()
            if os.path.exists("data/fsm_rutas.db"):
                conn = sqlite3.connect("data/fsm_rutas.db")
                df_todas_sucursales = pd.read_sql_query("SELECT id_sucursal, sucursal_nombre, cliente_marca, zona_localidad, estado, latitud, longitud, estatus_visita FROM sucursales ORDER BY sucursal_nombre", conn)
                conn.close()
                
            with col_rad1:
                opcion_origen = st.radio("Epicentro / Punto Cero:", ["📍 Base Operativa Atizapán", "🏪 Seleccionar Sucursal Ancla"], key="rad_origen_type")
                if opcion_origen == "📍 Base Operativa Atizapán":
                    lat_ancla, lon_ancla, nombre_epicentro = 19.549732, -99.236967, "Base Atizapán"
                else:
                    if not df_todas_sucursales.empty:
                        sucursal_ancla_str = st.selectbox("Sucursal Ancla:", df_todas_sucursales.apply(lambda row: f"[{row['cliente_marca']}] {row['sucursal_nombre']} - {row['zona_localidad']}", axis=1).tolist())
                        idx_e = df_todas_sucursales.apply(lambda row: f"[{row['cliente_marca']}] {row['sucursal_nombre']} - {row['zona_localidad']}", axis=1).tolist().index(sucursal_ancla_str)
                        row_e = df_todas_sucursales.iloc[idx_e]
                        lat_ancla, lon_ancla, nombre_epicentro = float(row_e['latitud']), float(row_e['longitud']), f"{row_e['sucursal_nombre']} ({row_e['cliente_marca']})"
                    else: lat_ancla, lon_ancla, nombre_epicentro = 19.549732, -99.236967, "Base Atizapán"
                
                hora_inicio_radial = st.select_slider("Hora de Salida:", options=["08:00", "08:30", "09:00", "09:30"], value="09:00", key="rad_h")

            with col_rad2:
                radio_cobertura_km = st.slider("📐 Radio Máximo de Búsqueda (km):", min_value=2, max_value=30, value=10, step=1, key="sl_radio_km")
                visitas_pares = st.slider("🎯 Visitas Objetivos (Pares):", min_value=2, max_value=10, value=6, step=2, key="sl_visitas_pares")

            if st.button("🚀 Generar Circuito Radial", key="btn_gen_radial"):
                if not df_todas_sucursales.empty:
                    pool_radial = df_todas_sucursales.to_dict(orient='records')
                    bloque_radial = generar_ruta_radial_tactica(lat_ancla, lon_ancla, pool_radial, radio_cobertura_km, visitas_pares)
                    if bloque_radial:
                        visitas_calc_rad, _, _ = simular_ruta_del_dia(bloque_radial, hora_inicio_radial, len(bloque_radial), False, nombre_epicentro, (lat_ancla, lon_ancla))
                        if visitas_calc_rad:
                            st.session_state.radial_simulada = True
                            st.session_state.radial_visitas_final = []
                            st.session_state.radial_puntos_mapa = []
                            st.session_state.radial_coords_viaje = [(lat_ancla, lon_ancla)]
                            for idx, v in enumerate(visitas_calc_rad):
                                orig = next(item for item in bloque_radial if item['id_sucursal'] == v['ID Sucursal'])
                                url_gps = f"https://www.google.com/maps/dir/?api=1&destination={orig['latitud']},{orig['longitud']}&travelmode=driving"
                                st.session_state.radial_visitas_final.append({"ID": orig['id_sucursal'], "Sec": v["Secuencia"], "Marca": orig['cliente_marca'], "Sucursal": v["Nombre Sucursal"], "Dirección": v["Dirección"], "ETA": v["ETA Llegada"], "Navegación": f'<a href="{url_gps}" target="_blank">🗺️ GPS</a>'})
                                st.session_state.radial_puntos_mapa.append({"lat": float(orig['latitud']), "lon": float(orig['longitud']), "name": f"[{orig['cliente_marca']}] {v['Nombre Sucursal']}", "idx": idx+1})
                                st.session_state.radial_coords_viaje.append((float(orig['latitud']), float(orig['longitud'])))

            if st.session_state.radial_simulada:
                st.write("---")
                st.markdown(f"### 🎯 Circuito Radial — Epicentro: {nombre_epicentro}")
                st.markdown(f'<div class="contenedor-tabla-scroll"><table class="dataframe-renderizada">{pd.DataFrame(st.session_state.radial_visitas_final).to_html(escape=False, index=False, classes="dataframe-renderizada")}</table></div>', unsafe_allow_html=True)
                
                st.subheader("✅ Registro Rápido de Visitas Completadas")
                ids_rad = [item["ID"] for item in st.session_state.radial_visitas_final]
                rad_sel = st.multiselect("Selecciona tiendas completadas:", options=ids_rad, format_func=lambda x: next(f"[{item['Marca']}] {item['Sucursal']}" for item in st.session_state.radial_visitas_final if item["ID"] == x), key="rad_multi")
                if st.button("💾 Guardar Visitas Radiales COMPLETADAS", key="btn_save_rad"):
                    actualizar_estatus_sucursales(rad_sel, "COMPLETADA")
                    st.success("¡Visitas registradas exitosamente!")
                    st.session_state.radial_simulada = False
                    st.rerun()

                st_folium(crear_mapa_base(st.session_state.radial_puntos_mapa, obtener_ruta_vial_real(st.session_state.radial_coords_viaje)), width=1200, height=400, key="mapa_radial_active")

    elif tipo_ruta == "Semanal":
        st.info("Para mantener optimizado el sistema, los módulos Semanal y Regional utilizan la lógica por proximidad básica.")
    else:
        st.info("Selecciona el modo 'Diaria' para acceder al enrutamiento VRP y Radial por Burbuja.")

else:
    # ============================================================
    # 📋 MÓDULO ADMINISTRATIVO DE INVENTARIO Y CONTROL (OPCIÓN 3)
    # ============================================================
    st.markdown("### 📋 Módulo de Control General de Inventario y Auditorías")
    st.caption("Administra el estatus de las sucursales, visualiza pendientes y gestiona los ciclos de visita.")
    
    conn = sqlite3.connect("data/fsm_rutas.db")
    df_inv = pd.read_sql_query("SELECT id_sucursal, cliente_marca, sucursal_nombre, estado, zona_localidad, estatus_visita, fecha_ultima_visita FROM sucursales ORDER BY estado, zona_localidad, sucursal_nombre", conn)
    conn.close()
    
    if not df_inv.empty:
        # METRICAS CLAVE
        tot = len(df_inv)
        comp = len(df_inv[df_inv['estatus_visita'] == 'COMPLETADA'])
        pend = tot - comp
        porc = (comp / tot * 100) if tot > 0 else 0
        
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Puntos de Venta", tot)
        m2.metric("Pendientes por Visitar", pend)
        m3.metric("Visitas Completadas", comp)
        m4.metric("Avance Global Cobertura", f"{porc:.1f}%")
        
        st.write("---")
        
        # FILTROS DE TABLA
        c1, c2, c3 = st.columns(3)
        with c1: f_est = st.selectbox("Filtrar por Estado:", ["TODOS"] + sorted(df_inv['estado'].unique().tolist()))
        with c2: f_marca = st.selectbox("Filtrar por Marca:", ["TODAS"] + sorted(df_inv['cliente_marca'].unique().tolist()))
        with c3: f_status = st.selectbox("Filtrar por Estatus:", ["TODOS", "PENDIENTE", "COMPLETADA"])
        
        df_filtrado = df_inv.copy()
        if f_est != "TODOS": df_filtrado = df_filtrado[df_filtrado['estado'] == f_est]
        if f_marca != "TODAS": df_filtrado = df_filtrado[df_filtrado['cliente_marca'] == f_marca]
        if f_status != "TODOS": df_filtrado = df_filtrado[df_filtrado['estatus_visita'] == f_status]
        
        st.dataframe(df_filtrado, use_container_width=True, height=400)
        
        # REINICIO DE CICLO Y GESTIÓN MANUAL
        st.subheader("⚙️ Acciones Administrativas de Cobertura")
        col_adm1, col_adm2 = st.columns(2)
        
        with col_adm1:
            st.markdown("#### 🔄 Reiniciar Ciclo de Visitas (Limpieza de Estatus)")
            est_reset = st.selectbox("Selecciona Estado a reiniciar:", ["TODOS LOS ESTADOS"] + sorted(df_inv['estado'].unique().tolist()), key="sel_reset_est")
            if st.button("🚨 Reiniciar Estatus a PENDIENTE"):
                param_est = None if est_reset == "TODOS LOS ESTADOS" else est_reset
                reiniciar_estatus_visitas(param_est)
                st.success(f"¡Se han reiniciado todas las sucursales en {est_reset} a estatus PENDIENTE!")
                st.rerun()