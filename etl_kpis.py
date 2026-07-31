import sqlite3
import pandas as pd
import math
import os
from datetime import datetime

try:
    from core.simulacion import calcular_distancia_haversine
except ImportError:
    from simulacion import calcular_distancia_haversine

DB_PRINCIPAL = "data/rutas_qsr.db" if os.path.exists("data/rutas_qsr.db") else "rutas_qsr.db"
DB_KPIS = "data/rutas_kpis.db" if os.path.exists("data/rutas_qsr.db") else "rutas_kpis.db"

def extraer_y_transformar_datos(rendimiento_km_l=12.0, costo_litro=24.50, costo_mto_15k=3500.0, sueldo_hora=60.0):
    if not os.path.exists(DB_PRINCIPAL):
        print("⚠️ No se encontró la base de datos principal.")
        return

    conn_prin = sqlite3.connect(DB_PRINCIPAL)
    df_completadas = pd.read_sql_query("SELECT * FROM sucursales WHERE estatus_visita LIKE 'COMPLETADA%'", conn_prin)
    # 🚀 ACTUALIZADO: Agregamos zona_localidad y sucursal_nombre para gráficos interactivos
    df_avance = pd.read_sql_query("SELECT id_sucursal, sucursal_nombre, cliente_marca, estatus_visita, estado, zona_localidad, visitas_realizadas FROM sucursales", conn_prin)
    conn_prin.close()

    if df_completadas.empty:
        print("ℹ️ No hay visitas completadas para calcular KPIs financieros aún.")
        conn_kpi = sqlite3.connect(DB_KPIS)
        df_avance.to_sql("kpis_avance_operativo", conn_kpi, if_exists="replace", index=False)
        conn_kpi.close()
        return

    centro_lat = df_completadas['latitud'].mean()
    centro_lon = df_completadas['longitud'].mean()
    
    distancia_total_estimada_km = 0.0
    for _, row in df_completadas.iterrows():
         distancia_total_estimada_km += calcular_distancia_haversine(centro_lat, centro_lon, float(row['latitud']), float(row['longitud'])) * 2 
         
    costo_gasolina_total = (distancia_total_estimada_km / rendimiento_km_l) * costo_litro
    costo_mantenimiento_por_km = costo_mto_15k / 15000.0
    costo_mantenimiento_total = distancia_total_estimada_km * costo_mantenimiento_por_km
    costo_tco_por_km = (costo_gasolina_total + costo_mantenimiento_total) / distancia_total_estimada_km if distancia_total_estimada_km > 0 else 0
    
    visitas_completadas = len(df_completadas)
    tiempo_efectivo_horas = (visitas_completadas * 45) / 60.0 
    velocidad_promedio_kmh = 25.0
    tiempo_traslado_horas = distancia_total_estimada_km / velocidad_promedio_kmh
    costo_trafico = tiempo_traslado_horas * sueldo_hora 

    data_kpi = {
        "fecha_calculo": [datetime.now().strftime("%Y-%m-%d %H:%M:%S")],
        "total_visitas": [visitas_completadas],
        "distancia_total_km": [round(distancia_total_estimada_km, 2)],
        "costo_gasolina_mxn": [round(costo_gasolina_total, 2)],
        "costo_mantenimiento_mxn": [round(costo_mantenimiento_total, 2)],
        "tco_por_km_mxn": [round(costo_tco_por_km, 2)],
        "tiempo_efectivo_hrs": [round(tiempo_efectivo_horas, 2)],
        "tiempo_traslado_hrs": [round(tiempo_traslado_horas, 2)],
        "costo_trafico_mxn": [round(costo_trafico, 2)]
    }
    df_kpi_resumen = pd.DataFrame(data_kpi)

    conn_kpi = sqlite3.connect(DB_KPIS)
    df_kpi_resumen.to_sql("kpis_financieros", conn_kpi, if_exists="append", index=False)
    df_avance.to_sql("kpis_avance_operativo", conn_kpi, if_exists="replace", index=False)
    conn_kpi.close()
    
    print("✅ Data Mart Financiero actualizado correctamente.")

if __name__ == "__main__":
    extraer_y_transformar_datos()