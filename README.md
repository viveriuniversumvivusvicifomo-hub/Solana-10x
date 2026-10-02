# solana-10x

Sistema cuantitativo (research → captura → features → labels → modelos) para detectar tokens **Pump.fun en bonding curve** en el rango de market cap **~$8k–$20k**, antes de la migración a PumpSwap.

**Usuario:** Sinck (Europe/Madrid).  
**Estado:** Cycle 0 — definición, fuentes y esqueleto. Sin conectores live ni lógica fingida.

## Documentación Cycle 0

Ver [`cycle0/RESUMEN.md`](cycle0/RESUMEN.md) y:

- [`cycle0/fuentes-datos.md`](cycle0/fuentes-datos.md)
- [`cycle0/definicion-captura-v0.md`](cycle0/definicion-captura-v0.md)
- [`cycle0/feature-set-mvp.md`](cycle0/feature-set-mvp.md)
- [`cycle0/protocolos-verificacion.md`](cycle0/protocolos-verificacion.md)
- [`cycle0/pipeline-esqueleto.md`](cycle0/pipeline-esqueleto.md)

## Layout

```
solana-10x/
  cycle0/           # entregables de diseño
  src/
    ingestion/      # raw creates, trades, curve, oracle
    capture/        # Momento de Captura v0
    features/       # vector ≤ T0
    labeling/       # outcomes > T0 (tabla separada)
    models/         # stubs
    backtest/       # stubs walk-forward
    verification/   # gates anti look-ahead
```

## Principios

1. On-chain BondingCurve es la verdad de precio/MC en curva.  
2. Ninguna feature usa datos posteriores a T0.  
3. Labels nunca se joinean al feature matrix de entrenamiento.  
4. Tests de verificación son gate de merge.

## Setup (stub)

```bash
cd solana-10x
python -m venv .venv && source .venv/bin/activate
pip install -e .
```

Claves API (Cycle 1+): `HELIUS_API_KEY`, `BITQUERY_TOKEN`, opcional `BIRDEYE_API_KEY`, `JUPITER_API_KEY`.
