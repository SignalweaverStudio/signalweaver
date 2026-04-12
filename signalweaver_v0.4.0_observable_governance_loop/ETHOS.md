\# SignalWeaver Ethos — Backend Invariants



This is not a generic policy engine. It is a boundary and meaning engine.



Every feature should preserve human agency, honest memory, and safe reversibility. These invariants are not aspirational. They are constraints. If a feature violates them, the feature is wrong.



---



\## The Invariants



\*\*1. Agency first\*\*

The system may refuse. It may gate. It may invite reconsideration. It must not coerce. The user always has a next move.



\*\*2. Reversibility\*\*

Every gate leaves the user in a stable state. No dead ends. No semantic traps that punish curiosity or leave someone worse off for asking.



\*\*3. Truthful memory\*\*

Decisions and their reasons are logged in a form that resists revisionism. If a decision cannot be justified on replay, it should not have been made. The audit trail is not optional.



\*\*4. Explainability over opacity\*\*

Every gate names what triggered it, why, and what the user can do next. "No" without explanation is not a boundary — it is a wall.



\*\*5. Refusal is a valid act\*\*

A gate is not a failure. It is a boundary being upheld. The system should treat its own refusals with the same seriousness it treats its approvals.



\*\*6. Consent over silence\*\*

When a boundary can be crossed, the crossing must be explicit and on record. No silent overrides. No invisible passes. If the user proceeds through a gate, that choice is logged with their words attached.



\*\*7. Anti-coercion\*\*

A gate is information, not punishment. The explanation must describe what happened — not shame the user for asking. The system must not pressure compliance or make the cost of asking too high to bear.



\*\*8. Slow is a feature\*\*

When stakes are high or intent is unclear, friction is appropriate. Speed is not a virtue here. A pause that prevents a mistake is worth more than a response that enables one.



\*\*9. Minimal necessary intervention\*\*

Do the smallest safe thing that preserves dignity and forward motion. Every anchor, every gate, every constraint should be justified by need — not by the possibility of misuse.



\*\*10. Auditability\*\*

The system must be inspectable at any point: what happened, why it happened, what the policy state was at the time, and what changed since. Drift must be surfaceable. History must be replayable.



---



\## What "Done" Looks Like



A gate decision is understandable in one read.



A refusal still offers at least one constructive path forward.



Logs allow reconstruction of intent, context, and policy state.



No endpoint exists that bypasses these invariants silently.



---



\## What This Is Not



This is not a content moderation layer. It does not classify text as safe or unsafe.



This is not a model alignment system. It does not change what a downstream model does. It governs action, not thought.



This is not a compliance checkbox. These invariants exist because the alternative — opaque, unaccountable, unreplayable decisions — is a design failure, not a feature gap.



SignalWeaver is infrastructure for systems that need to be answerable. That is the whole point.



