# FIELD MAPPING APPENDIX

Version 0.1
Status: Engineering Draft

This appendix complements the Liquid Lens Specification.

It defines the intended responsibilities of each Lacuna field variable.

It deliberately avoids prescribing mathematical implementations.

The renderer remains free to evolve provided these responsibilities are preserved.

---------------------------------------------------------------------

# Rendering Pipeline

Acquisition

↓

Lacuna Engine

↓

Field Variables

↓

Material Response

↓

Optical Response

↓

Rendered Image

Only the Field Variables are visible to the renderer.

---------------------------------------------------------------------

# q

Meaning

Large-scale displacement from equilibrium.

Primary Responsibilities

- overall deformation
- large folds
- broad surface curvature
- equilibrium position

Secondary Responsibilities

- optical depth bias
- cavity compression
- centre-of-mass displacement

Must Never Control

- colour
- brightness
- flashing
- transparency

---------------------------------------------------------------------

# p

Meaning

Momentum of the field.

Primary Responsibilities

- flow direction
- ribbon orientation
- transport
- rotational behaviour

Secondary Responsibilities

- curvature
- trailing structures
- inertial lag

Must Never Control

- colour
- optical intensity
- glow

---------------------------------------------------------------------

# activity

Meaning

Instantaneous disturbance energy.

Primary Responsibilities

- ripple amplitude
- fold strength
- disturbance radius

Secondary Responsibilities

- droplet formation threshold
- standing-wave energy

Must Never Control

- emotional appearance
- colour coding
- warnings

---------------------------------------------------------------------

# tempo

Meaning

Temporal rhythm.

Primary Responsibilities

- standing-wave spacing
- ripple frequency
- oscillation period

Secondary Responsibilities

- fine surface texture

Must Never Control

- movement speed directly
- brightness

---------------------------------------------------------------------

# irregularity

Meaning

Departure from regular rhythm.

Primary Responsibilities

- asymmetry
- non-uniform wave spacing
- ribbon branching

Secondary Responsibilities

- temporary droplet separation

Must Never Produce

- noise
- chaos
- spikes
- cellular breakup

---------------------------------------------------------------------

# idle

Meaning

Distance toward equilibrium.

Primary Responsibilities

- damping
- smoothing
- recombination
- return to rest

Secondary Responsibilities

- optical clarity
- surface relaxation

Must Never

- instantly freeze motion
- produce abrupt transitions

---------------------------------------------------------------------

# Optical Layer

The optical layer exists independently of motion.

Permanent properties include:

- refraction
- optical depth
- subtle internal reflection
- anti-reflective edge colour
- shadowing
- layered glass

These properties should remain visible even when the field is perfectly still.

---------------------------------------------------------------------

# Behaviour Matrix

IDLE

Material

- smooth
- quiet
- cohesive

Optics

- deep
- transparent
- faintly alive

------------------------------------------------

LOW ACTIVITY

Material

- standing waves
- gentle folds

Optics

- soft refraction changes

------------------------------------------------

SUSTAINED ACTIVITY

Material

- flowing ribbons
- directional transport

Optics

- stronger internal gradients

------------------------------------------------

FRAGMENTED ACTIVITY

Material

- rounded droplets
- orbital separation
- gradual recombination

Optics

- multiple interacting distortions

------------------------------------------------

RECOVERY

Material

- wave decay
- droplet merging
- smoothing

Optics

- return toward optical stillness

---------------------------------------------------------------------

# Forbidden Responses

The renderer must never produce:

- literal ferrofluid spikes
- clustered magnetic hedgehogs
- trypophobia-triggering structures
- exploding particles
- lightning
- flames
- smoke
- neon glow
- HUD graphics
- game visual effects

---------------------------------------------------------------------

# Rendering Priority

When implementation decisions conflict:

1. Physical believability
2. Calmness
3. Continuity
4. Truthfulness
5. Visual beauty

Beauty must never override the first four principles.

---------------------------------------------------------------------

# Future Extension

Additional field variables may be introduced.

Each new variable should answer three questions:

1. What physical property does it represent?

2. Which material behaviour should it influence?

3. What must it never control?

This preserves continuity across future versions of the Liquid Lens.

