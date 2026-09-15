# Fly Casino v2

A persistent 2D reinforcement-learning simulation inspired by the Drosophila mushroom body. The fly autonomously moves through a small world, manages internal needs, explores, visits casinos, learns machine values from reward-prediction error, and adapts when probabilities drift.

## v2 features
- Persistent 2D world and autonomous navigation
- Hunger, thirst, energy, fatigue, stress, curiosity, and mood
- Goal selection using learned values plus homeostatic drives
- Three casino locations with independent learned Q-values
- Dopamine-like reward prediction error and KC/MBON/DAN telemetry
- Dynamic payout-probability drift to force re-learning
- Persistent bankroll, visits, events, and wagering history
- Live canvas map, brain visualization, bankroll chart, and controls
- Automatic migration from the original v1 state format

This is a computational model and simulation, not a claim to emulate a complete biological fly brain. FlyBucks are simulated and have no real-world value.

## Run
```bash
python3 app.py
```
The service listens on port 8080.
