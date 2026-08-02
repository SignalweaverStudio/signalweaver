# LACUNA HISTORY

## Origin

Lacuna began as an attempt to translate the reliable focus experience of driving a classic car on quiet B-roads into a laptop environment.

The original idea was to capture interaction micro-timing and express it through a continuous visual instrument rather than a productivity score.

## Early Engine

The first engine used:

- activity
- irregularity
- tempo
- idle
- q
- p
- s

It ran at a nominal 120 Hz and logged privacy-preserving timing-derived values.

No key identities, mouse coordinates, application names, or typed content were recorded.

## Diagnostics Phase

Large all-day recordings were collected.

Diagnostics established:

- stable sampling
- no NaNs or infinities
- long-session boundedness
- repeatable resting behaviour
- scheduler late-tick / catch-up structure

## Timing Discovery

Observatory v2 revealed that the historical runtime was integrating engine time at approximately twice wall-clock time.

The issue was traced to the timestep expression using the scheduled tick reference instead of the previous actual engine-step time.

The first fix corrected the reference point.

A second fix removed the lower timestep clamp, which had continued to inflate catch-up frames.

The final B2 timing validation produced an engine/wall ratio of approximately 0.996.

## Revalidation

After the B2 fix:

- the resting attractor remained near 0.1062
- p damping remained stable
- q settled slowly and smoothly
- the historical p-to-q lag of about 0.33 seconds was superseded by evidence near 1.50 seconds
- active phase geometry changed from approximately 1.83:1 to approximately 1.28:1

## Visual Identity

The early live renderer used a phase-space dot.

This was recognised as a development instrument rather than the final product.

Visual exploration moved through:

- elastic membrane
- ferrofluid
- magnetic skin
- liquid lens
- optical instruments
- concave sapphire well

The leading physical identity became the Concave Well:

- gunmetal body
- naval brass tension ring
- concave sapphire
- dark optical cavity
- smooth reactive fluid
- no spikes
- no cellular textures

## Current Stage

Lacuna is now collecting canonical Epoch B2 recordings while developing the first screen-overlay embodiment of the Liquid Lens design language.
