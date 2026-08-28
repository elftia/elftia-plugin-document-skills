"""Fixed PDF simple-font encodings expressed as code-to-Unicode tables."""

from typing import TypeAlias

EncodingTable: TypeAlias = tuple[str | None, ...]

WIN_ANSI: EncodingTable = (
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    " ", "!", '"', "#", "$", "%", "&", "'",
    "(", ")", "*", "+", ",", "-", ".", "/",
    "0", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", ":", ";", "<", "=", ">", "?",
    "@", "A", "B", "C", "D", "E", "F", "G",
    "H", "I", "J", "K", "L", "M", "N", "O",
    "P", "Q", "R", "S", "T", "U", "V", "W",
    "X", "Y", "Z", "[", "\\", "]", "^", "_",
    "`", "a", "b", "c", "d", "e", "f", "g",
    "h", "i", "j", "k", "l", "m", "n", "o",
    "p", "q", "r", "s", "t", "u", "v", "w",
    "x", "y", "z", "{", "|", "}", "~", "•",
    "€", "•", "‚", "ƒ", "„", "…", "†", "‡",
    "ˆ", "‰", "Š", "‹", "Œ", "•", "Ž", "•",
    "•", "‘", "’", "“", "”", "•", "–", "—",
    "˜", "™", "š", "›", "œ", "•", "ž", "Ÿ",
    " ", "¡", "¢", "£", "¤", "¥", "¦", "§",
    "¨", "©", "ª", "«", "¬", "-", "®", "¯",
    "°", "±", "²", "³", "´", "µ", "¶", "·",
    "¸", "¹", "º", "»", "¼", "½", "¾", "¿",
    "À", "Á", "Â", "Ã", "Ä", "Å", "Æ", "Ç",
    "È", "É", "Ê", "Ë", "Ì", "Í", "Î", "Ï",
    "Ð", "Ñ", "Ò", "Ó", "Ô", "Õ", "Ö", "×",
    "Ø", "Ù", "Ú", "Û", "Ü", "Ý", "Þ", "ß",
    "à", "á", "â", "ã", "ä", "å", "æ", "ç",
    "è", "é", "ê", "ë", "ì", "í", "î", "ï",
    "ð", "ñ", "ò", "ó", "ô", "õ", "ö", "÷",
    "ø", "ù", "ú", "û", "ü", "ý", "þ", "ÿ",
)

MAC_ROMAN: EncodingTable = (
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    " ", "!", '"', "#", "$", "%", "&", "'",
    "(", ")", "*", "+", ",", "-", ".", "/",
    "0", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", ":", ";", "<", "=", ">", "?",
    "@", "A", "B", "C", "D", "E", "F", "G",
    "H", "I", "J", "K", "L", "M", "N", "O",
    "P", "Q", "R", "S", "T", "U", "V", "W",
    "X", "Y", "Z", "[", "\\", "]", "^", "_",
    "`", "a", "b", "c", "d", "e", "f", "g",
    "h", "i", "j", "k", "l", "m", "n", "o",
    "p", "q", "r", "s", "t", "u", "v", "w",
    "x", "y", "z", "{", "|", "}", "~", None,
    "Ä", "Å", "Ç", "É", "Ñ", "Ö", "Ü", "á",
    "à", "â", "ä", "ã", "å", "ç", "é", "è",
    "ê", "ë", "í", "ì", "î", "ï", "ñ", "ó",
    "ò", "ô", "ö", "õ", "ú", "ù", "û", "ü",
    "†", "°", "¢", "£", "§", "•", "¶", "ß",
    "®", "©", "™", "´", "¨", None, "Æ", "Ø",
    None, "±", None, None, "¥", "µ", None, None,
    None, None, None, "ª", "º", None, "æ", "ø",
    "¿", "¡", "¬", None, "ƒ", None, None, "«",
    "»", "…", " ", "À", "Ã", "Õ", "Œ", "œ",
    "–", "—", "“", "”", "‘", "’", "÷", None,
    "ÿ", "Ÿ", "⁄", "¤", "‹", "›", "ﬁ", "ﬂ",
    "‡", "·", "‚", "„", "‰", "Â", "Ê", "Á",
    "Ë", "È", "Í", "Î", "Ï", "Ì", "Ó", "Ô",
    None, "Ò", "Ú", "Û", "Ù", "ı", "ˆ", "˜",
    "¯", "˘", "˙", "˚", "¸", "˝", "˛", "ˇ",
)

