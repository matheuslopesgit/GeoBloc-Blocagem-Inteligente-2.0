# Decompiled with PyLingual (https://pylingual.io)
# Internal filename: 'GeoBloc-Blocagem Inteligente 2.py'
# Bytecode version: 3.12.0rc2 (3531)
# Source timestamp: 1970-01-01 00:00:00 UTC (0)

global cancelar
import geopandas as gpd
import networkx as nx
import pandas as pd
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import queue
import time
import traceback
import warnings
from shapely.geometry import LineString
from shapely.ops import split
from shapely.prepared import prep
warnings.filterwarnings('ignore')
fila = queue.Queue()
cancelar = False
MIN_LINHA = 50
def enviar_log(msg):
    fila.put(('log', msg))
def enviar_progresso(v):
    fila.put(('progress', v))
def enviar_fim():
    fila.put(('fim', None))
def corrigir_geometria(gdf):
    try:
        from shapely.validation import make_valid
        return gdf.geometry.apply(make_valid)
    except:
        return gdf.buffer(0)
def cortar_linhas(linhas, redes):
    if redes is None or redes.empty:
        return linhas
    else:
        redes_union = redes.unary_union
        redes_prep = prep(redes_union)
        novas = []
        for linha in linhas.itertuples():
            geom = linha.geometry
            try:
                if redes_prep.intersects(geom):
                    partes = split(geom, redes_union)
                    for p in partes.geoms:
                        if p.length > 10:
                            nova = linhas.loc[[linha.Index]].copy()
                            nova.geometry = p
                            novas.append(nova)
                else:
                    novas.append(linhas.loc[[linha.Index]])
            except:
                novas.append(linhas.loc[[linha.Index]])
        return gpd.GeoDataFrame(pd.concat(novas), crs=linhas.crs)
def processar():
    try:
        t0 = time.time()
        enviar_log('🚀 Iniciando blocagem...')
        talhoes = gpd.read_file(entry_talhoes.get())
        linhas = gpd.read_file(entry_linhas.get())
        redes = None
        redes_union = None
        if entry_redes.get():
            redes = gpd.read_file(entry_redes.get())
            if redes.crs != talhoes.crs:
                redes = redes.to_crs(talhoes.crs)
            redes_union = redes.unary_union
        talhoes['geometry'] = corrigir_geometria(talhoes)
        linhas['geometry'] = corrigir_geometria(linhas)
        if talhoes.crs != linhas.crs:
            linhas = linhas.to_crs(talhoes.crs)
        enviar_log('✂️ Cortando linhas...')
        linhas = cortar_linhas(linhas, redes)
        enviar_progresso(20)
        enviar_log('🔗 Spatial Join...')
        join = gpd.sjoin(linhas, talhoes, predicate='intersects')
        modo = combo_agrupar.get()
        col_estagio = None
        col_variedade = None
        if modo in ['ESTAGIO', 'ESTAGIO + VARIEDADE']:
            col_estagio = [c for c in join.columns if '_ESTAGIO' in c][0]
        if modo in ['VARIEDADE', 'ESTAGIO + VARIEDADE']:
            col_variedade = [c for c in join.columns if '_VARIEDADE' in c][0]
        if modo == 'ESTAGIO':
            grupos = join.groupby(col_estagio)
        else:
            if modo == 'VARIEDADE':
                grupos = join.groupby(col_variedade)
            else:
                if modo == 'ESTAGIO + VARIEDADE':
                    grupos = join.groupby([col_estagio, col_variedade])
                else:
                    if modo == 'SEM CRITERIO':
                        grupos = [('SEM CRITERIO', join)]
                    else:
                        raise ValueError(f'Modo de agrupamento inválido: {modo}')
        resultado = []
        debug_linhas = []
        bloco_id = 1
        total = len(grupos)
        atual = 0
        for chave, grupo in grupos:
            atual += 1
            enviar_progresso(20 + int(atual / total * 60))
            if modo == 'ESTAGIO':
                estagio, variedade = (chave, 'TODOS')
            else:
                if modo == 'VARIEDADE':
                    estagio, variedade = ('TODOS', chave)
                else:
                    if modo == 'ESTAGIO + VARIEDADE':
                        estagio, variedade = chave
                    else:
                        if modo == 'SEM CRITERIO':
                            estagio, variedade = ('TODOS', 'TODOS')
            enviar_log(f'⚙️ {estagio} | {variedade}')
            G = nx.Graph()
            ids = grupo['index_right'].unique()
            for i in ids:
                G.add_node(i)
            for linha_id, sub in grupo.groupby(grupo.index):
                linha_geom = sub.iloc[0].geometry
                if linha_geom.length < MIN_LINHA:
                    continue
                else:
                    validos = []
                    for _, row in sub.iterrows():
                        talhao_geom = talhoes.loc[row['index_right']].geometry
                        inter = linha_geom.intersection(talhao_geom)
                        if inter.length >= MIN_LINHA:
                            validos.append(row['index_right'])
                    if len(validos) > 1:
                        for i in range(len(validos)):
                            for j in range(i + 1, len(validos)):
                                g1 = talhoes.loc[validos[i]].geometry
                                g2 = talhoes.loc[validos[j]].geometry
                                if redes_union is not None:
                                    linha_test = LineString([g1.centroid, g2.centroid])
                                    if linha_test.intersects(redes_union):
                                        continue
                                G.add_edge(validos[i], validos[j])
                                debug_linhas.append({'geometry': linha_geom, 'T1': validos[i], 'T2': validos[j]})
            componentes = list(nx.connected_components(G))
            ids_no_grafo = set()
            for c in componentes:
                ids_no_grafo.update(c)
            isolados = list(set(ids) - ids_no_grafo)
            for iso in isolados:
                componentes.append({iso})
            for comp in componentes:
                subset = talhoes.loc[list(comp)]
                geom = subset.unary_union
                linhas_bloco = linhas[linhas.intersects(geom)]
                comprimentos = []
                for _, l in linhas_bloco.iterrows():
                    inter = l.geometry.intersection(geom)
                    if inter.length > 0:
                        comprimentos.append(inter.length)
                total_len = sum(comprimentos)
                qtd = len(comprimentos)
                tiro_medio = total_len / qtd if qtd > 0 else 0
                media_pond = sum([c * c for c in comprimentos]) / total_len if total_len > 0 else 0
                erro = False
                if qtd == 0 or tiro_medio < 40:
                    erro = True
                resultado.append({'geometry': geom, '_ESTAGIO': estagio, '_VARIEDADE': variedade, 'BLOCO_ID': bloco_id, 'QTD_TALHOES': len(subset), 'QTD_LINHAS': qtd, 'TOTAL_COMP': round(total_len, 2), 'TIRO_MEDIO': round(tiro_medio, 2), 'MEDIA_POND': round(media_pond, 2), 'ERRO_BLOCO': erro})
                bloco_id += 1
        enviar_log('💾 Salvando...')
        final = gpd.GeoDataFrame(resultado, crs=talhoes.crs)
        final.to_file(entry_saida.get())
        excel = entry_saida.get().replace('.shp', '_AUDITORIA.xlsx')
        final.drop(columns='geometry').to_excel(excel, index=False)
        if debug_linhas:
            gpd.GeoDataFrame(debug_linhas, crs=talhoes.crs).to_file(entry_saida.get().replace('.shp', '_DEBUG.shp'))
        enviar_progresso(100)
        enviar_log(f'🏁 Finalizado em {round(time.time() - t0, 2)}s')
        enviar_fim()
    except Exception as e:
        enviar_log('❌ ERRO:')
        enviar_log(str(e))
        enviar_log(traceback.format_exc())
