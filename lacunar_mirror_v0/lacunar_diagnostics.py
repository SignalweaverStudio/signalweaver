#!/usr/bin/env python3
from pathlib import Path
import argparse
from lacunar_diag.runner import run_diagnostics

def main():
    parser = argparse.ArgumentParser(description='Validate, summarise, and visualise a Lacunar Mirror experiment.')
    parser.add_argument('csv', type=Path, help='CSV experiment file to analyse')
    args = parser.parse_args()
    try:
        run_diagnostics(args.csv)
    except KeyboardInterrupt:
        print('\nDiagnostics cancelled.')
    except Exception as error:
        print('\nLacunar Diagnostics failed:')
        print(error)
        raise SystemExit(1)

if __name__ == '__main__':
    main()
