# Fly Casino V4 — Colony Lab

V4 turns the original single-fly reinforcement-learning project into a persistent artificial-neuroscience colony. The production instance runs on Proxmox CT 103 behind Cloudflare Tunnel at `https://game.dpifiles.org`.

## V4 release features
- Persistent multi-fly shared world (2–40 organisms)
- Original V3 founding organism preserved in parallel
- Real FlyWire public v783 neuron identities for KC, MBON, PAM, PPL1, EPG, PFL3, DNa02, PN and visual populations
- 24-channel compound-eye simulation per fly
- Individual brains, homeostatic drives, memories, bankrolls and learned machine values
- Social transmission of learned preferences and location knowledge
- Sleep-driven memory consolidation
- Heritable traits, persistent mutations, offspring and lineage tracking
- Shared changing payout schedules/weather
- Reproducible headless population experiments up to 120 flies × 12,000 steps
- Connectome coverage inspector with actual FlyWire root IDs, cell types and predicted neurotransmitters
- V3 clone/intervention/replay APIs retained for compatibility

## Scientific scope
FlyWire v783 identities and annotations are real public connectome data. V4's neural activity equations, functional couplings, sensory model, social behavior and learning rules are computational approximations; this is not a biophysical whole-brain emulator.

FlyWire public data is used under CC BY-NC 4.0. Source annotation table: `flyconnectome/flywire_annotations`, Supplemental File 1. The repository ships only a small generated subset used by the runtime, not the full annotation table.

## Production
- App: Gunicorn/Flask on port 8080
- State: `/var/lib/fly-casino/`
- V3 state: `/var/lib/fly-casino/state.json`
- V4 colony state: `/var/lib/fly-casino/colony-v4.json`
- Domain: `https://game.dpifiles.org`

## Deploy
Run `./deploy.sh` inside CT 103. The script backs up both V3 and V4 state before replacing application files and restarting the service.
