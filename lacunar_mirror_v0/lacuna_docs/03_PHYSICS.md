# LACUNA PHYSICS

Version 0.1  
Status: Current technical baseline

## Engine Epochs

### Epoch A

Historical recordings:

- experiment_002_all_day.csv
- experiment_003_all_day.csv
- experiment_004_all_day.csv
- experiment_005_all_day.csv
- experiment_006_all_day.csv
- experiment_007_all_day.csv
- experiment_008_all_day.csv

Characteristics:

- historical timestep calculation bug
- engine over-integrated time
- approximate engine/wall ratios between 1.82 and 2.00
- lower timestep clamp present

Epoch A remains valid evidence for:

- acquisition telemetry
- scheduler behaviour
- privacy properties
- data integrity
- historical boundedness
- historical instrument behaviour

Epoch A q/p timing claims are superseded.

### Epoch B1

Recording:

- epoch_b_validation_01.csv

Characteristics:

- previous-frame timestep calculation fixed
- lower timestep clamp still present
- engine/wall ratio approximately 1.081

### Epoch B2

Recordings:

- epoch_b_validation_02.csv
- epoch_b_idle_settling_01.csv
- experiment_009_all_day.csv and later canonical recordings unless explicitly reassigned

Characteristics:

- timestep uses actual elapsed time from previous engine step
- lower timestep clamp removed
- upper safety cap retained
- validated engine/wall ratio approximately 0.996
- current timing baseline

## Revalidated B2 Findings

- numerical stability preserved
- resting attractor preserved at approximately q = 0.1062, p = 0
- p damps rapidly during inactivity
- q approaches equilibrium more slowly
- active q/p geometry re-established
- p leads q by approximately 1.50 seconds in current evidence
- active ellipse aspect approximately 1.28:1
- active q standard deviation approximately 0.368
- active p standard deviation approximately 0.288
- active radius p95 approximately 1.135

## Scheduler Behaviour

Windows scheduling produces a persistent late-tick / catch-up-tick pattern.

This appears as large populations of:

- intervals <= 4 ms
- intervals between 12 and 20 ms

The engine now integrates real elapsed time correctly, so this scheduler texture no longer produces the historical time-doubling defect.

## Current State Variables

Acquisition observables:

- activity
- irregularity
- tempo
- idle

Engine state:

- q
- p
- s

Derived values:

- energy
- stiffness
- damping
- force

The renderer should consume field state rather than raw hardware events.
