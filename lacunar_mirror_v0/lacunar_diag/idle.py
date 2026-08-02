import numpy as np
import pandas as pd
from .config import CHUNK_SIZE, IDLE_THRESHOLD, MIN_IDLE_EPISODE_SECONDS

def analyse_idle_episodes(csv_path):
    episodes=[]; start=None; previous=None
    for chunk in pd.read_csv(csv_path,usecols=['elapsed_s','idle'],chunksize=CHUNK_SIZE):
        elapsed=pd.to_numeric(chunk['elapsed_s'],errors='coerce').to_numpy()
        idle=pd.to_numeric(chunk['idle'],errors='coerce').to_numpy()
        for current,value in zip(elapsed,idle):
            if not np.isfinite(current) or not np.isfinite(value): continue
            active_idle=value >= IDLE_THRESHOLD
            if active_idle and start is None: start=float(current)
            elif not active_idle and start is not None:
                end=float(previous if previous is not None else current)
                duration=max(0.0,end-start)
                if duration >= MIN_IDLE_EPISODE_SECONDS: episodes.append({'start_s':start,'end_s':end,'duration_s':duration})
                start=None
            previous=float(current)
    if start is not None and previous is not None:
        duration=max(0.0,previous-start)
        if duration >= MIN_IDLE_EPISODE_SECONDS: episodes.append({'start_s':start,'end_s':previous,'duration_s':duration})
    frame=pd.DataFrame(episodes,columns=['start_s','end_s','duration_s'])
    if frame.empty:
        summary={'threshold':IDLE_THRESHOLD,'minimum_episode_seconds':MIN_IDLE_EPISODE_SECONDS,'episode_count':0,'total_idle_seconds':0.0,'median_duration_seconds':0.0,'p95_duration_seconds':0.0,'longest_duration_seconds':0.0}
    else:
        d=frame['duration_s']; summary={'threshold':IDLE_THRESHOLD,'minimum_episode_seconds':MIN_IDLE_EPISODE_SECONDS,'episode_count':int(len(frame)),'total_idle_seconds':float(d.sum()),'median_duration_seconds':float(d.median()),'p95_duration_seconds':float(d.quantile(0.95)),'longest_duration_seconds':float(d.max())}
    return frame, summary
