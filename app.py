import ezdxf
import math
import os
import re
import pandas as pd
import streamlit as st
from collections import defaultdict

# --- CONFIGURACIÓN GENERAL ---
ARCHIVO_DEFECTO = "prueba_riego.dxf"
TAMANO_MARCADOR = 4.0 

# MAPA DE COLORES ACTUALIZADO
MAPA_DIAMETROS = {
    30: "63mm", 32: "63mm", 34: "63mm",
    6: "75mm", 215: "75mm",
    3: "90mm", 134: "90mm",
    4: "110mm", 171: "110mm",
    1: "140mm", 231: "140mm",
    2: "160mm", 52: "160mm",
    200: "200mm", 202: "200mm",
    5: "250mm", 171: "250mm", 170: "250mm",
    100: "315mm", 102: "315mm", 104: "315mm"
}

# --- NUEVO: SALTOS DE REDUCCIÓN COMERCIAL PERMITIDOS ---
# Si no existe salto directo, el algoritmo pasará por el intermedio más cercano
REDUCCIONES_DIRECTAS = [
    (315, 250), (250, 200), 
    (200, 160), (200, 140), # 200 a 140 es válido
    (160, 140), (160, 110), 
    (140, 110), (140, 90),  # 140 a 90 es válido
    (110, 90), (110, 75), 
    (90, 75), (90, 63), 
    (75, 63)
]

# --- BASE DE DATOS DE LA EMPRESA (CATÁLOGO MAESTRO) ---
BASE_DATOS_EMPRESA = {
    "Curva 30° de 140mm": {"codigo": "101031657", "desc_oficial": "CURVA PVC 140 UF X 30°"},
    "Curva 30° de 200mm": {"codigo": "101077136", "desc_oficial": "CURVA PVC 200 UF X 30°"},
    "Curva 30° de 90mm": {"codigo": "S.C.", "desc_oficial": "CURVA PVC 90 SP X 30°"},
    "Curva 45° de 90mm": {"codigo": "101076226", "desc_oficial": "CURVA PVC 90 SP X 45°"},
    "Curva 60° de 140mm": {"codigo": "S.C.", "desc_oficial": "CURVA PVC 140 UF X 60°"},
    "Curva 60° de 200mm": {"codigo": "101077145", "desc_oficial": "CURVA PVC 200 UF X 60°"},
    "Curva 90° de 140mm": {"codigo": "101091517", "desc_oficial": "CURVA PVC 140 UF X 90°"},
    "Curva 90° de 200mm": {"codigo": "101039856", "desc_oficial": "CURVA PVC 200 UF X 90°"},
    "Curva 90° de 250mm": {"codigo": "101076415", "desc_oficial": "CURVA PVC 250 UF X 90°"},
    "Curva 90° de 90mm": {"codigo": "101047316", "desc_oficial": "CURVA PVC 90 SP X 90°"},
    
    "Reducción 140mm - 90mm": {"codigo": "101076459", "desc_oficial": "REDUCCION PVC SP 140MM X 90MM"},
    "Reducción 200mm - 140mm": {"codigo": "101076509", "desc_oficial": "REDUCCION PVC UF 200MM X 140MM"},
    
    "Tee 200mm": {"codigo": "101076635", "desc_oficial": "TEE PVC UF 200 MM"},
    "Tee 250mm": {"codigo": "101076880", "desc_oficial": "TEE PVC UF 250 MM"},
    "Tee 90mm": {"codigo": "101004364", "desc_oficial": "TEE PVC SP 90 MM"},

    # Mantenemos algunos de prueba anteriores para evitar errores en el dibujo de muestra
    "Curva 90° de 110mm": {"codigo": "ACC-CUR-001", "desc_oficial": "CURVA PVC 90° 110MM UF"},
    "Tee Reducida 110x75x110mm": {"codigo": "ACC-TEE-045", "desc_oficial": "TEE REDUCIDA PVC INYECTADA 110X75MM"},
    "Tee Reducida 90x75x90mm": {"codigo": "ACC-TEE-042", "desc_oficial": "TEE REDUCIDA PVC INYECTADA 90X75MM"},
    "Tee 140mm": {"codigo": "ACC-TEE-140", "desc_oficial": "TEE RECTA PVC 140MM"},
    "Tee 110mm": {"codigo": "ACC-TEE-110", "desc_oficial": "TEE RECTA PVC 110MM"},
    "Reducción 110mm - 90mm": {"codigo": "ACC-RED-005", "desc_oficial": "REDUCCION CONICA PVC 110 A 90MM"},
    "Reducción 90mm - 75mm": {"codigo": "ACC-RED-008", "desc_oficial": "REDUCCION CONICA PVC 90 A 75MM"},
    "Purga/Desfogue 110mm": {"codigo": "VAL-PUR-110", "desc_oficial": "CONJUNTO VALVULA DE PURGA 110MM COMPLETA"}
}

