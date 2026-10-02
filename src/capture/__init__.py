"""Capture — Momento de Captura v0.

Contrato
--------
- Emite ``CaptureEvent`` inmutables cuando MC_usd ∈ [MC_lo, MC_hi], complete=false,
  tradeable ≥ N segundos, ≥1 trade en ventana (ver cycle0/definicion-captura-v0.md).
- Prohibido leer candles/trades con ts > candidato a T0.
- Math de MC/precio solo vía ``capture.math`` (DRY / V5).

Verification hooks
------------------
- ``verify_capture_schema`` (V1)
- ``verify_no_future_reads`` (V1)
- ``verify_idempotent_capture_id`` (V1)
- golden fixtures en tests/fixtures/captures/ (V6)
"""
