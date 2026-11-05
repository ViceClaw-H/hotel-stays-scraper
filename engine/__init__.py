"""Hotel Rate Intelligence Engine Package."""
# Lightweight package initialization: allows standalone utility modules (country_taxes,
# provenance_gate, rate_writer, verify_evidence_integrity) to be imported in zero-dependency environments.

def __getattr__(name: str):
    if name in ("recalculate_room_baseline", "recalculate_all_baselines", "analyze_rates"):
        from .calculator import recalculate_room_baseline, recalculate_all_baselines, analyze_rates
        globals()[name] = locals()[name]
        return locals()[name]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")

__all__ = ["recalculate_room_baseline", "recalculate_all_baselines", "analyze_rates"]

