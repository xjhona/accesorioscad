import streamlit as st
import ezdxf
import math
import re
import pandas as pd
import tempfile
import io
import os
from collections import defaultdict

# --- CONFIGURACIÓN DE PÁGINA STREAMLIT ---
st.set_page_config(page_title="Analizador CAD de Riego", page_icon="💧", layout="wide")

# --- VARIABLES GLOBALES Y DICCIONARIOS ---
TAMANO_MARCADOR = 4.0 

MAPA_DIAMETROS = {
    30: "63mm", 32: "63mm", 34: "63mm",
    6: "75mm", 215: "75mm",
    3: "90mm", 134: "90mm",
    4: "110mm", 171: "110mm",
    1: "140mm", 231: "140mm",
    2: "160mm", 52: "160mm",
    200: "200mm", 202: "200mm",
    5: "250mm", 160: "250mm", 170: "250mm",
    100: "315mm", 102: "315mm", 104: "315mm"
}

# --- FUNCIONES MATEMÁTICAS Y DE LÓGICA ---
def obtener_clave_coord(x, y):
    return f"{round(x, 2)},{round(y, 2)}"

def extraer_num(diam_str):
    m = re.search(r'\d+', diam_str)
    return int(m.group()) if m else 0

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
    dx = p_extremo[0] - p_centro[0]
    dy = p_extremo[1] - p_centro[1]
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
    curr_coord = coord_inicial
    prev_coord = None
    iteraciones = 0
    while iteraciones < 1000:
        iteraciones += 1
        conexiones = grafo[curr_coord]
        grado = len(conexiones)
        
        if grado == 1:
            if prev_coord is not None: return True
            siguiente = obtener_clave_coord(*conexiones[0]['vecino'])
            prev_coord = curr_coord
            curr_coord = siguiente
        elif grado == 2:
            v1 = obtener_clave_coord(*conexiones[0]['vecino'])
            v2 = obtener_clave_coord(*conexiones[1]['vecino'])
            siguiente = v1 if v2 == prev_coord else v2
            prev_coord = curr_coord
            curr_coord = siguiente
        elif grado >= 3:
            max_angulo = -1
            idx_m1, idx_m2 = -1, -1
            for i in range(len(conexiones)):
                for j in range(i+1, len(conexiones)):
                    ang = calcular_angulo_entre_lineas(conexiones[i]['centro'], conexiones[i]['vecino'], conexiones[j]['vecino'])
                    if ang > max_angulo: max_angulo, idx_m1, idx_m2 = ang, i, j
            vec_m1 = obtener_clave_coord(*conexiones[idx_m1]['vecino'])
            vec_m2 = obtener_clave_coord(*conexiones[idx_m2]['vecino'])
            
            if prev_coord == vec_m1 or prev_coord == vec_m2: return True
            else: return False
    return False

