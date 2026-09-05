# NEO Signal Terminal Mobile — Stage 10

Production-integration Flutter light-theme personal trading terminal.

Included:
- Home live broker status, indices and MTM
- Signals and lifecycle detail
- Option scanner with richer candidate table and selected live premium
- Guarded swipe -> one-time confirmation -> broker submission
- Positions, exit intents, SL/T1/T2 plans
- Risk gate, execution arm and kill switch
- Orders / holdings / limits / journal viewer
- Core-instrument sync and manual restart recovery
- Android Gradle project, manifest, light launch theme and adaptive icon placeholder

Important: Android cleartext HTTP is enabled for LAN/emulator development. For production deployment, use HTTPS/WSS and disable cleartext traffic. Release signing is still configured to debug signing as a safe placeholder; configure your own keystore before distribution.
