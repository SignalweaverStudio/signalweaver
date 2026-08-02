# Lacunar Mirror v0 — Dynamics Bench Rig

This is the first testable implementation of the Lacunar Mirror's dynamics layer.

It does **not** diagnose focus, ADHD, distraction, productivity, emotion, or intent.

It receives only abstract interaction signals and evolves three continuous internal values:

- `q`: displacement
- `p`: momentum
- `s`: slow compliance

The engine is separate from any future toroid, particle field, overlay, or visual renderer.

## First run: synthetic test

Python 3.10 or newer is recommended.

```bash
pip install matplotlib
python lacunar_mirror_v0.py --mode synthetic --plot
```

The synthetic session runs for 70 seconds:

1. idle
2. steady interaction
3. fragmented bursts
4. quiet thought / near-idle
5. faster steady interaction
6. full idle and settling

A CSV file is written to the working directory.

## Live timing mode

```bash
pip install pynput matplotlib
python lacunar_mirror_v0.py --mode live --plot
```

Stop with `Ctrl+C`.

Live mode records no keys, text, mouse coordinates, applications, windows, URLs, or clipboard data. Raw event timestamps remain temporarily in memory. The CSV contains only normalised telemetry and dynamics state.

## What to inspect

The first questions are deliberately simple:

- Does `p` provide believable residual motion?
- Does `q` remain bounded?
- Does the system settle naturally during idle?
- Does `s` move slowly enough to feel like memory rather than an alert?
- Does fragmented input alter texture without producing punishment or runaway?
- Does the engine feel dead, nervous, heavy, or responsive?

Do not tune for beauty yet. Tune for truthful dynamics.

## Useful commands

Run without plotting:

```bash
python lacunar_mirror_v0.py --mode synthetic
```

Use a lower update rate:

```bash
python lacunar_mirror_v0.py --mode synthetic --plot --hz 60
```

Write the log somewhere explicit:

```bash
python lacunar_mirror_v0.py --mode live --plot --log ~/focustracker/lacunar_v0.csv
```

## Current design status

The three-state model is a starting hypothesis, not permanent doctrine. The invariants are:

- no user classification
- continuous internal evolution
- deterministic and bounded behaviour
- natural settling
- renderer independence
- no semantic capture
