import streamlit as st
import ezdxf
import math
import re
import pandas as pd
import os
import tempfile
import io
from collections import defaultdict

# --- CONFIGURACIÓN GENERAL ---
TAMANO_MARCADOR = 4.0 
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

REDUCCIONES_DIRECTAS = [
    (315, 250), (250, 200), (200, 160), (200, 140),
    (160, 140), (160, 110), (140, 110), (140, 90),
    (110, 90), (110, 75), (90, 75), (90, 63), (75, 63)
]

def obtener_datos_empresa(accesorio_str, catalogo_empresa=None):
    if catalogo_empresa is None: catalogo_empresa = {}
    if accesorio_str in catalogo_empresa: return catalogo_empresa[accesorio_str]
    return {"codigo": "S.C.", "desc_oficial": accesorio_str.upper()}

def calcular_reducciones_cascada(d_max, d_min):
    if d_max <= d_min: return []
    cola = [[d_max]]
    visitados = {d_max}
    while cola:
        camino = cola.pop(0)
        nodo_actual = camino[-1]
        if nodo_actual == d_min:
            resultado = []
            for i in range(len(camino)-1): resultado.append(f"Reducción {camino[i]}mm - {camino[i+1]}mm")
            return resultado
        for mayor, menor in REDUCCIONES_DIRECTAS:
            if mayor == nodo_actual and menor not in visitados:
                visitados.add(menor)
                nuevo_camino = list(camino)
                nuevo_camino.append(menor)
                cola.append(nuevo_camino)
    return [f"Reducción {d_max}mm - {d_min}mm"]

def obtener_clave_coord(x, y): return f"{round(x, 2)},{round(y, 2)}"
def extraer_num(diam_str): return int(re.search(r'\d+', diam_str).group()) if re.search(r'\d+', diam_str) else 0

def calcular_angulo_entre_lineas(p_centro, p_extremo1, p_extremo2):
    v1 = (p_extremo1[0] - p_centro[0], p_extremo1[1] - p_centro[1])
    v2 = (p_extremo2[0] - p_centro[0], p_extremo2[1] - p_centro[1])
    dot_product = v1[0] * v2[0] + v1[1] * v2[1]
    mag1, mag2 = math.sqrt(v1[0]**2 + v1[1]**2), math.sqrt(v2[0]**2 + v2[1]**2)
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
    longitud_ramal = 0.0
    diam_ramal = 0
    for _ in range(1000):
        conexiones = grafo[curr_coord]
        grado = len(conexiones)
        if grado == 1:
            if prev_coord is not None: return True
            conn = conexiones[0]
            diam_ramal = extraer_num(MAPA_DIAMETROS[conn['color']])
            longitud_ramal += math.dist(conn['centro'], conn['vecino'])
            prev_coord, curr_coord = curr_coord, obtener_clave_coord(*conn['vecino'])
        elif grado == 2:
            c1, c2 = conexiones[0], conexiones[1]
            v1, v2 = obtener_clave_coord(*c1['vecino']), obtener_clave_coord(*c2['vecino'])
            c_next, next_coord = (c2, v2) if v1 == prev_coord else (c1, v1)
            longitud_ramal += math.dist(c_next['centro'], c_next['vecino'])
            prev_coord, curr_coord = curr_coord, next_coord
        elif grado >= 3:
            if diam_ramal in [75, 90] and longitud_ramal < 6.0: return False
            d_max = max([extraer_num(MAPA_DIAMETROS[c['color']]) for c in conexiones])
            d_prev = extraer_num(MAPA_DIAMETROS[[c for c in conexiones if obtener_clave_coord(*c['vecino']) == prev_coord][0]['color']])
            return d_prev == d_max
    return False

