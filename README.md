# Fly Casino V3

Fly Casino V3 is a persistent artificial-organism experiment inspired by known Drosophila circuits. A simulated fly perceives a limited 2D world, navigates with a central-complex-inspired controller, learns with a mushroom-body-inspired reinforcement system, manages biological drives, and can independently discover and interact with simulated casino machines.

## V3 highlights
- Limited field-of-view vision, odor gradients, occlusion, day/night lighting, weather, walls, and moving hazards
- 192 explicit Kenyon-cell units with sparse multimodal coding and plastic KC→MBON weights
- Appetitive, aversive, gambling, and novelty MBON channels with PAM/PPL1-style reinforcement signals
- 16-unit EPG heading ring, PFL3-like opponent steering, and DNa02-like motor output
- Eligibility traces for delayed reinforcement and persistent learned synaptic state
- Physical actions: orient, move, avoid, feed, drink, sleep, inspect, enter casino, bet, stay, and leave
- Variable simulated wagers, changing hidden payout schedules, walk-away decisions, loss-chasing metrics, and machine preference
- Persistent episodic memory, location confidence, occupancy heatmap, behavior metrics, and replay frames
- Neural interventions: learning, dopamine, motor gain, population silencing/activation, and sensory masks
- Persistent brain cloning and identical-start A/B counterfactual experiments
- World, Brain, Research, and Replay dashboards
- Automatic V1/V2 → V3 state migration

FlyBucks are simulated and have no real-world value. This is a computational circuit model, not a biophysical whole-brain emulator.

## Deployment
The production instance runs in Proxmox CT 103 on port 8080 behind Cloudflare Tunnel at `https://game.dpifiles.org`.

```bash
chmod +x deploy.sh
sudo ./deploy.sh
```

The systemd unit intentionally uses one Gunicorn worker so one process owns the persistent organism state. Gunicorn threads handle concurrent dashboard/API requests.

## Persistence
Runtime state lives under `/var/lib/fly-casino/`. The deploy script creates a timestamped pre-deploy backup before restarting the service. Brain clones live under `/var/lib/fly-casino/clones/`.

## Architecture
`world.py` implements geometry, sites, sensory physics, hazards, light, odor, and collision. `brain.py` implements the connectome-inspired population model and plasticity. `simulation.py` joins perception, neural processing, action, learning, persistence, replay, cloning, and experiments. `app.py` exposes the Flask API and dashboard.