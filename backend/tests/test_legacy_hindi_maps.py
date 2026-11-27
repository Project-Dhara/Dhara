"""Unit tests for Kruti Dev 010 and Softkey Chanakya → Unicode maps."""
from __future__ import annotations

from app.services.ingestion.legacy_hindi_maps import chanakya_to_unicode, krutidev_to_unicode


def test_krutidev_known_phrases():
    assert krutidev_to_unicode("dkj[kkuksa dh la[;k") == "कारखानों की संख्या"
    assert "कार्यरत" in krutidev_to_unicode("dk;Zjr")


def test_krutidev_passthrough_empty():
    assert krutidev_to_unicode("") == ""


def test_chanakya_known_phrases():
    assert chanakya_to_unicode("ÖæÚUÌ") == "भारत"
    assert chanakya_to_unicode("ßæãUÙ ·¤æ Ùæ×") == "वाहन का नाम"
    assert chanakya_to_unicode("ç·¤âè") == "किसी"
    assert "दिल्ली" in chanakya_to_unicode("çÎËÜè")


def test_chanakya_empty():
    assert chanakya_to_unicode("") == ""
