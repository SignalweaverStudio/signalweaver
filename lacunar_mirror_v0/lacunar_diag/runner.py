from pathlib import Path
from .idle import analyse_idle_episodes
from .plots import collect_plot_sample, save_phase_portrait, save_time_series_plots
from .report import print_idle_summary, print_statistics, print_validation_report, save_summary_json
from .statistics import build_statistics, collect_percentile_sample
from .utils import make_output_directory
from .validate import first_pass

def run_diagnostics(csv_path:Path)->None:
    if not csv_path.exists(): raise FileNotFoundError(f'CSV file not found: {csv_path}')
    if not csv_path.is_file(): raise ValueError(f'Path is not a file: {csv_path}')
    file_size=csv_path.stat().st_size; output=make_output_directory(csv_path)
    print('\nPass 1 of 4: validating dataset and calculating exact statistics...'); exact=first_pass(csv_path)
    print('Pass 2 of 4: collecting percentile sample...'); sample=collect_percentile_sample(csv_path,exact['row_count']); statistics=build_statistics(exact,sample)
    print('Pass 3 of 4: detecting idle episodes...'); episodes,idle_summary=analyse_idle_episodes(csv_path)
    print('Pass 4 of 4: collecting plot sample and creating figures...'); plot_sample=collect_plot_sample(csv_path,exact['row_count']); plot_paths=save_time_series_plots(plot_sample,output); plot_paths.append(save_phase_portrait(plot_sample,output))
    statistics.to_csv(output/'statistics.csv',float_format='%.12g'); episodes.to_csv(output/'idle_episodes.csv',index=False)
    save_summary_json(output/'summary.json',csv_path,file_size,exact,statistics,idle_summary,plot_paths)
    print_validation_report(csv_path,file_size,exact,len(sample)); print_statistics(statistics); print_idle_summary(idle_summary)
    print('\n'+'='*60+'\nOUTPUT\n'+'='*60+f'\n\nOutput directory:\n{output.resolve()}\n\nCreated:\n  statistics.csv\n  idle_episodes.csv\n  summary.json')
    for p in plot_paths: print(f'  {p.name}')
    print()