STANDARD: EncodingTable = (
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    " ", "!", '"', "#", "$", "%", "&", "’",
    "(", ")", "*", "+", ",", "-", ".", "/",
    "0", "1", "2", "3", "4", "5", "6", "7",
    "8", "9", ":", ";", "<", "=", ">", "?",
    "@", "A", "B", "C", "D", "E", "F", "G",
    "H", "I", "J", "K", "L", "M", "N", "O",
    "P", "Q", "R", "S", "T", "U", "V", "W",
    "X", "Y", "Z", "[", "\\", "]", "^", "_",
    "‘", "a", "b", "c", "d", "e", "f", "g",
    "h", "i", "j", "k", "l", "m", "n", "o",
    "p", "q", "r", "s", "t", "u", "v", "w",
    "x", "y", "z", "{", "|", "}", "~", None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, "¡", "¢", "£", "⁄", "¥", "ƒ", "§",
    "¤", "'", "“", "«", "‹", "›", "ﬁ", "ﬂ",
    None, "–", "†", "‡", "·", None, "¶", "•",
    "‚", "„", "”", "»", "…", "‰", None, "¿",
    None, "`", "´", "ˆ", "˜", "¯", "˘", "˙",
    "¨", None, "˚", "¸", None, "˝", "˛", "ˇ",
    "—", None, None, None, None, None, None, None,
    None, None, None, None, None, None, None, None,
    None, "Æ", None, "ª", None, None, None, None,
    "Ł", "Ø", "Œ", "º", None, None, None, None,
    None, "æ", None, None, None, "ı", None, None,
    "ł", "ø", "œ", "ß", None, None, None, None,
)

_TABLES: dict[str, EncodingTable] = {
    "/WinAnsiEncoding": WIN_ANSI,
    "/MacRomanEncoding": MAC_ROMAN,
    "/StandardEncoding": STANDARD,
}

# Each tuple starts with the canonical code. The remaining codes are accepted
# only because the normative PDF encoding vectors assign the exact same glyph
# name to every listed code; unlisted Unicode collisions stay ambiguous.
_SAME_GLYPH_DUPLICATES: dict[str, dict[str, tuple[int, ...]]] = {
    "/WinAnsiEncoding": {
        " ": (0x20, 0xA0),
        "-": (0x2D, 0xAD),
        "•": (0x95, 0x7F, 0x81, 0x8D, 0x8F, 0x90, 0x9D),
    },
    "/MacRomanEncoding": {
        " ": (0x20, 0xCA),
    },
}


def encoding_table(name: str | None) -> EncodingTable | None:
    return _TABLES.get(name) if name is not None else None


def encode_simple_text(name: str | None, text: str) -> bytes | None:
    table = encoding_table(name)
    if table is None or name is None:
        return None
    codes_by_character: dict[str, list[int]] = {}
    for code, character in enumerate(table):
        if character is None:
            continue
        codes_by_character.setdefault(character, []).append(code)
    inverse = {
        character: _canonical_code(name, character, codes)
        for character, codes in codes_by_character.items()
    }
    if any(inverse.get(character) is None for character in text):
        return None
    return bytes(inverse[character] for character in text if inverse[character] is not None)


def _canonical_code(name: str, character: str, codes: list[int]) -> int | None:
    if len(codes) == 1:
        return codes[0]
    proven_equivalent = _SAME_GLYPH_DUPLICATES.get(name, {}).get(character)
    if proven_equivalent is None or set(proven_equivalent) != set(codes):
        return None
    return proven_equivalent[0]


def decode_simple_bytes(name: str | None, encoded: bytes) -> str | None:
    table = encoding_table(name)
    if table is None:
        return None
    decoded = [table[code] for code in encoded]
    if any(character is None for character in decoded):
        return None
    return "".join(character for character in decoded if character is not None)


assert all(len(table) == 256 for table in _TABLES.values())
