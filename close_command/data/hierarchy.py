"""
Group hierarchy for Helios Chemicals Group.
Reflects parent-child relationships defined in entities.py.
"""

from __future__ import annotations
from data.entities import ENTITY_REGISTRY, get_parent, get_children


def _build_hierarchy() -> dict:
    """Build a nested tree dict from the flat ENTITY_REGISTRY."""
    def build_node(code: str) -> dict:
        children_codes = get_children(code)
        entity = ENTITY_REGISTRY[code]
        node = {
            "entity_code": code,
            "entity_name": entity["entity_name"],
            "entity_method": entity["entity_method"],
            "currency": entity["currency"],
            "pcon": entity["pcon"],
            "pown": entity["pown"],
            "is_nci": entity["is_nci"],
            "children": {child: build_node(child) for child in children_codes},
        }
        return node

    # Find root entities (no parent)
    roots = [
        code for code, data in ENTITY_REGISTRY.items()
        if data.get("parent") is None
    ]
    if len(roots) == 1:
        return build_node(roots[0])
    # Multiple roots — wrap in synthetic node
    return {
        "entity_code": "__ROOT__",
        "entity_name": "Consolidated Group Root",
        "children": {root: build_node(root) for root in roots},
    }


GROUP_HIERARCHY: dict = _build_hierarchy()


def get_consolidation_path(entity_code: str) -> list[str]:
    """Return the path from the given entity up to the root (inclusive of both ends).

    Example: get_consolidation_path('HCG-FR') -> ['HCG-FR', 'HCG-DE', 'HCG']
    """
    try:
        if entity_code not in ENTITY_REGISTRY:
            return []
        path = [entity_code]
        current = entity_code
        visited: set[str] = {current}
        while True:
            parent = get_parent(current)
            if parent is None:
                break
            if parent in visited:
                # Guard against circular references
                break
            path.append(parent)
            visited.add(parent)
            current = parent
        return path
    except Exception:
        return []


def is_under_entity(child_code: str, parent_code: str) -> bool:
    """Return True if child_code is a descendant (direct or indirect) of parent_code."""
    try:
        if child_code not in ENTITY_REGISTRY or parent_code not in ENTITY_REGISTRY:
            return False
        path = get_consolidation_path(child_code)
        # Path includes child itself, so skip index 0
        return parent_code in path[1:]
    except Exception:
        return False


def get_all_descendants(entity_code: str) -> list[str]:
    """Return all descendants (direct and indirect children) of the given entity."""
    try:
        if entity_code not in ENTITY_REGISTRY:
            return []
        result: list[str] = []
        queue = list(get_children(entity_code))
        visited: set[str] = set()
        while queue:
            current = queue.pop(0)
            if current in visited:
                continue
            visited.add(current)
            result.append(current)
            queue.extend(get_children(current))
        return result
    except Exception:
        return []


def is_direct_parent(parent_code: str, child_code: str) -> bool:
    """Return True if parent_code is the immediate parent of child_code."""
    try:
        return get_parent(child_code) == parent_code
    except Exception:
        return False


def get_sibling_entities(entity_code: str) -> list[str]:
    """Return all entities that share the same direct parent (excluding entity_code itself)."""
    try:
        if entity_code not in ENTITY_REGISTRY:
            return []
        parent = get_parent(entity_code)
        if parent is None:
            # Root entity — siblings are other root entities
            return [
                code for code, data in ENTITY_REGISTRY.items()
                if data.get("parent") is None and code != entity_code
            ]
        return [
            code for code in get_children(parent)
            if code != entity_code
        ]
    except Exception:
        return []