def dibujar_esquema_nodo(msp, cx, cy, id_nodo, conexiones_nodo, accesorios_lista, deflexion_real, catalogo_empresa):
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

        if hay_reduccion and diam_num < diam_max_nodo:
            if f"x{diam_num}x" not in " ".join(accesorios_lista):
                mitad_x, mitad_y = centro_esq_x + (R_LINEA/2) * math.cos(ang_rad), centro_esq_y + (R_LINEA/2) * math.sin(ang_rad)
                ang_perp = ang_rad + math.pi/2
                p_red1 = (mitad_x + 2.5*math.cos(ang_perp), mitad_y + 2.5*math.sin(ang_perp))
                p_red2 = (mitad_x - 2.5*math.cos(ang_perp), mitad_y - 2.5*math.sin(ang_perp))
                msp.add_line(p_red1, p_red2, dxfattribs={'layer': capa_lineas, 'color': 1}) 
                txt_x = mitad_x + 3.0 * math.cos(ang_perp)
                txt_y = mitad_y + 3.0 * math.sin(ang_perp) - 0.5
                msp.add_text("RED", dxfattribs={'insert': (txt_x, txt_y), 'height': 1.2, 'layer': capa_textos, 'color': 1})

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
        datos_empresa = obtener_datos_empresa(item, catalogo_empresa)
        msp.add_text(f"- [{datos_empresa['codigo']}]", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, y_texto), 'height': 1.4, 'layer': capa_textos, 'color': 3})
        msp.add_text(f"  {item}", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, y_texto - 1.8), 'height': 1.6, 'layer': capa_textos, 'color': 7})
        y_texto -= 4.0

