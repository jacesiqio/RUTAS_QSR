# core/simulacion.py
import datetime
import math

def calcular_distancia_haversine(lat1, lon1, lat2, lon2):
    """
    Calcula la distancia real en kilómetros entre dos coordenadas geográficas
    utilizando la fórmula de Haversine.
    """
    R = 6371.0  # Radio de la Tierra en kilómetros
    
    rad_lat1 = math.radians(lat1)
    rad_lon1 = math.radians(lon1)
    rad_lat2 = math.radians(lat2)
    rad_lon2 = math.radians(lon2)
    
    dlat = rad_lat2 - rad_lat1
    dlon = rad_lon2 - rad_lon1
    
    a = math.sin(dlat / 2)**2 + math.cos(rad_lat1) * math.cos(rad_lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c

def simular_ruta_del_dia(sucursales_pool, hora_inicio_str, max_visitas, es_regional, punto_partida, coordenadas_origen=(19.549732, -99.236967)):
    """
    Simula la jornada aplicando distancias geográficas reales y velocidades promedio
    ajustadas de forma dinámica (Metropolitano vs Foráneo).
    """
    formato_hora = "%H:%M"
    hora_actual = datetime.datetime.strptime(hora_inicio_str, formato_hora)
    hora_corte = datetime.datetime.strptime("18:00", formato_hora)
    
    visitas_aprobadas = []
    distancia_acumulada_km = 0.0
    
    lat_actual, lon_actual = coordenadas_origen
    
    for i, sucursal in enumerate(sucursales_pool):
        if len(visitas_aprobadas) >= max_visitas:
            break
            
        lat_dest = float(sucursal['latitud'])
        lon_dest = float(sucursal['longitud'])
        
        # 1. Calcular distancia geométrica real
        distancia_tramo = calcular_distancia_haversine(lat_actual, lon_actual, lat_dest, lon_dest)
        
        # 2. Ajuste Dinámico por Entorno (Velocidades y Sinuosidad)
        if es_regional:
            # Carretera foránea: Ajuste por curvas de montaña
            distancia_real_km = distancia_tramo * 1.25
            velocidad_promedio = 55.0 if i == 0 else 75.0
        else:
            # Ciudad (CDMX/EDOMEX): Ajuste por semáforos, cuadrículas y tráfico pesado
            distancia_real_km = distancia_tramo * 1.40
            velocidad_promedio = 22.0 if i == 0 else 18.0
            
        # Calcular tiempo de traslado en minutos
        tiempo_traslado_min = int((distancia_real_km / velocidad_promedio) * 60)
        
        # Mapear tiempo en sitio según el estándar de Ecolab
        tipo_v = sucursal.get('tipo_visita', 'STANDARD')
        duracion_servicio = 120 if tipo_v == 'INSTALACION' else 80
        
        # 3. Evaluar línea de tiempo del FSM
        hora_llegada = hora_actual + datetime.timedelta(minutes=tiempo_traslado_min)
        hora_salida = hora_llegada + datetime.timedelta(minutes=duracion_servicio)
        
        hora_arribo_hotel = hora_salida + datetime.timedelta(minutes=30)
        
        # 4. FILTRO DE SEGURIDAD ELÁSTICO
        if es_regional:
            # En carretera es implacable: Parar antes de las 6:00 PM
            if hora_arribo_hotel > hora_corte:
                break
        else:
            # En ciudad: Hacemos un bypass. Permitimos que la ruta urbana se consolide
            # completa sin truncar las tiendas lejanas de la Ruta 4 o 5.
            pass
            
        visitas_aprobadas.append({
            "Secuencia": len(visitas_aprobadas) + 1,
            "ID Sucursal": sucursal.get('id_sucursal', 'N/A'),
            "Nombre Sucursal": sucursal.get('sucursal_nombre', 'N/A'),
            "Dirección": sucursal.get('direccion_completa', 'N/A'),
            "Tipo": tipo_v,
            "Distancia Tramo": f"{distancia_real_km:.1f} km",
            "ETA Llegada": hora_llegada.strftime(formato_hora),
            "Hora Salida": hora_salida.strftime(formato_hora)
        })
        
        distancia_acumulada_km += distancia_real_km
        hora_actual = hora_salida
        lat_actual, lon_actual = lat_dest, lon_dest
        
    hora_final_jornada = (hora_actual + datetime.timedelta(minutes=30)).strftime(formato_hora) if visitas_aprobadas else hora_inicio_str
    
    return visitas_aprobadas, distancia_acumulada_km, hora_final_jornada