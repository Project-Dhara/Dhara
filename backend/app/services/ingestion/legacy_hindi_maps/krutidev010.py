"""Kruti Dev 010 → Unicode Devanagari.

Substitution table and matra/reph reordering adapted from LTRC kru2uni
(https://github.com/ltrc/kru2uni), which implements the standard Kruti Dev 010
glyph map used across Indian government documents.
"""
from __future__ import annotations

import re

# Ordered replacements (multi-char first). Source: LTRC kru2uni k2u table.
_K2U: list[tuple[str, str]] = [
    ("\xf1", "\u0970"),
    ("Q+Z", "QZ+"),
    ("sas", "sa"),
    ("aa", "a"),
    (")Z", "\u0930\u094d\u0926\u094d\u0927"),
    ("ZZ", "Z"),
    ("\u2018", '"'),
    ("\u2019", '"'),
    ("\u201c", "'"),
    ("\u201d", "'"),
    ("\xe5", "\u0966"),
    ("\u0192", "\u0967"),
    ("\u201e", "\u0968"),
    ("\u2026", "\u0969"),
    ("\u2020", "\u096a"),
    ("\u2021", "\u096b"),
    ("\u02c6", "\u096c"),
    ("\u2030", "\u096d"),
    ("\u0160", "\u096e"),
    ("\u2039", "\u096f"),
    ("\xb6+", "\u095e\u094d"),
    ("d+", "\u0958"),
    ("[+k", "\u0959"),
    ("[+", "\u0959\u094d"),
    ("x+", "\u095a"),
    ("T+", "\u091c\u093c\u094d"),
    ("t+", "\u095b"),
    ("M+", "\u095c"),
    ("<+", "\u095d"),
    ("Q+", "\u095e"),
    (";+", "\u095f"),
    ("j+", "\u0931"),
    ("u+", "\u0929"),
    ("\xd9k", "\u0924\u094d\u0924"),
    ("\xd9", "\u0924\u094d\u0924\u094d"),
    ("\xe4", "\u0915\u094d\u0924"),
    ("\u2013", "\u0926\u0943"),
    ("\u2014", "\u0915\u0943"),
    ("\xe9", "\u0928\u094d\u0928"),
    ("\u2122", "\u0928\u094d\u0928\u094d"),
    ("=kk", "=k"),
    ("f=k", "f="),
    ("\xe0", "\u0939\u094d\u0928"),
    ("\xe1", "\u0939\u094d\u092f"),
    ("\xe2", "\u0939\u0943"),
    ("\xe3", "\u0939\u094d\u092e"),
    ("\xbaz", "\u0939\u094d\u0930"),
    ("\xba", "\u0939\u094d"),
    ("\xed", "\u0926\u094d\u0926"),
    ("{k", "\u0915\u094d\u0937"),
    ("{", "\u0915\u094d\u0937\u094d"),
    ("=", "\u0924\u094d\u0930"),
    ("\xab", "\u0924\u094d\u0930\u094d"),
    ("N\xee", "\u091b\u094d\u092f"),
    ("V\xee", "\u091f\u094d\u092f"),
    ("B\xee", "\u0920\u094d\u092f"),
    ("M\xee", "\u0921\u094d\u092f"),
    ("<\xee", "\u0922\u094d\u092f"),
    ("|", "\u0926\u094d\u092f"),
    ("K", "\u091c\u094d\u091e"),
    ("}", "\u0926\u094d\u0935"),
    ("J", "\u0936\u094d\u0930"),
    ("V\xaa", "\u091f\u094d\u0930"),
    ("M\xaa", "\u0921\u094d\u0930"),
    ("<\xaa\xaa", "\u0922\u094d\u0930"),
    ("N\xaa", "\u091b\u094d\u0930"),
    ("\xd8", "\u0915\u094d\u0930"),
    ("\xdd", "\u092b\u094d\u0930"),
    ("nzZ", "\u0930\u094d\u0926\u094d\u0930"),
    ("\xe6", "\u0926\u094d\u0930"),
    ("\xe7", "\u092a\u094d\u0930"),
    ("\xc1", "\u092a\u094d\u0930"),
    ("xz", "\u0917\u094d\u0930"),
    ("#", "\u0930\u0941"),
    (":", "\u0930\u0942"),
    ("v\u201a", "\u0911"),
    ("vks", "\u0913"),
    ("vkS", "\u0914"),
    ("vk", "\u0906"),
    ("v", "\u0905"),
    ("b\xb1", "\u0908\u0902"),
    ("\xc3", "\u0908"),
    ("bZ", "\u0908"),
    ("b", "\u0907"),
    ("m", "\u0909"),
    ("\xc5", "\u090a"),
    (",s", "\u0910"),
    (",", "\u090f"),
    ("_", "\u090b"),
    ("\xf4", "\u0915\u094d\u0915"),
    ("d", "\u0915"),
    ("Dk", "\u0915"),
    ("D", "\u0915\u094d"),
    ("[k", "\u0916"),
    ("[", "\u0916\u094d"),
    ("x", "\u0917"),
    ("Xk", "\u0917"),
    ("X", "\u0917\u094d"),
    ("\xc4", "\u0918"),
    ("?k", "\u0918"),
    ("?", "\u0918\u094d"),
    ("\xb3", "\u0919"),
    ("pkS", "\u091a\u0948"),
    ("p", "\u091a"),
    ("Pk", "\u091a"),
    ("P", "\u091a\u094d"),
    ("N", "\u091b"),
    ("t", "\u091c"),
    ("Tk", "\u091c"),
    ("T", "\u091c\u094d"),
    (">", "\u091d"),
    ("\xf7", "\u091d\u094d"),
    ("\xa5", "\u091e"),
    ("\xea", "\u091f\u094d\u091f"),
    ("\xeb", "\u091f\u094d\u0920"),
    ("V", "\u091f"),
    ("B", "\u0920"),
    ("\xec", "\u0921\u094d\u0921"),
    ("\xef", "\u0921\u094d\u0922"),
    ("M+", "\u0921\u093c"),
    ("<+", "\u0922\u093c"),
    ("M", "\u0921"),
    ("<", "\u0922"),
    (".k", "\u0923"),
    (".", "\u0923\u094d"),
    ("r", "\u0924"),
    ("Rk", "\u0924"),
    ("R", "\u0924\u094d"),
    ("Fk", "\u0925"),
    ("F", "\u0925\u094d"),
    (")", "\u0926\u094d\u0927"),
    ("n", "\u0926"),
    ("/k", "\u0927"),
    ("/", "\u0927\u094d"),
    ("\xcb", "\u0927\u094d"),
    ("\xe8", "\u0927"),
    ("u", "\u0928"),
    ("Uk", "\u0928"),
    ("U", "\u0928\u094d"),
    ("i", "\u092a"),
    ("Ik", "\u092a"),
    ("I", "\u092a\u094d"),
    ("Q", "\u092b"),
    ("\xb6", "\u092b\u094d"),
    ("c", "\u092c"),
    ("Ck", "\u092c"),
    ("C", "\u092c\u094d"),
    ("Hk", "\u092d"),
    ("H", "\u092d\u094d"),
    ("e", "\u092e"),
    ("Ek", "\u092e"),
    ("E", "\u092e\u094d"),
    (";", "\u092f"),
    ("\xb8", "\u092f\u094d"),
    ("j", "\u0930"),
    ("y", "\u0932"),
    ("Yk", "\u0932"),
    ("Y", "\u0932\u094d"),
    ("G", "\u0933"),
    ("o", "\u0935"),
    ("Ok", "\u0935"),
    ("O", "\u0935\u094d"),
    ("'k", "\u0936"),
    ("'", "\u0936\u094d"),
    ('"k', "\u0937"),
    ('"', "\u0937\u094d"),
    ("l", "\u0938"),
    ("Lk", "\u0938"),
    ("L", "\u0938\u094d"),
    ("g", "\u0939"),
    ("\xc8", "\u0940\u0902"),
    ("saz", "\u094d\u0930\u0947\u0902"),
    ("z", "\u094d\u0930"),
    ("\xcc", "\u0926\u094d\u0926"),
    ("\xcd", "\u091f\u094d\u091f"),
    ("\xce", "\u091f\u094d\u0920"),
    ("\xcf", "\u0921\u094d\u0921"),
    ("\xd1", "\u0915\u0943"),
    ("\xd2", "\u092d"),
    ("\xd3", "\u094d\u092f"),
    ("\xd4", "\u0921\u094d\u0922"),
    ("\xd6", "\u091d\u094d"),
    ("\xdck", "\u0936"),
    ("\xdc", "\u0936\u094d"),
    ("\u201a", "\u0949"),
    ("kas", "\u094b\u0902"),
    ("ks", "\u094b"),
    ("kS", "\u094c"),
    ("\xa1k", "\u093e\u0901"),
    ("ak", "k\u0902"),
    ("k", "\u093e"),
    ("ah", "\u0940\u0902"),
    ("h", "\u0940"),
    ("aq", "\u0941\u0902"),
    ("q", "\u0941"),
    ("aw", "\u0942\u0902"),
    ("\xa1w", "\u0942\u0901"),
    ("w", "\u0942"),
    ("`", "\u0943"),
    ("\u0300", "\u0943"),
    ("as", "\u0947\u0902"),
    ("\xb1s", "s\xb1"),
    ("s", "\u0947"),
    ("aS", "\u0948\u0902"),
    ("S", "\u0948"),
    ("a\xaa", "\u094d\u0930\u0902"),
    ("\xaa", "\u094d\u0930"),
    ("fa", "\u0902f"),
    ("a", "\u0902"),
    ("\xa1", "\u0901"),
    ("%", ":"),
    ("W", "\u0945"),
    ("\u2022", "\u093d"),
    ("\xb7", "\u093d"),
    ("\u2219", "\u093d"),
    ("~j", "\u094d\u0930"),
    ("~", "\u094d"),
    ("\\", "?"),
    ("+", "\u093c"),
    ("^", "\u2018"),
    ("*", "\u2019"),
    ("\xde", "\u201c"),
    ("\xdf", "\u201d"),
    ("(", ";"),
    ("\xbc", "("),
    ("\xbd", ")"),
    ("\xbf", "{"),
    ("\xc0", "}"),
    ("\xbe", "="),
    ("A", "\u0964"),
    ("-", "."),
    ("&", "-"),
    ("\u03bc", "-"),
    ("\u0152", "\u0970"),
    ("]", ","),
    ("~ ", "\u094d "),
    ("@", "/"),
    ("\xae", "\u0948\u0902"),
]