def obtener_datos_empresa(accesorio_str):
    if accesorio_str in BASE_DATOS_EMPRESA:
        return BASE_DATOS_EMPRESA[accesorio_str]
    return {"codigo": "SIN-CODIGO", "desc_oficial": accesorio_str.upper() + " (A COTIZAR)"}

def calcular_reducciones_cascada(d_max, d_min):
    """Calcula el camino comercial más corto entre dos diámetros."""
    if d_max <= d_min: return []
    
    # Algoritmo BFS para encontrar la ruta de reducciones
    cola = [[d_max]]
    visitados = {d_max}
    
    while cola:
        camino = cola.pop(0)
        nodo_actual = camino[-1]
        
        if nodo_actual == d_min:
            resultado = []
            for i in range(len(camino)-1):
                resultado.append(f"Reducción {camino[i]}mm - {camino[i+1]}mm")
            return resultado
            
        for mayor, menor in REDUCCIONES_DIRECTAS:
            if mayor == nodo_actual and menor not in visitados:
                visitados.add(menor)
                nuevo_camino = list(camino)
                nuevo_camino.append(menor)
                cola.append(nuevo_camino)
                
    # Fallback si no hay ruta registrada en la lista comercial
    return [f"Reducción {d_max}mm - {d_min}mm"]

# --- PARTE 1: GENERADOR DE ARCHIVO DE PRUEBA ---
def crear_dxf_prueba():
    doc = ezdxf.new()
    msp = doc.modelspace()
    print(f"Generando archivo de prueba: {ARCHIVO_DEFECTO}...")

    # Codo 90° Reducido de 200mm a 140mm
    msp.add_line((0, 0), (0, 10), dxfattribs={'color': 200}) # 200mm
    msp.add_line((0, 10), (10, 10), dxfattribs={'color': 1}) # 140mm
    
    # Tee Compleja (Flujo 200mm, deriva a 140mm y 90mm Larga)
    msp.add_line((30, -10), (30, 0), dxfattribs={'color': 200}) # Matriz 200mm
    msp.add_line((30, 0), (45, 0), dxfattribs={'color': 1})     # Deriva a 140mm (Larga > 6m)
    msp.add_line((30, 0), (15, 0), dxfattribs={'color': 3})     # Deriva a 90mm (Larga > 6m)

    # NUEVO CASO EXCEPCIONAL: Válvula Hidráulica Directa
    # Matriz de 160mm con una derivación corta de 75mm (L = 4m)
    msp.add_line((100, 0), (100, 10), dxfattribs={'color': 2})  # Viene 160mm
    msp.add_line((100, 10), (100, 20), dxfattribs={'color': 2}) # Sigue 160mm
    msp.add_line((100, 10), (104, 10), dxfattribs={'color': 6}) # Ramal corto 75mm (L = 4m)

    # Cruz 
    msp.add_line((70, 0), (80, 0), dxfattribs={'color': 4})
    msp.add_line((80, 0), (90, 0), dxfattribs={'color': 4})
    msp.add_line((80, 0), (80, 10), dxfattribs={'color': 3}) 
    msp.add_line((80, 0), (80, -10), dxfattribs={'color': 6}) 

    doc.saveas(ARCHIVO_DEFECTO)
    print("Archivo generado exitosamente.\n")

# --- PARTE 2: LÓGICA MATEMÁTICA ---
def obtener_clave_coord(x, y): return f"{round(x, 2)},{round(y, 2)}"
def extraer_num(diam_str): return int(re.search(r'\d+', diam_str).group()) if re.search(r'\d+', diam_str) else 0