def analizar_plano(ruta_archivo, catalogo_empresa=None):
    if catalogo_empresa is None: catalogo_empresa = {}
    try:
        doc = ezdxf.readfile(ruta_archivo)
        msp = doc.modelspace()
        for layer in ['METRADOS_PYTHON', '_ESQUEMAS_LINEAS', '_ESQUEMAS_TEXTOS']:
            if layer not in doc.layers: doc.layers.add(layer, color=2 if layer == 'METRADOS_PYTHON' else 7)
    except Exception as e:
        raise Exception(f"No se pudo leer el archivo DXF: {e}")

    grafo = defaultdict(list)
    max_x_dibujo, max_y_dibujo = -float('inf'), -float('inf')

    for entidad in msp:
        if not hasattr(entidad.dxf, 'color') or entidad.dxf.color not in MAPA_DIAMETROS:
            continue
            
        color = entidad.dxf.color

        if entidad.dxftype() == 'LINE':
            start = (float(entidad.dxf.start.x), float(entidad.dxf.start.y))
            end = (float(entidad.dxf.end.x), float(entidad.dxf.end.y))
            max_x_dibujo, max_y_dibujo = max(max_x_dibujo, start[0], end[0]), max(max_y_dibujo, start[1], end[1])
            key_start, key_end = obtener_clave_coord(*start), obtener_clave_coord(*end)
            grafo[key_start].append({'color': color, 'vecino': end, 'centro': start})
            grafo[key_end].append({'color': color, 'vecino': start, 'centro': end})
            
        elif entidad.dxftype() == 'LWPOLYLINE':
            puntos = entidad.get_points(format='xy')
            for i in range(len(puntos) - 1):
                start = (float(puntos[i][0]), float(puntos[i][1]))
                end = (float(puntos[i+1][0]), float(puntos[i+1][1]))
                max_x_dibujo, max_y_dibujo = max(max_x_dibujo, start[0], end[0]), max(max_y_dibujo, start[1], end[1])
                key_start, key_end = obtener_clave_coord(*start), obtener_clave_coord(*end)
                grafo[key_start].append({'color': color, 'vecino': end, 'centro': start})
                grafo[key_end].append({'color': color, 'vecino': start, 'centro': end})
                
        elif entidad.dxftype() == 'POLYLINE':
            puntos = [(float(v.dxf.location.x), float(v.dxf.location.y)) for v in entidad.vertices]
            for i in range(len(puntos) - 1):
                start = puntos[i]
                end = puntos[i+1]
                max_x_dibujo, max_y_dibujo = max(max_x_dibujo, start[0], end[0]), max(max_y_dibujo, start[1], end[1])
                key_start, key_end = obtener_clave_coord(*start), obtener_clave_coord(*end)
                grafo[key_start].append({'color': color, 'vecino': end, 'centro': start})
                grafo[key_end].append({'color': color, 'vecino': start, 'centro': end})

    if max_x_dibujo == -float('inf'):
        return None, None, []

    resultados_nodos, deflexiones_nodos = {}, {} 
    for coord_key, conexiones in grafo.items():
        grado = len(conexiones)
        diametros_num = [extraer_num(MAPA_DIAMETROS[c['color']]) for c in conexiones]
        d_max = max(diametros_num) if diametros_num else 0
        accesorios_en_este_nodo = []
        deflexion_actual = 0

        if grado == 1:
            if es_final_principal(coord_key, grafo): accesorios_en_este_nodo.append(f"Purga/Desfogue {d_max}mm")
        elif grado == 2:
            conn1, conn2 = conexiones[0], conexiones[1]
            angulo_accesorio = 180 - calcular_angulo_entre_lineas(conn1['centro'], conn1['vecino'], conn2['vecino'])
            deflexion_actual = angulo_accesorio
            tipo_curva = clasificar_curva_comercial(angulo_accesorio)
            d1, d2 = diametros_num[0], diametros_num[1]
            if tipo_curva == "RECTO":
                if d1 != d2: accesorios_en_este_nodo.extend(calcular_reducciones_cascada(max(d1, d2), min(d1, d2)))
            else:
                d_max_local, d_min_local = max(d1, d2), min(d1, d2)
                accesorios_en_este_nodo.append(f"Curva {tipo_curva} de {d_max_local}mm")
                if d1 != d2: accesorios_en_este_nodo.append(f"Reducción {d_max_local}mm - {d_min_local}mm")
        elif grado == 3:
            max_angulo = -1
            idx_m1, idx_m2 = -1, -1
            for i in range(3):
                for j in range(i+1, 3):
                    ang = calcular_angulo_entre_lineas(conexiones[i]['centro'], conexiones[i]['vecino'], conexiones[j]['vecino'])
                    if ang > max_angulo: max_angulo, idx_m1, idx_m2 = ang, i, j
            indices = {0, 1, 2}
            indices.remove(idx_m1); indices.remove(idx_m2)
            idx_r = list(indices)[0] 
            d_m1, d_m2, d_r = extraer_num(MAPA_DIAMETROS[conexiones[idx_m1]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[idx_m2]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[idx_r]['color']])
            d_main_max, d_main_min = max(d_m1, d_m2), min(d_m1, d_m2)
            long_branch = math.dist(conexiones[idx_r]['centro'], conexiones[idx_r]['vecino'])
            es_ramal_valvula = (d_r in [75, 90] and long_branch < 6.0)
            nombre_tee = f"Tee Reducida {d_main_max}x{d_r}x{d_main_max}mm" if d_main_max != d_r else f"Tee {d_main_max}mm"
            
            if nombre_tee in catalogo_empresa or es_ramal_valvula: accesorios_en_este_nodo.append(nombre_tee)
            else:
                accesorios_en_este_nodo.append(f"Tee {d_main_max}mm")
                accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_r))
            if d_main_max != d_main_min: accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_main_min))
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
            d_m1, d_m2 = extraer_num(MAPA_DIAMETROS[conexiones[idx_m1]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[idx_m2]['color']])
            d_main_max, d_main_min = max(d_m1, d_m2), min(d_m1, d_m2)
            for idx_r in indices_ramales:
                d_r = extraer_num(MAPA_DIAMETROS[conexiones[idx_r]['color']])
                long_branch = math.dist(conexiones[idx_r]['centro'], conexiones[idx_r]['vecino'])
                es_ramal_valvula = (d_r in [75, 90] and long_branch < 6.0)
                nombre_tee = f"Tee Reducida {d_main_max}x{d_r}x{d_main_max}mm" if d_main_max != d_r else f"Tee {d_main_max}mm"
                if nombre_tee in catalogo_empresa or es_ramal_valvula: accesorios_en_este_nodo.append(nombre_tee)
                else: 
                    accesorios_en_este_nodo.append(f"Tee {d_main_max}mm")
                    accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_r))
            if d_main_max != d_main_min: accesorios_en_este_nodo.extend(calcular_reducciones_cascada(d_main_max, d_main_min))

        if accesorios_en_este_nodo:
            resultados_nodos[coord_key] = accesorios_en_este_nodo
            deflexiones_nodos[coord_key] = deflexion_actual

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
            datos = obtener_datos_empresa(acc, catalogo_empresa)
            detalles_nodos_excel.append({'ID Nodo CAD': nombre_nodo, 'Coord X': round(x, 2), 'Coord Y': round(y, 2), 'Código ERP': datos['codigo'], 'Descripción Comercial': datos['desc_oficial'], 'Accesorio Geométrico': acc})
            if "Purga/Desfogue" in acc:
                es_purga = True
                diam_out = acc.replace("Purga/Desfogue ", "")
                capa_out = f"_OUT_MATRIZ_{diam_out.upper()}"
                if capa_out not in doc.layers: doc.layers.add(capa_out, color=1)
                msp.add_text(f"OUT {diam_out}", dxfattribs={'insert': (x + TAMANO_MARCADOR*1.2, y - TAMANO_MARCADOR*1.5), 'height': TAMANO_MARCADOR, 'layer': capa_out})

        if not es_purga:
            cx_esq, cy_esq = start_esq_x + (col_actual * 80), start_esq_y - (row_actual * 80)
            dibujar_esquema_nodo(msp, cx_esq, cy_esq, nombre_nodo, grafo[coord_key], accesorios, deflexion, catalogo_empresa)
            col_actual += 1
            if col_actual >= 4: col_actual, row_actual = 0, row_actual + 1
        contador_nodo += 1

    resumen_excel = []
    for acc, cant in sorted(conteo_accesorios.items()):
        datos = obtener_datos_empresa(acc, catalogo_empresa)
        resumen_excel.append({'Código ERP': datos['codigo'], 'Descripción Comercial': datos['desc_oficial'], 'Accesorio Geométrico': acc, 'Cantidad': cant})
        
    # Guardamos en un buffer en memoria (ideal para Streamlit)
    doc_io = io.StringIO()
    doc.write(doc_io)
    cad_str = doc_io.getvalue()

    # Guardamos Excel en un BytesIO
    excel_io = io.BytesIO()
    with pd.ExcelWriter(excel_io, engine='openpyxl') as writer:
        pd.DataFrame(resumen_excel).to_excel(writer, sheet_name="BOM - Para Compras", index=False)
        pd.DataFrame(detalles_nodos_excel).to_excel(writer, sheet_name="Replanteo Topográfico", index=False)
    excel_bytes = excel_io.getvalue()
    
    return cad_str, excel_bytes, resumen_excel

