# LACUNA RESEARCH PROTOCOL

Version 0.1  
Status: Active

## Purpose

The research protocol exists to preserve context around recordings without turning Lacuna into a surveillance or classification system.

## Canonical Recording

Canonical long-session recordings use filenames such as:

experiment_009_all_day.csv

## Session Notes

Each recording may have a timestamped notes file:

experiment_009_notes.csv

The notes file records:

- recording start
- engine epoch
- user-authored notes
- recording stop

## Start Utility

Canonical sessions may be started with:

python .\lacunar_day_start.py 009

This creates the notes file, records the session metadata, and launches the recorder.

## Add Note Utility

Notes may be added from another PowerShell window with:

python .\lacunar_note.py "Working on Lacuna"

Examples:

python .\lacunar_note.py "Away — coffee"
python .\lacunar_note.py "Returned"
python .\lacunar_note.py "Watching YouTube"
python .\lacunar_note.py "Working on Liquid Lens concepts"

## Interpretation Rule

Notes are not machine-learning labels by default.

They are human annotations for later investigation.

Lacuna must not silently infer meaning beyond what the user wrote.

## Research Order

1. Validate recording integrity.
2. Validate timing integrity.
3. Identify episodes or transitions.
4. Compare episodes with user notes.
5. Form hypotheses.
6. Test hypotheses on later recordings.
7. Avoid retrospective storytelling.

## Current Research Question

Can Lacuna reveal structure in a working day that is not reducible to a simple activity graph?

## Current Baseline

Epoch B2 is the current validated baseline.