def calcular_angulo_entre_lineas(p_centro, p_extremo1, p_extremo2):
    v1 = (p_extremo1[0] - p_centro[0], p_extremo1[1] - p_centro[1])
    v2 = (p_extremo2[0] - p_centro[0], p_extremo2[1] - p_centro[1])
    dot_product = v1[0] * v2[0] + v1[1] * v2[1]
    mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
    mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
    if mag1 == 0 or mag2 == 0: return 0
    cos_theta = max(min(dot_product / (mag1 * mag2), 1.0), -1.0)
    return math.degrees(math.acos(cos_theta))

def obtener_angulo_absoluto(p_centro, p_extremo):
    dx, dy = p_extremo[0] - p_centro[0], p_extremo[1] - p_centro[1]
    angulo = math.degrees(math.atan2(dy, dx))
    return angulo if angulo >= 0 else angulo + 360

def clasificar_curva_comercial(angulo_deflexion):
    if angulo_deflexion < 15.0: return "RECTO"
    elif 15.0 <= angulo_deflexion < 37.5: return "30°"
    elif 37.5 <= angulo_deflexion < 52.5: return "45°"
    elif 52.5 <= angulo_deflexion < 75.0: return "60°"
    elif 75.0 <= angulo_deflexion < 105.0: return "90°"
    else: return f"ESPECIAL ({int(angulo_deflexion)}°)"

def es_final_principal(coord_inicial, grafo):
    curr_coord, prev_coord = coord_inicial, None
    for _ in range(1000):
        conexiones = grafo[curr_coord]
        grado = len(conexiones)
        if grado == 1:
            if prev_coord is not None: return True
            prev_coord, curr_coord = curr_coord, obtener_clave_coord(*conexiones[0]['vecino'])
        elif grado == 2:
            v1, v2 = obtener_clave_coord(*conexiones[0]['vecino']), obtener_clave_coord(*conexiones[1]['vecino'])
            prev_coord, curr_coord = curr_coord, (v1 if v2 == prev_coord else v2)
        elif grado >= 3:
            d_max = max([extraer_num(MAPA_DIAMETROS[c['color']]) for c in conexiones])
            d_prev = extraer_num(MAPA_DIAMETROS[[c for c in conexiones if obtener_clave_coord(*c['vecino']) == prev_coord][0]['color']])
            return d_prev == d_max
    return False

