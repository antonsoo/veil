"""Does a token read as words, or as noise?

An issued credential is random: its letters follow each other the way dice
fall. A file path, a test name or a request id is made of words, and in
words some letters follow others far more often than chance (``th``, ``er``,
``in``) and some almost never (``qx``, ``zv``).

The table below scores every pair of letters by how much more or less
likely it is than chance, counted over the words and identifiers of the
Python standard library (``scripts/build_bigram_table.py`` builds it and
explains the encoding). A run of letters whose pairs score above zero on
average reads as a word. A token most of whose letters sit in such runs is
a name somebody chose, not a key somebody generated.
"""

from __future__ import annotations

import re
import string

_TABLE = (
    "0fji19f0h0cmkl0g0mknee9ac0",  # a
    "l8gcn275il0l97jc0hh9l000l8",  # b
    "l0c6m70kh2kkc6o72gcmf63070",  # c
    "ka7hra20n50e59j70fidj424b0",  # d
    "i8jjdib1807mgl9gamll4cbic0",  # e
    "k0bdij60p00i8aob1lffj020a0",  # f
    "f697q4dgk00ibkf70inekb1009",  # g
    "n036r304l03898m00fafd00060",  # h
    "ddhfelf0406jipkd0fml0e0c0d",  # i
    "h0a3s100c0f411nd09d5m01050",  # j
    "h2ber8d4k02j5hdd6claf3k051",  # k
    "k97gon30m03j39kb06jhi450g2",  # l
    "nh5cq400i05cf7mm06hcf00070",  # m
    "l5jlmel3g0cc4dmb03jmfd00a0",  # n
    "aghk8ha0c0bfiodi0oikicf503",  # o
    "n3abn729h05k66li1mdlga80h0",  # p
    "56292401740d4db85gf4u10100",  # q
    "l7ddp9i0k0b9fkl80iijfa80g0",  # r
    "f1e6q6bgk09c98hh39koh381f0",  # s
    "k5cbna0om00da6kb0khfk2a2h5",  # t
    "dfeclfc0f00ljm9j0okl700700",  # u
    "q330r635k000b9e60442006100",  # v
    "m77el90mo00e3hk36mg613a500",  # w
    "j9o8jc38k00ea0al09dq330ea7",  # x
    "8bcbj985i00dhhgp0bnn88g085",  # y
    "h272t40cm00eech309875030a8",  # z
)
_BASE36 = string.digits + string.ascii_lowercase
_PAIR_SCORE = {
    first + second: _BASE36.index(digit) - 17
    for first, row in zip(string.ascii_lowercase, _TABLE, strict=True)
    for second, digit in zip(string.ascii_lowercase, row, strict=True)
}

# camelCase and ACRONYMWord boundaries split a run of letters into words.
_WORD_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
_SEPARATOR_RE = re.compile(r"[/_+=.\-]")
# Hexadecimal with a digit in it, between separators: a hash, a UUID group, a
# counter. An identifier, as a whole token of plain hex already is.
_ID_PIECE_RE = re.compile(r"[0-9a-fA-F]*\d[0-9a-fA-F]*")

_MIN_WORD = 3
_MAX_ABBREVIATION = 4
_MIN_RANDOM_BODY = 16
_MIN_LETTER_SHARE = 0.4
_MAX_WORD_SHARE = 0.4


def reads_as_word(letters: str) -> bool:
    """Whether a run of letters has the letter pairs of a word."""
    lowered = letters.lower()
    if len(lowered) < _MIN_WORD:
        return False
    return sum(_PAIR_SCORE[a + b] for a, b in zip(lowered, lowered[1:], strict=False)) > 0


def looks_random(token: str) -> bool:
    """Whether a token of ASCII letters, digits and separators could be a generated key.

    False for a token that is mostly words (a path, a snake_case or camelCase
    name), mostly digits, or whose only random-looking parts are hexadecimal
    identifiers between separators.
    """
    pieces = [
        piece for piece in _SEPARATOR_RE.split(token) if piece and not _ID_PIECE_RE.fullmatch(piece)
    ]
    body = sum(len(piece) for piece in pieces)
    if body < _MIN_RANDOM_BODY:
        return False
    letters = sum(ch.isalpha() for piece in pieces for ch in piece)
    if letters < _MIN_LETTER_SHARE * body:
        return False
    in_words = 0
    for piece in pieces:
        if len(piece) <= _MAX_ABBREVIATION and piece.isalpha():
            # "pkg", "usr", "io", "v": a whole path component or name part of
            # a few letters is an abbreviation. Random text does not put two
            # separators that close together.
            in_words += len(piece)
        else:
            in_words += sum(len(word) for word in _WORD_RE.findall(piece) if reads_as_word(word))
    return bool(in_words < _MAX_WORD_SHARE * letters)