def dibujar_esquema_nodo(msp, cx, cy, id_nodo, conexiones_nodo, accesorios_lista, deflexion_real):
    ANCHO_CAJA = 60
    ALTO_CAJA = 60
    R_LINEA = 15 
    capa_lineas = '_ESQUEMAS_LINEAS'
    capa_textos = '_ESQUEMAS_TEXTOS'

    p1 = (cx - ANCHO_CAJA/2, cy + ALTO_CAJA/2)
    p2 = (cx + ANCHO_CAJA/2, cy + ALTO_CAJA/2)
    p3 = (cx + ANCHO_CAJA/2, cy - ALTO_CAJA/2)
    p4 = (cx - ANCHO_CAJA/2, cy - ALTO_CAJA/2)
    msp.add_lwpolyline([p1, p2, p3, p4, p1], dxfattribs={'layer': capa_lineas, 'color': 8})
    
    msp.add_text(f"DETALLE NODO {id_nodo}", dxfattribs={
        'insert': (cx - ANCHO_CAJA/2 + 2, cy + ALTO_CAJA/2 - 4),
        'height': 2.5, 'layer': capa_textos, 'color': 2
    })

    centro_esq_x, centro_esq_y = cx, cy + 5
    msp.add_circle((centro_esq_x, centro_esq_y), radius=0.8, dxfattribs={'layer': capa_lineas, 'color': 7})

    angulos_absolutos = []
    hay_reduccion = any("Reducción" in a for a in accesorios_lista)
    diametros_conectados = [extraer_num(MAPA_DIAMETROS[c['color']]) for c in conexiones_nodo]
    diam_max_nodo = max(diametros_conectados) if diametros_conectados else 0

    for conn in conexiones_nodo:
        ang_abs = obtener_angulo_absoluto(conn['centro'], conn['vecino'])
        angulos_absolutos.append(ang_abs)
        ang_rad = math.radians(ang_abs)
        fin_x = centro_esq_x + R_LINEA * math.cos(ang_rad)
        fin_y = centro_esq_y + R_LINEA * math.sin(ang_rad)
        
        msp.add_line((centro_esq_x, centro_esq_y), (fin_x, fin_y), dxfattribs={'layer': capa_lineas, 'color': conn['color']})
        diam_texto = MAPA_DIAMETROS[conn['color']]
        diam_num = extraer_num(diam_texto)
        
        msp.add_text(diam_texto, dxfattribs={
            'insert': (fin_x + 1.5*math.cos(ang_rad), fin_y + 1.5*math.sin(ang_rad)),
            'height': 1.8, 'layer': capa_textos, 'color': 7
        })

        if hay_reduccion and diam_num < diam_max_nodo:
            mitad_x = centro_esq_x + (R_LINEA/2) * math.cos(ang_rad)
            mitad_y = centro_esq_y + (R_LINEA/2) * math.sin(ang_rad)
            ang_perp = ang_rad + math.pi/2
            w = 2.0
            p_red1 = (mitad_x + w*math.cos(ang_perp), mitad_y + w*math.sin(ang_perp))
            p_red2 = (mitad_x - w*math.cos(ang_perp), mitad_y - w*math.sin(ang_perp))
            msp.add_line(p_red1, p_red2, dxfattribs={'layer': capa_lineas, 'color': 1})
            msp.add_text(" RED", dxfattribs={'insert': (p_red1[0], p_red1[1]+1), 'height': 1.2, 'color': 1})

    es_curva = any("Curva" in a for a in accesorios_lista)
    if es_curva and len(angulos_absolutos) == 2:
        a1, a2 = angulos_absolutos[0], angulos_absolutos[1]
        start_a, end_a = min(a1, a2), max(a1, a2)
        if end_a - start_a > 180: start_a, end_a = end_a, start_a + 360
        msp.add_arc(
            (centro_esq_x, centro_esq_y), radius=R_LINEA * 0.4, 
            start_angle=start_a, end_angle=end_a, dxfattribs={'layer': capa_lineas, 'color': 2}
        )
        angulo_medio = math.radians((start_a + end_a) / 2)
        txt_x = centro_esq_x + (R_LINEA * 0.6) * math.cos(angulo_medio)
        txt_y = centro_esq_y + (R_LINEA * 0.6) * math.sin(angulo_medio)
        msp.add_text(f"{int(deflexion_real)}°", dxfattribs={'insert': (txt_x, txt_y), 'height': 2.0, 'layer': capa_textos, 'color': 2})

    y_texto = cy - 8
    msp.add_text("Requerimiento:", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 2, y_texto), 'height': 2.0, 'color': 7})
    y_texto -= 3.5
    for item in accesorios_lista:
        msp.add_text(f" - {item}", dxfattribs={'insert': (cx - ANCHO_CAJA/2 + 3, y_texto), 'height': 1.8, 'layer': capa_textos, 'color': 3})
        y_texto -= 3.0