# --- PARTE 3: RUTINA DE DIBUJO DE ESQUEMAS ---
def dibujar_esquema_nodo(msp, cx, cy, id_nodo, conexiones_nodo, accesorios_lista, deflexion_real):
    ANCHO_CAJA, ALTO_CAJA, R_LINEA = 70, 75, 15 
    capa_lineas, capa_textos = '_ESQUEMAS_LINEAS', '_ESQUEMAS_TEXTOS'

    p1, p2 = (cx - ANCHO_CAJA/2, cy + ALTO_CAJA/2), (cx + ANCHO_CAJA/2, cy + ALTO_CAJA/2)
    p3, p4 = (cx + ANCHO_CAJA/2, cy - ALTO_CAJA/2), (cx - ANCHO_CAJA/2, cy - ALTO_CAJA/2)
    msp.add_lwpolyline([p1, p2, p3, p4, p1], dxfattribs={'layer': capa_lineas, 'color': 8}) 
    
    msp.add_text(f"DETALLE {id_nodo}", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, cy + ALTO_CAJA/2 - 4), 'height': 2.5, 'layer': capa_textos, 'color': 2})

    centro_esq_x, centro_esq_y = cx, cy + 8
    msp.add_circle((centro_esq_x, centro_esq_y), radius=0.8, dxfattribs={'layer': capa_lineas, 'color': 7})

    angulos_absolutos = []
    hay_reduccion = any("Reducción" in a for a in accesorios_lista)
    diametros_conectados = [extraer_num(MAPA_DIAMETROS[c['color']]) for c in conexiones_nodo]
    diam_max_nodo = max(diametros_conectados) if diametros_conectados else 0

    for conn in conexiones_nodo:
        ang_abs = obtener_angulo_absoluto(conn['centro'], conn['vecino'])
        angulos_absolutos.append(ang_abs)
        ang_rad = math.radians(ang_abs)
        fin_x, fin_y = centro_esq_x + R_LINEA * math.cos(ang_rad), centro_esq_y + R_LINEA * math.sin(ang_rad)
        
        msp.add_line((centro_esq_x, centro_esq_y), (fin_x, fin_y), dxfattribs={'layer': capa_lineas, 'color': conn['color']})
        
        diam_texto = MAPA_DIAMETROS[conn['color']]
        diam_num = extraer_num(diam_texto)
        msp.add_text(diam_texto, dxfattribs={'insert': (fin_x + 1.5*math.cos(ang_rad), fin_y + 1.5*math.sin(ang_rad)), 'height': 1.8, 'layer': capa_textos, 'color': 7})

        # Dibujar marca roja de Reducción en el esquema
        if hay_reduccion and diam_num < diam_max_nodo:
            # Si se usó una Tee especial, no requiere el símbolo de reducción anexo en ese ramal
            if f"x{diam_num}x" not in " ".join(accesorios_lista):
                mitad_x, mitad_y = centro_esq_x + (R_LINEA/2) * math.cos(ang_rad), centro_esq_y + (R_LINEA/2) * math.sin(ang_rad)
                ang_perp = ang_rad + math.pi/2
                p_red1 = (mitad_x + 2.0*math.cos(ang_perp), mitad_y + 2.0*math.sin(ang_perp))
                p_red2 = (mitad_x - 2.0*math.cos(ang_perp), mitad_y - 2.0*math.sin(ang_perp))
                msp.add_line(p_red1, p_red2, dxfattribs={'layer': capa_lineas, 'color': 1}) 
                msp.add_text(" RED", dxfattribs={'insert': (p_red1[0], p_red1[1]+1), 'height': 1.2, 'color': 1})

    es_curva = any("Curva" in a for a in accesorios_lista)
    if es_curva and len(angulos_absolutos) == 2:
        a1, a2 = angulos_absolutos[0], angulos_absolutos[1]
        start_a, end_a = min(a1, a2), max(a1, a2)
        if end_a - start_a > 180: start_a, end_a = end_a, start_a + 360
        msp.add_arc((centro_esq_x, centro_esq_y), radius=R_LINEA * 0.4, start_angle=start_a, end_angle=end_a, dxfattribs={'layer': capa_lineas, 'color': 2})
        angulo_medio = math.radians((start_a + end_a) / 2)
        txt_x, txt_y = centro_esq_x + (R_LINEA * 0.6) * math.cos(angulo_medio), centro_esq_y + (R_LINEA * 0.6) * math.sin(angulo_medio)
        msp.add_text(f"{int(deflexion_real)}°", dxfattribs={'insert': (txt_x, txt_y), 'height': 2.0, 'layer': capa_textos, 'color': 2})

    y_texto = cy - 8
    msp.add_text("Requerimiento:", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, y_texto), 'height': 2.0, 'color': 7})
    y_texto -= 3.5
    for item in accesorios_lista:
        datos_empresa = obtener_datos_empresa(item)
        msp.add_text(f"- [{datos_empresa['codigo']}]", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, y_texto), 'height': 1.4, 'layer': capa_textos, 'color': 3})
        msp.add_text(f"  {item}", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, y_texto - 1.8), 'height': 1.6, 'layer': capa_textos, 'color': 7})
        y_texto -= 4.0

