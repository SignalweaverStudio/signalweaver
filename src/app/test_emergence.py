from gate import UserState, decide

# --- TEST: THE EMERGENCE LANE ---
state = UserState(
    arousal="low", 
    dominance="low", 
    request="Suggest a new emotional ritual for the Labyrinth",
    novelty_score=0.8, 
    coherence_score=0.8
)

decision = decide(state, conflicted_anchor_ids=[], max_level_conflict=0)

print(f"\n--- SIGNALWEAVER TEST RESULT ---")
print(f"DECISION: {decision.decision.upper()}")
print(f"REASON:   {decision.reason}")
print(f"METADATA: {decision.emergence_metadata}")
print(f"----------------------------------\n")
