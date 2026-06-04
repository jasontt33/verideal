"""Tests for backend/app/entities.py — entity name resolution and matching."""
from app.entities import (
    normalize,
    resolve_entity,
    entities_match,
    find_entity_in_invoice,
)


def test_normalize_lowercases_and_strips_punct():
    assert normalize("Stand Together, Inc.") == "stand together"
    assert normalize("Charles Koch  Foundation") == "charles koch foundation"
    assert normalize("STC4") == "stc4"


def test_resolve_entity_brand_to_parent():
    assert resolve_entity("ckf events") == "charles koch foundation"
    assert resolve_entity("cva action") == "americans for prosperity action"


def test_resolve_entity_alias_to_canonical():
    assert resolve_entity("afp") == "americans for prosperity"
    assert resolve_entity("stt") == "stand together trust"


def test_resolve_entity_passthrough_for_unknown():
    assert resolve_entity("acme widgets") == "acme widgets"


def test_entities_match_brand_and_parent():
    assert entities_match("Charles Koch Foundation", "CKF Events")


def test_entities_match_alias():
    assert entities_match("Stand Together, Inc.", "Stand Together Chamber of Commerce")
    assert entities_match("Americans for Prosperity", "AFP")


def test_entities_match_case_and_punct_insensitive():
    assert entities_match("STAND TOGETHER, INC.", "stand together inc")


def test_entities_match_distinct_returns_false():
    assert not entities_match("Stand Together Foundation", "Stand Together Trust")
    assert not entities_match("Americans for Prosperity", "Americans for Prosperity Action")


def test_find_entity_in_invoice_longest_match_wins():
    text = "Bill to:\nStand Together Chamber of Commerce\n1310 N Courthouse"
    name, canonical = find_entity_in_invoice(text)
    assert canonical == "stand together, inc."


def test_find_entity_in_invoice_short_name_word_boundary():
    name, _ = find_entity_in_invoice("Cvalue Corp")
    assert name is None
    name, _ = find_entity_in_invoice("Bill to: CVA action")
    assert name is not None


def test_find_entity_in_invoice_no_match():
    name, canonical = find_entity_in_invoice("Random Vendor LLC, Hollywood CA")
    assert name is None
    assert canonical is None