# --- PARTE 4: ANÁLISIS DEL PLANO Y GENERACIÓN DE REPORTE ---
def analizar_plano(ruta_archivo):
    print(f"\n>>> PROCESANDO ARCHIVO: {ruta_archivo}")
    try:
        doc = ezdxf.readfile(ruta_archivo)
        msp = doc.modelspace()
        for layer in ['METRADOS_PYTHON', '_ESQUEMAS_LINEAS', '_ESQUEMAS_TEXTOS']:
            if layer not in doc.layers: doc.layers.add(layer, color=2 if layer == 'METRADOS_PYTHON' else 7)
    except Exception as e:
        print(f"[ERROR CRÍTICO] No se pudo leer el archivo: {e}")
        return

    grafo = defaultdict(list)
    max_x_dibujo, max_y_dibujo = -float('inf'), -float('inf')

    for entidad in msp:
        if entidad.dxftype() == 'LINE' and entidad.dxf.color in MAPA_DIAMETROS:
            start, end = (entidad.dxf.start.x, entidad.dxf.start.y), (entidad.dxf.end.x, entidad.dxf.end.y)
            max_x_dibujo, max_y_dibujo = max(max_x_dibujo, start[0], end[0]), max(max_y_dibujo, start[1], end[1])
            key_start, key_end = obtener_clave_coord(*start), obtener_clave_coord(*end)
            grafo[key_start].append({'color': entidad.dxf.color, 'vecino': end, 'centro': start})
            grafo[key_end].append({'color': entidad.dxf.color, 'vecino': start, 'centro': end})

    resultados_nodos, deflexiones_nodos = {}, {} 

    # --- ANÁLISIS DE TOPOLOGÍA ---
    for coord_key, conexiones in grafo.items():
        grado = len(conexiones)
        diametros_num = [extraer_num(MAPA_DIAMETROS[c['color']]) for c in conexiones]
        d_max = max(diametros_num) if diametros_num else 0
        accesorios_en_este_nodo = []
        deflexion_actual = 0

        if grado == 1:
            if es_final_principal(coord_key, grafo):
                accesorios_en_este_nodo.append(f"Purga/Desfogue {d_max}mm")

        elif grado == 2:
            conn1, conn2 = conexiones[0], conexiones[1]
            angulo_accesorio = 180 - calcular_angulo_entre_lineas(conn1['centro'], conn1['vecino'], conn2['vecino'])
            deflexion_actual = angulo_accesorio
            tipo_curva = clasificar_curva_comercial(angulo_accesorio)
            d1, d2 = diametros_num[0], diametros_num[1]
            
            if tipo_curva == "RECTO":
                accesorios_en_este_nodo.extend(calcular_reducciones_cascada(max(d1, d2), min(d1, d2)))
            else:
                accesorios_en_este_nodo.append(f"Curva {tipo_curva} de {d_max}mm")
                accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_max, min(d1, d2)))

        elif grado == 3:
            # 1. Identificar geométricamente la línea principal para aislar el ramal
            max_angulo = -1
            idx_m1, idx_m2 = -1, -1
            for i in range(3):
                for j in range(i+1, 3):
                    ang = calcular_angulo_entre_lineas(conexiones[i]['centro'], conexiones[i]['vecino'], conexiones[j]['vecino'])
                    if ang > max_angulo: max_angulo, idx_m1, idx_m2 = ang, i, j
            
            indices = {0, 1, 2}
            indices.remove(idx_m1)
            indices.remove(idx_m2)
            idx_r = list(indices)[0] # Índice del ramal derivado
            
            conn_m1, conn_m2, conn_r = conexiones[idx_m1], conexiones[idx_m2], conexiones[idx_r]
            
            d_m1 = extraer_num(MAPA_DIAMETROS[conn_m1['color']])
            d_m2 = extraer_num(MAPA_DIAMETROS[conn_m2['color']])
            d_r = extraer_num(MAPA_DIAMETROS[conn_r['color']])
            
            d_main_max = max(d_m1, d_m2)
            d_main_min = min(d_m1, d_m2)
            
            # --- EXCEPCIÓN: VÁLVULAS HIDRÁULICAS CORTAS ---
            long_branch = math.dist(conn_r['centro'], conn_r['vecino'])
            es_ramal_valvula = (d_r in [75, 90] and long_branch < 6.0)
            
            nombre_tee = f"Tee Reducida {d_main_max}x{d_r}x{d_main_max}mm" if d_main_max != d_r else f"Tee {d_main_max}mm"
            
            # Verificamos si la pieza existe en el catálogo O si es una excepción de válvula corta
            if nombre_tee in BASE_DATOS_EMPRESA or es_ramal_valvula:
                accesorios_en_este_nodo.append(nombre_tee)
            else:
                accesorios_en_este_nodo.append(f"Tee {d_main_max}mm")
                accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_r))
                
            # Si la tubería principal sufre reducción, se añade post-tee
            if d_main_max != d_main_min:
                accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_main_min))

        elif grado == 4:
            pares = []
            for i in range(4):
                for j in range(i+1, 4):
                    ang = calcular_angulo_entre_lineas(conexiones[i]['centro'], conexiones[i]['vecino'], conexiones[j]['vecino'])
                    if ang > 165:
                        d1, d2 = extraer_num(MAPA_DIAMETROS[conexiones[i]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[j]['color']])
                        pares.append((ang, d1+d2, i, j))
            
            if pares:
                pares.sort(key=lambda x: (x[1], x[0]), reverse=True)
                idx_m1, idx_m2 = pares[0][2], pares[0][3]
            else:
                d_list = [(extraer_num(MAPA_DIAMETROS[c['color']]), idx) for idx, c in enumerate(conexiones)]
                d_list.sort(reverse=True)
                idx_m1, idx_m2 = d_list[0][1], d_list[1][1]
            
            indices_ramales = {0, 1, 2, 3}
            indices_ramales.remove(idx_m1); indices_ramales.remove(idx_m2)
            
            d_m1 = extraer_num(MAPA_DIAMETROS[conexiones[idx_m1]['color']])
            d_m2 = extraer_num(MAPA_DIAMETROS[conexiones[idx_m2]['color']])
            d_main_max = max(d_m1, d_m2)
            d_main_min = min(d_m1, d_m2)
                
            for idx_r in indices_ramales:
                conn_r = conexiones[idx_r]
                d_r = extraer_num(MAPA_DIAMETROS[conn_r['color']])
                
                # --- EXCEPCIÓN: VÁLVULAS HIDRÁULICAS CORTAS EN CRUZ ---
                long_branch = math.dist(conn_r['centro'], conn_r['vecino'])
                es_ramal_valvula = (d_r in [75, 90] and long_branch < 6.0)
                
                nombre_tee = f"Tee Reducida {d_main_max}x{d_r}x{d_main_max}mm" if d_main_max != d_r else f"Tee {d_main_max}mm"
                
                if nombre_tee in BASE_DATOS_EMPRESA or es_ramal_valvula:
                    accesorios_en_este_nodo.append(nombre_tee)
                else: 
                    accesorios_en_este_nodo.append(f"Tee {d_main_max}mm")
                    accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_r))
                    
            if d_main_max != d_main_min:
                accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_main_min))

        if accesorios_en_este_nodo:
            resultados_nodos[coord_key] = accesorios_en_este_nodo
            deflexiones_nodos[coord_key] = deflexion_actual

    # --- DFS Y EXPORTACIÓN ---
    def get_xy(k): return map(float, k.split(','))
    todas_las_claves = sorted(list(grafo.keys()), key=lambda k: (-list(get_xy(k))[1], list(get_xy(k))[0]))

    visitados, orden_final_nodos = set(), []
    for nodo_inicial in todas_las_claves:
        if nodo_inicial not in visitados:
            stack = [nodo_inicial]
            while stack:
                curr = stack.pop()
                if curr not in visitados:
                    visitados.add(curr)
                    if curr in resultados_nodos: orden_final_nodos.append(curr)
                    vecinos = [obtener_clave_coord(*c['vecino']) for c in grafo[curr] if obtener_clave_coord(*c['vecino']) not in visitados]
                    vecinos.sort(key=lambda k: (-list(get_xy(k))[1], list(get_xy(k))[0]), reverse=True)
                    stack.extend(vecinos)

    conteo_accesorios, detalles_nodos_excel = defaultdict(int), []
    contador_nodo = 1
    start_esq_x, start_esq_y, col_actual, row_actual = max_x_dibujo + 100, max_y_dibujo, 0, 0

    for coord_key in orden_final_nodos:
        accesorios, deflexion = resultados_nodos[coord_key], deflexiones_nodos[coord_key]
        x, y = get_xy(coord_key)
        nombre_nodo = f"N-{contador_nodo}"

        msp.add_circle((x, y), radius=TAMANO_MARCADOR, dxfattribs={'layer': 'METRADOS_PYTHON'})
        msp.add_text(nombre_nodo, dxfattribs={'insert': (x + TAMANO_MARCADOR*1.2, y + TAMANO_MARCADOR*1.2), 'height': TAMANO_MARCADOR, 'layer': 'METRADOS_PYTHON'})

        es_purga = False
        for acc in accesorios:
            conteo_accesorios[acc] += 1
            datos = obtener_datos_empresa(acc)
            detalles_nodos_excel.append({'ID Nodo': nombre_nodo, 'Coord X': round(x, 2), 'Coord Y': round(y, 2), 'Cód. Empresa': datos['codigo'], 'Desc. Comercial': datos['desc_oficial'], 'Accesorio Geométrico': acc})
            if "Purga/Desfogue" in acc:
                es_purga = True
                diam_out = acc.replace("Purga/Desfogue ", "")
                capa_out = f"_OUT_MATRIZ_{diam_out.upper()}"
                if capa_out not in doc.layers: doc.layers.add(capa_out, color=1)
                msp.add_text(f"OUT {diam_out}", dxfattribs={'insert': (x + TAMANO_MARCADOR*1.2, y - TAMANO_MARCADOR*1.5), 'height': TAMANO_MARCADOR, 'layer': capa_out})

        if not es_purga:
            cx_esq, cy_esq = start_esq_x + (col_actual * 80), start_esq_y - (row_actual * 80)
            dibujar_esquema_nodo(msp, cx_esq, cy_esq, nombre_nodo, grafo[coord_key], accesorios, deflexion)
            col_actual += 1
            if col_actual >= 4: col_actual, row_actual = 0, row_actual + 1

        contador_nodo += 1

    print("\n" + "="*40 + "\nRESUMEN DE MATERIALES (COMERCIAL)\n" + "="*40)
    resumen_excel = []
    for acc, cant in sorted(conteo_accesorios.items()):
        datos = obtener_datos_empresa(acc)
        print(f"[{datos['codigo']}] {acc}: {cant} und.")
        resumen_excel.append({'Código ERP / SKU': datos['codigo'], 'Descripción Comercial (Compras)': datos['desc_oficial'], 'Accesorio Geométrico': acc, 'Cantidad Requerida': cant})
        
    base_nombre = ruta_archivo.replace('.dxf', '')
    ruta_cad = f"{base_nombre}_NUMERADO.dxf"
    doc.saveas(ruta_cad)
    print(f"\n-> Plano CAD y Esquemas guardados en: '{ruta_cad}'")

    ruta_excel = f"{base_nombre}_REPORTE.xlsx"
    with pd.ExcelWriter(ruta_excel) as writer:
        pd.DataFrame(resumen_excel).to_excel(writer, sheet_name="BOM - Para Compras", index=False)
        pd.DataFrame(detalles_nodos_excel).to_excel(writer, sheet_name="Replanteo Topográfico", index=False)
    print(f"-> Reporte Excel generado como: '{ruta_excel}'")
    
    return ruta_cad, ruta_excel, resumen_excel

