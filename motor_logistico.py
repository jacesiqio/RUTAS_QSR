import math

def optimizar_secuencia_por_proximidad(inicio_lat, inicio_lon, sucursales_pool):
    """Ordena las sucursales estrictamente por el vecino más cercano (Ruta óptima)."""
    ordenado, restantes = [], sucursales_pool.copy()
    curr_lat, curr_lon = inicio_lat, inicio_lon
    
    while restantes:
        mejor_idx, min_dist = 0, float('inf')
        for idx, s in enumerate(restantes):
            d = math.sqrt((float(s['latitud']) - curr_lat)**2 + (float(s['longitud']) - curr_lon)**2)
            if d < min_dist:
                min_dist, mejor_idx = d, idx
        s_elegida = restantes.pop(mejor_idx)
        ordenado.append(s_elegida)
        curr_lat, curr_lon = float(s_elegida['latitud']), float(s_elegida['longitud'])
        
    return ordenado

def generar_clusters_geograficos(inicio_lat, inicio_lon, sucursales_pool, visitas_por_ruta):
    """Algoritmo de clustering GEOGRÁFICO PURO. Sin penalización por marca."""
    pool = [s for s in sucursales_pool if str(s.get('estatus_visita', 'PENDIENTE')).upper() != 'COMPLETADA']
    if not pool:
        return []
        
    N = len(pool)
    K = max(1, math.ceil(N / visitas_por_ruta))
    
    # 1. Encontrar los puntos centrales (centroides) lo más alejados entre sí para armar zonas
    centroids = []
    pool_copy = pool.copy()
    
    # El primer centroide es el más cercano al origen
    first_c = min(pool_copy, key=lambda s: math.sqrt((float(s['latitud']) - inicio_lat)**2 + (float(s['longitud']) - inicio_lon)**2))
    centroids.append(first_c)
    pool_copy.remove(first_c)
    
    while len(centroids) < K and pool_copy:
        best_cand = max(pool_copy, key=lambda s: min(math.sqrt((float(s['latitud']) - float(c['latitud']))**2 + (float(s['longitud']) - float(c['longitud']))**2) for c in centroids))
        centroids.append(best_cand)
        pool_copy.remove(best_cand)
            
    # 2. Asignar tiendas al centroide MÁS CERCANO (Geometría pura)
    clusters = [[] for _ in range(K)]
    restantes = pool.copy()
    
    # Inyectar los centroides a sus propios clusters
    for i in range(K):
        clusters[i].append(centroids[i])
        if centroids[i] in restantes:
            restantes.remove(centroids[i])
            
    while restantes:
        for i in range(K):
            if len(clusters[i]) >= visitas_por_ruta or not restantes:
                continue
            
            c_lat, c_lon = float(centroids[i]['latitud']), float(centroids[i]['longitud'])
            
            best_idx, min_dist = -1, float('inf')
            
            # Buscar puramente por distancia euclidiana
            for idx, s in enumerate(restantes):
                dist = math.sqrt((float(s['latitud']) - c_lat)**2 + (float(s['longitud']) - c_lon)**2)
                if dist < min_dist:
                    min_dist, best_idx = dist, idx
                    
            if best_idx != -1:
                clusters[i].append(restantes.pop(best_idx))
                
    # 3. Optimizar el ruteo interno de cada clúster conectando con el Punto de Origen
    return [optimizar_secuencia_por_proximidad(inicio_lat, inicio_lon, clus) for clus in clusters if clus]