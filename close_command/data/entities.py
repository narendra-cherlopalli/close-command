"""
Entity registry for Helios Chemicals Group consolidation.
"""

ENTITY_REGISTRY = {
    "HCG": {
        "entity_code": "HCG",
        "entity_name": "Helios Chemicals Group",
        "entity_method": "GLOBAL",
        "currency": "GBP",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": None,
        "is_nci": False,
        "is_root": True,
        "description": "Ultimate parent holding company",
    },
    "HCG-UK": {
        "entity_code": "HCG-UK",
        "entity_name": "Helios UK Ltd",
        "entity_method": "GLOBAL",
        "currency": "GBP",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": "HCG",
        "is_nci": False,
        "is_root": False,
        "description": "UK operating subsidiary",
    },
    "HCG-DE": {
        "entity_code": "HCG-DE",
        "entity_name": "Helios Deutschland GmbH",
        "entity_method": "GLOBAL",
        "currency": "EUR",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": "HCG",
        "is_nci": False,
        "is_root": False,
        "description": "German operating subsidiary",
    },
    "HCG-US": {
        "entity_code": "HCG-US",
        "entity_name": "Helios Americas Inc",
        "entity_method": "GLOBAL",
        "currency": "USD",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": "HCG",
        "is_nci": False,
        "is_root": False,
        "description": "US Americas hub subsidiary",
    },
    "HCG-SG": {
        "entity_code": "HCG-SG",
        "entity_name": "Helios Asia Pte Ltd",
        "entity_method": "GLOBAL",
        "currency": "SGD",
        "pcon": 75.0,
        "pown": 75.0,
        "parent": "HCG",
        "is_nci": True,
        "is_root": False,
        "description": "Singapore Asia hub - NCI entity (75% owned)",
    },
    "HCG-FR": {
        "entity_code": "HCG-FR",
        "entity_name": "Helios France SAS",
        "entity_method": "GLOBAL",
        "currency": "EUR",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": "HCG-DE",
        "is_nci": False,
        "is_root": False,
        "description": "French subsidiary under Germany",
    },
    "HCG-NL": {
        "entity_code": "HCG-NL",
        "entity_name": "Helios Netherlands BV",
        "entity_method": "GLOBAL",
        "currency": "EUR",
        "pcon": 60.0,
        "pown": 60.0,
        "parent": "HCG-DE",
        "is_nci": True,
        "is_root": False,
        "description": "Netherlands subsidiary - NCI entity (60% owned)",
    },
    "HCG-AU": {
        "entity_code": "HCG-AU",
        "entity_name": "Helios Australia Pty Ltd",
        "entity_method": "GLOBAL",
        "currency": "AUD",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": "HCG-US",
        "is_nci": False,
        "is_root": False,
        "description": "Australian subsidiary under Americas hub",
    },
    "HCG-JP": {
        "entity_code": "HCG-JP",
        "entity_name": "Helios Japan KK",
        "entity_method": "EQUITY",
        "currency": "JPY",
        "pcon": 40.0,
        "pown": 40.0,
        "parent": "HCG",
        "is_nci": False,
        "is_root": False,
        "description": "Japan associate - equity method (40% owned)",
    },
    "SHARED": {
        "entity_code": "SHARED",
        "entity_name": "Shared Services Centre",
        "entity_method": "GLOBAL",
        "currency": "GBP",
        "pcon": 100.0,
        "pown": 100.0,
        "parent": "HCG",
        "is_nci": False,
        "is_root": False,
        "description": "Central shared services entity",
    },
}

VALID_ENTITY_CODES = set(ENTITY_REGISTRY.keys())


def get_entity(code: str) -> dict | None:
    """Return entity details dict or None if not found."""
    try:
        return ENTITY_REGISTRY.get(code)
    except Exception:
        return None


def get_parent(code: str) -> str | None:
    """Return parent entity code or None if root or not found."""
    try:
        entity = ENTITY_REGISTRY.get(code)
        if entity is None:
            return None
        return entity.get("parent")
    except Exception:
        return None


def get_children(code: str) -> list[str]:
    """Return list of direct child entity codes."""
    try:
        children = []
        for entity_code, entity_data in ENTITY_REGISTRY.items():
            if entity_data.get("parent") == code:
                children.append(entity_code)
        return children
    except Exception:
        return []


def is_nci_entity(code: str) -> bool:
    """Return True if entity has non-controlling interests."""
    try:
        entity = ENTITY_REGISTRY.get(code)
        if entity is None:
            return False
        return entity.get("is_nci", False)
    except Exception:
        return False


def get_pcon(code: str) -> float:
    """Return consolidation percentage for entity."""
    try:
        entity = ENTITY_REGISTRY.get(code)
        if entity is None:
            return 0.0
        return entity.get("pcon", 0.0)
    except Exception:
        return 0.0


def get_pown(code: str) -> float:
    """Return ownership percentage for entity."""
    try:
        entity = ENTITY_REGISTRY.get(code)
        if entity is None:
            return 0.0
        return entity.get("pown", 0.0)
    except Exception:
        return 0.0


def are_under_same_parent(code1: str, code2: str) -> bool:
    """Return True if both entities share the same direct parent."""
    try:
        parent1 = get_parent(code1)
        parent2 = get_parent(code2)
        if parent1 is None or parent2 is None:
            return False
        return parent1 == parent2
    except Exception:
        return False