if __name__ == "__main__":
    # --- INTERFAZ WEB STREAMLIT ---
    st.set_page_config(page_title="Metrados de Riego", layout="wide", page_icon="💧")
    
    st.title("💧 Generador de Detalles y Metrados ERP")
    st.markdown("""
    Sube tu plano DXF para analizar la topología de la red, generar automáticamente 
    los esquemas de nodos en CAD y calcular la lista de compras con códigos oficiales.
    """)

    archivo_subido = st.file_uploader("Sube tu archivo CAD (.dxf)", type=["dxf"])

    if archivo_subido is not None:
        ruta_temp = "temp_" + archivo_subido.name
        with open(ruta_temp, "wb") as f:
            f.write(archivo_subido.getbuffer())
            
        if st.button("Procesar Plano de Riego", type="primary"):
            with st.spinner("Analizando la red, calculando flujos y dibujando esquemas topográficos..."):
                try:
                    ruta_cad, ruta_excel, resumen = analizar_plano(ruta_temp)
                    st.success("¡Análisis completado con éxito!")
                    
                    st.subheader("📋 Resumen de Requerimientos (BOM)")
                    if resumen:
                        df_resumen = pd.DataFrame(resumen)
                        st.dataframe(df_resumen)
                    else:
                        st.warning("No se encontraron accesorios comerciales en el plano.")
                    
                    st.markdown("### Descarga de Entregables")
                    col1, col2 = st.columns(2)
                    
                    with col1:
                        with open(ruta_excel, "rb") as f:
                            st.download_button(
                                label="📥 Descargar Reporte Excel",
                                data=f, file_name=f"Metrados_{archivo_subido.name.replace('.dxf', '')}.xlsx",
                                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True
                            )
                    with col2:
                        with open(ruta_cad, "rb") as f:
                            st.download_button(
                                label="📥 Descargar Plano CAD con Esquemas",
                                data=f, file_name=f"Esquemas_{archivo_subido.name}",
                                mime="application/dxf", use_container_width=True
                            )
                except Exception as e:
                    st.error(f"Ocurrió un error inesperado al procesar el dibujo: {e}")
