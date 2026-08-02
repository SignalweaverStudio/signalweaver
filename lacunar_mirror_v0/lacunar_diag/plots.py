import math
import matplotlib.pyplot as plt
import pandas as pd
from .config import CHUNK_SIZE, PLOT_COLUMNS, PLOT_MAX_POINTS

def collect_plot_sample(csv_path,row_count:int)->pd.DataFrame:
    stride=max(1,math.ceil(row_count/PLOT_MAX_POINTS)); parts=[]; offset=0; usecols=['elapsed_s',*PLOT_COLUMNS]
    for chunk in pd.read_csv(csv_path,usecols=usecols,chunksize=CHUNK_SIZE):
        positions=range((-offset)%stride,len(chunk),stride)
        selected=chunk.iloc[list(positions)]
        if not selected.empty: parts.append(selected)
        offset += len(chunk)
    if not parts: raise ValueError('Unable to collect plotting sample.')
    return pd.concat(parts,ignore_index=True).apply(pd.to_numeric,errors='coerce')

def save_time_series_plots(sample,output_directory):
    paths=[]; hours=sample['elapsed_s']/3600.0
    for column in PLOT_COLUMNS:
        fig,ax=plt.subplots(figsize=(12,4.5)); ax.plot(hours,sample[column],linewidth=0.7); ax.set_title(f'{column} over time'); ax.set_xlabel('Elapsed time (hours)'); ax.set_ylabel(column); ax.grid(True,alpha=0.25); fig.tight_layout(); path=output_directory/f'{column}_over_time.png'; fig.savefig(path,dpi=160); plt.close(fig); paths.append(path)
    return paths

def save_phase_portrait(sample,output_directory):
    fig,ax=plt.subplots(figsize=(7,7)); ax.plot(sample['q'],sample['p'],linewidth=0.45,alpha=0.7); ax.set_title('q-p phase portrait'); ax.set_xlabel('q'); ax.set_ylabel('p'); ax.grid(True,alpha=0.25); fig.tight_layout(); path=output_directory/'q_p_phase_portrait.png'; fig.savefig(path,dpi=180); plt.close(fig); return path
