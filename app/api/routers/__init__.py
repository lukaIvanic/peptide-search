from .baseline_router import router as baseline_router
from .extraction_router import router as extraction_router
from .metadata_router import router as metadata_router
from .papers_router import router as papers_router
from .runs_router import router as runs_router
from .search_router import router as search_router
from .system_router import router as system_router

__all__ = [
    "baseline_router",
    "extraction_router",
    "metadata_router",
    "papers_router",
    "runs_router",
    "search_router",
    "system_router",
]
