"""MetaTrader 5 integration package (Phase 4–5: connect / symbols / pricing)."""

__all__ = [
    "MT5Client",
    "MT5Error",
    "MT5Service",
    "MockMT5Gateway",
    "RealMT5Gateway",
]


def __getattr__(name: str):
    if name in {"MT5Client", "MT5Error"}:
        from app.mt5.client import MT5Client, MT5Error

        return {"MT5Client": MT5Client, "MT5Error": MT5Error}[name]
    if name == "MT5Service":
        from app.mt5.service import MT5Service

        return MT5Service
    if name in {"MockMT5Gateway", "RealMT5Gateway"}:
        from app.mt5.gateway import MockMT5Gateway, RealMT5Gateway

        return {"MockMT5Gateway": MockMT5Gateway, "RealMT5Gateway": RealMT5Gateway}[name]
    raise AttributeError(name)