def executar():
    global cancelar
    cancelar = False
    threading.Thread(target=processar, daemon=True).start()
def selecionar_arquivo(entry):
    path = filedialog.askopenfilename()
    entry.delete(0, tk.END)
    entry.insert(0, path)
def selecionar_saida():
    path = filedialog.asksaveasfilename(defaultextension='.shp')
    entry_saida.delete(0, tk.END)
    entry_saida.insert(0, path)
def atualizar_ui():
    while not fila.empty():
        tipo, val = fila.get()
        if tipo == 'log':
            log_box.insert(tk.END, val + '\n')
            log_box.see(tk.END)
        else:
            if tipo == 'progress':
                progress['value'] = val
            else:
                if tipo == 'fim':
                    messagebox.showinfo('Sucesso', 'Processo finalizado')
    root.after(100, atualizar_ui)
root = tk.Tk()
root.title('GeoBloc')
root.geometry('900x650')
root.configure(bg='#f0f0f0')
tk.Label(root, text='GeoBloc', font=('Segoe UI', 24, 'bold'), bg='#f0f0f0').pack()
tk.Label(root, text='Blocagem Inteligente', font=('Segoe UI', 10), fg='gray', bg='#f0f0f0').pack()
frame_inputs = tk.LabelFrame(root, text='Entradas', bg='#f0f0f0')
frame_inputs.pack(fill='x', padx=20, pady=10)
def linha(frame, text, row, is_saida=False):
    # ***<module>.linha: Failure: Compilation Error
    tk.Label(frame, text=text, bg='#f0f0f0').grid(row=row, column=0, padx=10, pady=5, sticky='w')
    e = tk.Entry(frame, width=70)
    e.grid(row=row, column=1)
    if is_saida:
        tk.Button(frame, text='...', command=selecionar_saida).grid(row=row, column=2)
        return e
    else:
        tk.Button(frame, text='...', command=lambda *, **e: selecionar_arquivo(e)).grid(row=row, column=2)
        return e
entry_talhoes = linha(frame_inputs, 'Talhões', 0)
entry_linhas = linha(frame_inputs, 'Linhas', 1)
entry_redes = linha(frame_inputs, 'Redes', 2)
entry_saida = linha(frame_inputs, 'Saída', 3, True)
frame_config = tk.LabelFrame(root, text='Configurações', bg='#f0f0f0')
frame_config.pack(pady=10)
tk.Label(frame_config, text='Modo de Agrupamento', bg='#f0f0f0').grid(row=0, column=0, padx=10)
combo_agrupar = ttk.Combobox(frame_config, values=['ESTAGIO', 'VARIEDADE', 'ESTAGIO + VARIEDADE', 'SEM CRITERIO'], state='readonly')
combo_agrupar.current(2)
combo_agrupar.grid(row=0, column=1, padx=10)
tk.Button(root, text='GERAR BLOCOS', command=executar, bg='#1f8bb4', fg='white', width=25, height=2).pack(pady=10)
progress = ttk.Progressbar(root, length=700)
progress.pack(pady=10)
frame_log = tk.LabelFrame(root, text='Log de Execução', bg='#f0f0f0')
frame_log.pack(fill='both', expand=True, padx=20, pady=10)
log_box = tk.Text(frame_log)
log_box.pack(fill='both', expand=True)
atualizar_ui()
if __name__ == '__main__':
    root.mainloop()
