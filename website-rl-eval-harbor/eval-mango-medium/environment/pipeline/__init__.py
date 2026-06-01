"""Pipeline package for the RL website-replication recipe.

Public surface so far:

    from pipeline.render import capture_page, capture_site, CaptureResult
    from pipeline.generate import sample_spec, generate_site, SiteSpec

These names are also re-exported at package level (``from pipeline import
capture_page``), but **lazily**: the convenience import does not load the heavy
submodules until the name is actually accessed. This matters because ``render``
pulls in Playwright and ``generate`` pulls in litellm — neither of which the
grader/metrics need. Importing ``pipeline.metrics.*`` must stay dependency-light,
so the package init must not eagerly import those submodules (PEP 562).
"""

# name -> submodule that defines it
_LAZY = {
    "CaptureResult": "pipeline.render",
    "capture_page": "pipeline.render",
    "capture_site": "pipeline.render",
    "SiteSpec": "pipeline.generate",
    "generate_site": "pipeline.generate",
    "sample_spec": "pipeline.generate",
}

__all__ = sorted(_LAZY)


def __getattr__(name: str):
    """Import the owning submodule on first access (PEP 562)."""
    module_name = _LAZY.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    import importlib

    value = getattr(importlib.import_module(module_name), name)
    globals()[name] = value  # cache so subsequent lookups skip __getattr__
    return value


def __dir__():
    return sorted(set(globals()) | set(_LAZY))