def traducir_a_geometria(desc_str):
    desc_str = str(desc_str).upper()
    # Detecta "CURVA PVC 140 UF X 30°" -> Curva 30° de 140mm
    m_curva = re.search(r'CURVA.*?PVC.*?\b(\d+)\b.*?X\s*(\d+)°?', desc_str)
    if m_curva: return f"Curva {m_curva.group(2)}° de {m_curva.group(1)}mm"
    
    # Detecta "TEE REDUCCION PVC UF/SP 160MM X 90MM" -> Tee Reducida 160x90x160mm
    m_tee_red = re.search(r'TEE\s+REDUC.*?\b(\d+)\s*M?M?\s*[X]\s*(\d+)\s*M?M?', desc_str)
    if m_tee_red: return f"Tee Reducida {m_tee_red.group(1)}x{m_tee_red.group(2)}x{m_tee_red.group(1)}mm"
    
    # Detecta "TEE PVC UF 200 MM" -> Tee 200mm
    m_tee = re.search(r'TEE\s+(?:RECTA\s+)?PVC.*?\b(\d+)\s*M?M?', desc_str)
    if m_tee and not 'REDUC' in desc_str: return f"Tee {m_tee.group(1)}mm"
    
    # Detecta "REDUCCION PVC UF 160MM X 140MM" -> Reducción 160mm - 140mm
    m_red = re.search(r'REDUCCI[OÓ]N.*?PVC.*?\b(\d+)\s*M?M?\s*[XA]\s*(\d+)\s*M?M?', desc_str)
    if m_red and 'TEE' not in desc_str: return f"Reducción {m_red.group(1)}mm - {m_red.group(2)}mm"
    return None