# --- NÚCLEO DE PROCESAMIENTO (MOTOR PRINCIPAL) ---
def procesar_archivo_dxf(archivo_dxf):
    """
    Recibe un archivo cargado desde la web, lo procesa y devuelve:
    1. Un DataFrame de Resumen
    2. Un DataFrame de Detalle
    3. La ruta del nuevo DXF modificado (temporal)
    4. Métricas para mostrar en la interfaz
    """
    # Guardar archivo cargado en un temporal para que ezdxf lo pueda leer
    with tempfile.NamedTemporaryFile(delete=False, suffix=".dxf") as tmp_in:
        tmp_in.write(archivo_dxf.getvalue())
        ruta_entrada = tmp_in.name

    doc = ezdxf.readfile(ruta_entrada)
    msp = doc.modelspace()
    
    if 'METRADOS_PYTHON' not in doc.layers: doc.layers.add('METRADOS_PYTHON', color=2)
    if '_ESQUEMAS_LINEAS' not in doc.layers: doc.layers.add('_ESQUEMAS_LINEAS', color=7)
    if '_ESQUEMAS_TEXTOS' not in doc.layers: doc.layers.add('_ESQUEMAS_TEXTOS', color=7)

    grafo = defaultdict(list)
    elementos_procesados = 0
    max_x_dibujo, max_y_dibujo = -float('inf'), -float('inf')

    for entidad in msp:
        if entidad.dxftype() == 'LINE':
            color = entidad.dxf.color
            if color not in MAPA_DIAMETROS: continue 
            start = (entidad.dxf.start.x, entidad.dxf.start.y)
            end = (entidad.dxf.end.x, entidad.dxf.end.y)
            max_x_dibujo = max(max_x_dibujo, start[0], end[0])
            max_y_dibujo = max(max_y_dibujo, start[1], end[1])
            key_start = obtener_clave_coord(*start)
            key_end = obtener_clave_coord(*end)
            grafo[key_start].append({'color': color, 'vecino': end, 'centro': start})
            grafo[key_end].append({'color': color, 'vecino': start, 'centro': end})
            elementos_procesados += 1

    resultados_nodos = {} 
    deflexiones_nodos = {}

    for coord_key, conexiones in grafo.items():
        grado = len(conexiones)
        colores = list(set([c['color'] for c in conexiones]))
        accesorios_en_este_nodo = []
        deflexion_actual = 0

        if grado == 1:
            if es_final_principal(coord_key, grafo):
                diam = MAPA_DIAMETROS[conexiones[0]['color']]
                accesorios_en_este_nodo.append(f"Purga/Desfogue {diam}")

        elif grado == 2:
            conn1, conn2 = conexiones[0], conexiones[1]
            angulo_interno = calcular_angulo_entre_lineas(conn1['centro'], conn1['vecino'], conn2['vecino'])
            angulo_accesorio = 180 - angulo_interno
            deflexion_actual = angulo_accesorio
            tipo_curva = clasificar_curva_comercial(angulo_accesorio)
            diam_1, diam_2 = MAPA_DIAMETROS[conn1['color']], MAPA_DIAMETROS[conn2['color']]
            if tipo_curva == "RECTO":
                if diam_1 != diam_2:
                    d1, d2 = extraer_num(diam_1), extraer_num(diam_2)
                    accesorios_en_este_nodo.append(f"Reducción {max(d1,d2)}mm - {min(d1,d2)}mm")
            else:
                if diam_1 == diam_2: accesorios_en_este_nodo.append(f"Curva {tipo_curva} de {diam_1}")
                else: accesorios_en_este_nodo.append(f"Curva {tipo_curva} Reducida {diam_1} - {diam_2}")

        elif grado == 3:
            max_angulo, idx_m1, idx_m2 = -1, -1, -1
            for i in range(3):
                for j in range(i+1, 3):
                    ang = calcular_angulo_entre_lineas(conexiones[i]['centro'], conexiones[i]['vecino'], conexiones[j]['vecino'])
                    if ang > max_angulo: max_angulo, idx_m1, idx_m2 = ang, i, j
            indices = {0, 1, 2}; indices.remove(idx_m1); indices.remove(idx_m2); idx_r = list(indices)[0]
            d_m1, d_m2, d_r = extraer_num(MAPA_DIAMETROS[conexiones[idx_m1]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[idx_m2]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[idx_r]['color']])
            d_max, d_min = max(d_m1, d_m2), min(d_m1, d_m2)
            if d_max == d_r: accesorios_en_este_nodo.append(f"Tee {d_max}mm")
            else: accesorios_en_este_nodo.append(f"Tee Reducida {d_max}x{d_r}x{d_max}mm")
            if d_max != d_min: accesorios_en_este_nodo.append(f"Reducción {d_max}mm - {d_min}mm")

        elif grado == 4:
            pares = []
            for i in range(4):
                for j in range(i+1, 4):
                    ang = calcular_angulo_entre_lineas(conexiones[i]['centro'], conexiones[i]['vecino'], conexiones[j]['vecino'])
                    if ang > 165:
                        d1, d2 = extraer_num(MAPA_DIAMETROS[conexiones[i]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[j]['color']])
                        pares.append((ang, d1+d2, i, j))
            if pares:
                pares.sort(key=lambda x: (x[1], x[0]), reverse=True); idx_m1, idx_m2 = pares[0][2], pares[0][3]
            else:
                d_list = [(extraer_num(MAPA_DIAMETROS[c['color']]), idx) for idx, c in enumerate(conexiones)]
                d_list.sort(reverse=True); idx_m1, idx_m2 = d_list[0][1], d_list[1][1]
            indices_ramales = {0, 1, 2, 3}; indices_ramales.remove(idx_m1); indices_ramales.remove(idx_m2)
            d_m1, d_m2 = extraer_num(MAPA_DIAMETROS[conexiones[idx_m1]['color']]), extraer_num(MAPA_DIAMETROS[conexiones[idx_m2]['color']])
            d_max, d_min = max(d_m1, d_m2), min(d_m1, d_m2)
            for idx_r in indices_ramales:
                d_r = extraer_num(MAPA_DIAMETROS[conexiones[idx_r]['color']])
                if d_max == d_r: accesorios_en_este_nodo.append(f"Tee {d_max}mm")
                else: accesorios_en_este_nodo.append(f"Tee Reducida {d_max}x{d_r}x{d_max}mm")
            if d_max != d_min: accesorios_en_este_nodo.append(f"Reducción {d_max}mm - {d_min}mm")

        if accesorios_en_este_nodo:
            resultados_nodos[coord_key] = accesorios_en_este_nodo
            deflexiones_nodos[coord_key] = deflexion_actual

    def get_xy(k): return map(float, k.split(','))
    todas_las_claves = list(grafo.keys())
    todas_las_claves.sort(key=lambda k: (-list(get_xy(k))[1], list(get_xy(k))[0]))

    visitados = set()
    orden_final_nodos = []
    for nodo_inicial in todas_las_claves:
        if nodo_inicial not in visitados:
            stack = [nodo_inicial]
            while stack:
                curr = stack.pop()
                if curr not in visitados:
                    visitados.add(curr)
                    if curr in resultados_nodos: orden_final_nodos.append(curr)
                    vecinos = [obtener_clave_coord(*c['vecino']) for c in grafo[curr]]
                    vecinos_no_visitados = [v for v in vecinos if v not in visitados]
                    vecinos_no_visitados.sort(key=lambda k: (-list(get_xy(k))[1], list(get_xy(k))[0]), reverse=True)
                    stack.extend(vecinos_no_visitados)

    conteo_accesorios = defaultdict(int)
    detalles_nodos = []
    contador_nodo = 1
    OFFSET_X = 100
    start_esquema_x = max_x_dibujo + OFFSET_X
    start_esquema_y = max_y_dibujo
    col_actual, row_actual = 0, 0
    MAX_COLUMNAS = 4

    for coord_key in orden_final_nodos:
        accesorios_en_este_nodo = resultados_nodos[coord_key]
        x, y = get_xy(coord_key)
        nombre_nodo = f"N-{contador_nodo}"

        msp.add_circle((x, y), radius=TAMANO_MARCADOR, dxfattribs={'layer': 'METRADOS_PYTHON'})
        msp.add_text(nombre_nodo, dxfattribs={'insert': (x + TAMANO_MARCADOR*1.2, y + TAMANO_MARCADOR*1.2), 'height': TAMANO_MARCADOR, 'layer': 'METRADOS_PYTHON'})

        es_purga = False
        for accesorio in accesorios_en_este_nodo:
            conteo_accesorios[accesorio] += 1
            detalles_nodos.append({'ID Nodo CAD': nombre_nodo, 'Coord X': x, 'Coord Y': y, 'Accesorio': accesorio})
            
            if "Purga/Desfogue" in accesorio:
                es_purga = True
                diam_out = accesorio.replace("Purga/Desfogue ", "")
                capa_out = f"_OUT_MATRIZ_{diam_out.upper()}"
                if capa_out not in doc.layers: doc.layers.add(capa_out, color=1)
                msp.add_text(f"OUT {diam_out}", dxfattribs={'insert': (x + TAMANO_MARCADOR*1.2, y - TAMANO_MARCADOR*1.5), 'height': TAMANO_MARCADOR, 'layer': capa_out})

        if not es_purga:
            cx_esq = start_esquema_x + (col_actual * 70) 
            cy_esq = start_esquema_y - (row_actual * 70)
            dibujar_esquema_nodo(msp, cx_esq, cy_esq, nombre_nodo, grafo[coord_key], accesorios_en_este_nodo, deflexiones_nodos[coord_key])
            col_actual += 1
            if col_actual >= MAX_COLUMNAS: col_actual, row_actual = 0, row_actual + 1
        contador_nodo += 1

    # Guardar DXF en temporal
    tmp_out = tempfile.NamedTemporaryFile(delete=False, suffix=".dxf")
    doc.saveas(tmp_out.name)
    ruta_salida = tmp_out.name
    
    # Crear Dataframes
    df_resumen = pd.DataFrame(list(conteo_accesorios.items()), columns=['Descripción de Accesorio', 'Cantidad (und)'])
    if not df_resumen.empty:
        df_resumen = df_resumen.sort_values(by='Descripción de Accesorio')
    df_detalle = pd.DataFrame(detalles_nodos)

    metricas = {
        "lineas_leidas": elementos_procesados,
        "nodos_analizados": len(grafo),
        "accesorios_totales": df_resumen['Cantidad (und)'].sum() if not df_resumen.empty else 0
    }
    
    # Limpiar archivo temporal de entrada
    os.remove(ruta_entrada)

    return df_resumen, df_detalle, ruta_salida, metricas

