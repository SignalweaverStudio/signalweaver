import json
import pandas as pd
from .config import VERSION
from .utils import format_duration

def print_validation_report(csv_path,file_size,exact,sample_size):
    nans=int(exact['nan_counts'].sum()); infs=int(exact['inf_counts'].sum())
    print('\n'+'='*60+f'\nLACUNAR DIAGNOSTICS v{VERSION}\n'+'='*60+'\n')
    print(f'File:               {csv_path.name}\nSize:               {file_size:,} bytes\nRows:               {exact["row_count"]:,}\nDuration:           {format_duration(exact["duration"])}\nSample rate:        {exact["sample_rate"]:.2f} Hz\nNaNs:               {nans:,}\nInfinities:         {infs:,}\nPercentile sample:  {sample_size:,} rows\n')
    print('Dataset validation PASSED' if nans==0 and infs==0 else 'WARNING: Dataset contains numerical issues')

def print_statistics(statistics):
    cols=['min','p05_approx','median_approx','mean','std','p95_approx','max']
    print('\n'+'='*60+'\nDESCRIPTIVE STATISTICS\n'+'='*60+'\n\nPercentiles and medians are approximate.\n')
    with pd.option_context('display.max_rows',None,'display.max_columns',None,'display.width',180,'display.float_format',lambda v:f'{v:.6f}'):
        print(statistics[cols].to_string())

def print_idle_summary(s):
    print('\n'+'='*60+'\nIDLE EPISODES\n'+'='*60+'\n')
    print(f'Idle threshold:     {s["threshold"]:.2f}\nMinimum duration:   {s["minimum_episode_seconds"]:.2f} s\nEpisodes:           {s["episode_count"]:,}\nTotal idle time:    {format_duration(s["total_idle_seconds"])}\nMedian duration:    {s["median_duration_seconds"]:.2f} s\n95th percentile:    {s["p95_duration_seconds"]:.2f} s\nLongest episode:    {format_duration(s["longest_duration_seconds"])}')

def save_summary_json(output_path,csv_path,file_size,exact,statistics,idle_summary,plot_paths):
    variables={}
    for variable,row in statistics.iterrows():
        variables[variable]={key:(int(value) if key in {'count','nan_count','inf_count'} else float(value)) for key,value in row.items()}
    payload={'diagnostics_version':VERSION,'source_file':csv_path.name,'file_size_bytes':file_size,'rows':exact['row_count'],'duration_seconds':exact['duration'],'sample_rate_hz':exact['sample_rate'],'idle':idle_summary,'variables':variables,'plots':[p.name for p in plot_paths]}
    output_path.write_text(json.dumps(payload,indent=2),encoding='utf-8')
