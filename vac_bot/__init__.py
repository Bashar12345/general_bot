from importlib import import_module

__all__ = ["ask", "rebuild_chain", "rebuild_vectordb"]


def __getattr__(name):
    if name in {"ask", "rebuild_chain"}:
        module = import_module(".chain", __name__)
        return getattr(module, name)
    if name == "rebuild_vectordb":
        module = import_module(".loader", __name__)
        return getattr(module, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
