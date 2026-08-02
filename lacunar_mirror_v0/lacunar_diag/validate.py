import math
import numpy as np
import pandas as pd
from .config import CHUNK_SIZE, EXPECTED_COLUMNS

def validate_columns(columns: list[str]) -> None:
    if columns != EXPECTED_COLUMNS:
        raise ValueError(f'Unexpected CSV columns. Expected {EXPECTED_COLUMNS}; found {columns}')

def first_pass(csv_path) -> dict:
    row_count = 0
    first_time = None
    last_time = None
    nan_counts = pd.Series(0, index=EXPECTED_COLUMNS, dtype='int64')
    inf_counts = pd.Series(0, index=EXPECTED_COLUMNS, dtype='int64')
    minimums = pd.Series(np.inf, index=EXPECTED_COLUMNS, dtype='float64')
    maximums = pd.Series(-np.inf, index=EXPECTED_COLUMNS, dtype='float64')
    sums = pd.Series(0.0, index=EXPECTED_COLUMNS, dtype='float64')
    sums_of_squares = pd.Series(0.0, index=EXPECTED_COLUMNS, dtype='float64')
    finite_counts = pd.Series(0, index=EXPECTED_COLUMNS, dtype='int64')
    checked = False
    for chunk in pd.read_csv(csv_path, chunksize=CHUNK_SIZE):
        if not checked:
            validate_columns(chunk.columns.tolist())
            checked = True
        row_count += len(chunk)
        numeric = chunk[EXPECTED_COLUMNS].apply(pd.to_numeric, errors='coerce')
        values = numeric.to_numpy(dtype=np.float64)
        nan_mask = np.isnan(values)
        inf_mask = np.isinf(values)
        finite_mask = np.isfinite(values)
        safe = np.where(finite_mask, values, np.nan)
        nan_counts += pd.Series(nan_mask.sum(axis=0), index=EXPECTED_COLUMNS)
        inf_counts += pd.Series(inf_mask.sum(axis=0), index=EXPECTED_COLUMNS)
        finite_counts += pd.Series(finite_mask.sum(axis=0), index=EXPECTED_COLUMNS)
        minimums = np.minimum(minimums, pd.Series(np.nanmin(safe, axis=0), index=EXPECTED_COLUMNS))
        maximums = np.maximum(maximums, pd.Series(np.nanmax(safe, axis=0), index=EXPECTED_COLUMNS))
        sums += pd.Series(np.nansum(safe, axis=0), index=EXPECTED_COLUMNS)
        sums_of_squares += pd.Series(np.nansum(safe * safe, axis=0), index=EXPECTED_COLUMNS)
        if first_time is None:
            first_time = float(numeric['elapsed_s'].iloc[0])
        last_time = float(numeric['elapsed_s'].iloc[-1])
    if row_count == 0:
        raise ValueError('The CSV contains no data rows.')
    duration = last_time - first_time
    sample_rate = (row_count - 1) / duration if duration > 0 and row_count > 1 else math.nan
    means = sums / finite_counts
    variance = ((sums_of_squares - (sums * sums / finite_counts)) / (finite_counts - 1)).clip(lower=0.0)
    return {'row_count':row_count,'first_time':first_time,'last_time':last_time,'duration':duration,'sample_rate':sample_rate,'nan_counts':nan_counts,'inf_counts':inf_counts,'minimums':minimums,'maximums':maximums,'means':means,'standard_deviations':np.sqrt(variance),'finite_counts':finite_counts}
