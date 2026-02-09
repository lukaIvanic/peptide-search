"""Compatibility shim for schema imports.

Schema models are organized under app.schemas_domain by domain:
search, runs, baseline, prompts, entities, shared.

Importing from app.schemas remains supported.
"""

from .schemas_domain.baseline import *
from .schemas_domain.entities import *
from .schemas_domain.prompts import *
from .schemas_domain.runs import *
from .schemas_domain.search import *
from .schemas_domain.shared import *

__all__ = [name for name in globals() if not name.startswith("_")]