def main():
    st.set_page_config(page_title="Metrados de Riego ERP", layout="wide", page_icon="💧")
    st.title("💧 Generador de Detalles y Metrados ERP")
    st.markdown("""
    Sube tu plano DXF para analizar la topología de la red, generar automáticamente 
    los esquemas de nodos en CAD y calcular la lista de compras.
    """)

    col1, col2 = st.columns(2)
    with col1:
        archivo_dxf = st.file_uploader("1️⃣ Sube tu archivo CAD (.dxf)", type=["dxf"])
    with col2:
        archivo_excel = st.file_uploader("2️⃣ Sube tu Catálogo Maestro (.xlsx o .csv) - Opcional", type=["xlsx", "csv"])

    if st.button("Procesar Plano de Riego", type="primary"):
        if archivo_dxf is None:
            st.error("Por favor, sube un archivo DXF.")
            return

        with st.spinner("Analizando la red y leyendo base de datos..."):
            try:
                catalogo_dict = {}
                if archivo_excel is not None:
                    file_ext = os.path.splitext(archivo_excel.name)[1].lower()
                    try:
                        if file_ext == '.csv':
                            try:
                                df_cat = pd.read_csv(archivo_excel, sep=';', encoding='utf-8-sig', on_bad_lines='skip')
                                if len(df_cat.columns) == 1:
                                    archivo_excel.seek(0)
                                    df_cat = pd.read_csv(archivo_excel, sep=',', encoding='utf-8-sig', on_bad_lines='skip')
                            except UnicodeDecodeError:
                                archivo_excel.seek(0)
                                df_cat = pd.read_csv(archivo_excel, sep=';', encoding='latin-1', on_bad_lines='skip')
                        else:
                            df_cat = pd.read_excel(archivo_excel)
                            
                        if not df_cat.empty:
                            cols_lower = [str(c).lower() for c in df_cat.columns]
                            col_cod = df_cat.columns[next((i for i, c in enumerate(cols_lower) if 'cód' in c or 'cod' in c or 'erp' in c), 0)]
                            col_desc = df_cat.columns[next((i for i, c in enumerate(cols_lower) if 'desc' in c or 'nom' in c), 1)]
                            
                            for _, row in df_cat.iterrows():
                                codigo_erp = str(row[col_cod]).strip()
                                descripcion_erp = str(row[col_desc]).strip()
                                clave_geometrica = traducir_a_geometria(descripcion_erp)
                                
                                if 'accesorio' in ' '.join(cols_lower):
                                    idx_acc = next((i for i, c in enumerate(cols_lower) if 'accesorio' in c), -1)
                                    if idx_acc != -1 and pd.notna(row.iloc[idx_acc]):
                                        clave_geometrica = str(row.iloc[idx_acc]).strip()
                                        
                                if clave_geometrica:
                                    catalogo_dict[clave_geometrica] = {
                                        "codigo": codigo_erp if codigo_erp and codigo_erp != 'nan' else "S.C.",
                                        "desc_oficial": descripcion_erp
                                    }
                        st.success(f"✅ Catálogo procesado: {len(catalogo_dict)} accesorios mapeados.")
                    except Exception as e:
                        st.warning(f"No se pudo leer el catálogo correctamente: {e}")

                # Guardar DXF en un archivo temporal seguro para ezdxf
                with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_dxf:
                    tmp_dxf.write(archivo_dxf.getvalue())
                    tmp_path = tmp_dxf.name

                cad_str, excel_bytes, resumen = analizar_plano(tmp_path, catalogo_dict)
                os.remove(tmp_path) # Limpiamos

                if not resumen:
                    st.warning("No se encontraron accesorios en el plano. Revisa los colores y las polilíneas.")
                    return

                st.success("¡Análisis completado con éxito!")
                st.subheader("📋 Resumen de Requerimientos (BOM)")
                st.dataframe(pd.DataFrame(resumen))

                st.markdown("### Descarga de Entregables")
                col_d1, col_d2 = st.columns(2)
                with col_d1:
                    st.download_button(
                        label="📥 Descargar Reporte Excel",
                        data=excel_bytes,
                        file_name=f"Metrados_{archivo_dxf.name.replace('.dxf', '')}.xlsx",
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )
                with col_d2:
                    st.download_button(
                        label="📥 Descargar Plano CAD (Detalles)",
                        data=cad_str,
                        file_name=f"Esquemas_{archivo_dxf.name}",
                        mime="application/dxf",
                        use_container_width=True
                    )

            except Exception as e:
                st.error(f"Ocurrió un error crítico durante el análisis: {str(e)}")

if __name__ == "__main__":
    main()
