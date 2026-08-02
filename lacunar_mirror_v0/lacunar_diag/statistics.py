import numpy as np
import pandas as pd
from .config import CHUNK_SIZE, EXPECTED_COLUMNS, PERCENTILE_SAMPLE_SIZE, RANDOM_SEED

def collect_percentile_sample(csv_path, row_count: int) -> pd.DataFrame:
    probability = min(1.0, PERCENTILE_SAMPLE_SIZE / row_count)
    rng = np.random.default_rng(RANDOM_SEED)
    parts = []
    for chunk in pd.read_csv(csv_path, usecols=EXPECTED_COLUMNS, chunksize=CHUNK_SIZE):
        numeric = chunk.apply(pd.to_numeric, errors='coerce')
        selected = numeric if probability >= 1.0 else numeric.loc[rng.random(len(numeric)) < probability]
        if not selected.empty:
            parts.append(selected)
    if not parts:
        raise ValueError('Unable to collect a percentile sample.')
    sample = pd.concat(parts, ignore_index=True)
    if len(sample) > PERCENTILE_SAMPLE_SIZE:
        sample = sample.sample(n=PERCENTILE_SAMPLE_SIZE, random_state=RANDOM_SEED)
    return sample.replace([np.inf, -np.inf], np.nan)

def build_statistics(exact: dict, sample: pd.DataFrame) -> pd.DataFrame:
    q = sample.quantile([0.01,0.05,0.50,0.95,0.99], numeric_only=True)
    out = pd.DataFrame(index=EXPECTED_COLUMNS)
    out['count']=exact['finite_counts']; out['min']=exact['minimums']; out['p01_approx']=q.loc[0.01]; out['p05_approx']=q.loc[0.05]; out['median_approx']=q.loc[0.50]; out['mean']=exact['means']; out['std']=exact['standard_deviations']; out['p95_approx']=q.loc[0.95]; out['p99_approx']=q.loc[0.99]; out['max']=exact['maximums']; out['nan_count']=exact['nan_counts']; out['inf_count']=exact['inf_counts']
    out.index.name='variable'
    return out