_UNICODE_VOWEL_SIGNS = set(
    "\u0905\u0906\u0907\u0908\u0909\u090a\u090f\u0910\u0913\u0914"
    "\u093e\u093f\u0940\u0941\u0942\u0943\u0947\u0948\u094b\u094c"
    "\u0902\u0903\u0901\u0945"
)
_UNICODE_UNATTACHED = set(
    "\u093e\u093f\u0940\u0941\u0942\u0943\u0947\u0948\u094b\u094c"
    "\u0902\u0903\u0901\u0945"
)


def krutidev_to_unicode(text: str) -> str:
    """Convert Kruti Dev 010–encoded text to Unicode Devanagari."""
    if not text:
        return text
    s = text
    s = s.replace(" \xaa", "\xaa").replace(" ~j", "~j").replace(" z", "z")

    for src, dst in _K2U:
        s = s.replace(src, dst)

    s = s.replace("\xb1", "Z\u0902")
    s = s.replace("\xc6", "\u0930\u094df")

    # f + ? -> ? + ि
    for _ in range(len(s) + 1):
        m = re.search(r"f(.)", s)
        if not m:
            break
        s = s.replace("f" + m.group(1), m.group(1) + "\u093f", 1)
    s = s.replace("f", "\u093f")

    s = s.replace("\xc7", "fa").replace("\xaf", "fa")
    s = s.replace("\xc9", "\u0930\u094dfa")

    for _ in range(len(s) + 1):
        m = re.search(r"fa(.)", s)
        if not m:
            break
        s = s.replace("fa" + m.group(1), m.group(1) + "\u093f\u0902", 1)

    s = s.replace("\xca", "\u0940Z")

    for _ in range(len(s) + 1):
        m = re.search("\u093f\u094d(.)", s)
        if not m:
            break
        s = s.replace("\u093f\u094d" + m.group(1), "\u094d" + m.group(1) + "\u093f", 1)

    s = s.replace("\u094dZ", "Z")

    # Place र् (from trailing Z) before matrās — LTRC kru2uni algorithm.
    guard = 0
    m = re.search(r"(.)?Z", s)
    while m and guard < 10_000:
        guard += 1
        misplaced = m.group(1) or ""
        needle = misplaced + "Z"
        index_r = s.index(needle)
        while index_r >= 0 and s[index_r] in _UNICODE_VOWEL_SIGNS:
            index_r -= 1
            if index_r < 0:
                break
            misplaced = s[index_r] + misplaced
        s = s.replace(misplaced + "Z", "\u0930\u094d" + misplaced, 1)
        m = re.search(r"(.)?Z", s)
    if "Z" in s:
        s = s.replace("Z", "\u0930\u094d")

    for matra in _UNICODE_UNATTACHED:
        s = s.replace(" " + matra, matra)
        s = s.replace("," + matra, matra + ",")
        s = s.replace("\u094d" + matra, matra)

    s = s.replace("\u094d\u094d\u0930", "\u094d\u0930")
    s = s.replace("\u094d\u0930\u094d", "\u0930\u094d")
    s = s.replace("\u094d\u094d", "\u094d")
    s = s.replace("\u094d ", " ")
    return s