def generar_excel_memoria(df_resumen, df_detalle):
    """Escribe los DataFrames en un buffer de memoria en lugar del disco duro."""
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine='xlsxwriter') as writer:
        df_resumen.to_excel(writer, sheet_name="Resumen de Metrados", index=False)
        df_detalle.to_excel(writer, sheet_name="Detalle Constructivo", index=False)
    return buffer.getvalue()


# --- INTERFAZ GRÁFICA (UI) CON STREAMLIT ---
st.title("💧 Software CAD: Analizador Automático de Riego")
st.markdown("Sube tu plano `.dxf` de diseño de riego. El sistema detectará accesorios, numerará topológicamente la red, dibujará esquemas isométricos paramétricos 2D en tu plano, y generará un presupuesto exacto en Excel.")

with st.sidebar:
    st.header("Configuración de Capas")
    st.info("El sistema está configurado para leer las tuberías usando los colores índice estándar de AutoCAD.")
    with st.expander("Ver Leyenda de Colores"):
        st.write("🔴 **140mm:** Colores 1, 231")
        st.write("🟡 **160mm:** Colores 2, 52")
        st.write("🟢 **90mm:** Colores 3, 134")
        st.write("🔵 **110mm:** Colores 4, 171")
        st.write("🟣 **75mm:** Colores 6, 215")
        st.write("⚫ **200mm:** Colores 200, 202")

