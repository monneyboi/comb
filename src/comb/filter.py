"""Pure filtering logic for Wikidata dump entities."""

from dataclasses import dataclass
from typing import Any

# The optional entity attributes comb knows about, in output order.
# id and type are always kept.
ATTRIBUTES = ("labels", "descriptions", "aliases", "claims", "sitelinks")


@dataclass(frozen=True)
class FilterConfig:
    """What to keep: entity types, attributes, and claim properties.

    ``properties`` is ``None`` when no property filter is given, meaning all
    claims pass through.
    """

    types: frozenset[str]
    attributes: frozenset[str]
    properties: frozenset[str] | None


def filter_entity(
    entity: dict[str, Any], config: FilterConfig
) -> dict[str, Any] | None:
    """Filter one parsed dump entity down to the configured selection.

    Returns the trimmed entity, or ``None`` when the entity is filtered out
    by type. Assumes ``id`` and ``type`` are present strings; the reader
    validates that before calling.
    """
    if entity["type"] not in config.types:
        return None

    kept: dict[str, Any] = {"id": entity["id"], "type": entity["type"]}
    for attribute in ATTRIBUTES:
        if attribute not in config.attributes:
            continue
        value = entity.get(attribute)
        if not value:
            continue
        if attribute == "claims" and config.properties is not None:
            value = {
                property_id: statements
                for property_id, statements in value.items()
                if property_id in config.properties
            }
            if not value:
                continue
        kept[attribute] = value
    return kept
