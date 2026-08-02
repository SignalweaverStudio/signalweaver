from pathlib import Path

def format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f'{hours}h {minutes:02d}m {secs:05.2f}s'

def make_output_directory(csv_path: Path) -> Path:
    output_directory = csv_path.parent / 'diagnostic_outputs' / csv_path.stem
    output_directory.mkdir(parents=True, exist_ok=True)
    return output_directory