archivo_subido = st.file_uploader("Arrastra tu archivo .dxf aquí", type=["dxf"])

if archivo_subido is not None:
    st.success(f"Archivo cargado: {archivo_subido.name}")
    
    if st.button("🚀 Iniciar Análisis Completo", type="primary"):
        with st.spinner('Procesando topología, calculando ángulos y dibujando esquemas...'):
            try:
                # 1. Procesar
                df_resumen, df_detalle, ruta_dxf_salida, metricas = procesar_archivo_dxf(archivo_subido)
                
                # 2. Métricas Rápidas
                st.subheader("📊 Resultados del Análisis")
                col1, col2, col3 = st.columns(3)
                col1.metric("Líneas Válidas Procesadas", metricas["lineas_leidas"])
                col2.metric("Uniones (Nodos) Evaluados", metricas["nodos_analizados"])
                col3.metric("Accesorios Totales Obtenidos", metricas["accesorios_totales"])

                if df_resumen.empty:
                    st.warning("No se encontraron accesorios en este plano. Verifica que las líneas usen los colores de la configuración.")
                else:
                    # 3. Mostrar Tablas
                    tab1, tab2 = st.tabs(["📝 Resumen para Presupuesto", "🗺️ Detalle Topográfico Constructivo"])
                    with tab1:
                        st.dataframe(df_resumen, use_container_width=True, hide_index=True)
                    with tab2:
                        st.dataframe(df_detalle, use_container_width=True, hide_index=True)

                    # 4. Zona de Descargas
                    st.divider()
                    st.subheader("⬇️ Descargar Entregables Generados")
                    col_down1, col_down2 = st.columns(2)
                    
                    # Generar Excel en memoria
                    excel_data = generar_excel_memoria(df_resumen, df_detalle)
                    
                    # Leer DXF temporal
                    with open(ruta_dxf_salida, "rb") as f:
                        dxf_data = f.read()

                    nombre_base = archivo_subido.name.replace('.dxf', '')

                    with col_down1:
                        st.download_button(
                            label="📥 Descargar Plano CAD (DXF) con Esquemas",
                            data=dxf_data,
                            file_name=f"{nombre_base}_NUMERADO_CON_ESQUEMAS.dxf",
                            mime="application/dxf",
                            use_container_width=True
                        )
                    
                    with col_down2:
                        st.download_button(
                            label="📥 Descargar Reporte de Metrados (Excel)",
                            data=excel_data,
                            file_name=f"{nombre_base}_REPORTE_METRADOS.xlsx",
                            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                            use_container_width=True
                        )

            except Exception as e:
                st.error(f"Ocurrió un error procesando el archivo. Detalles técnicos: {e}")