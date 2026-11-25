"""Name normalization used for fuzzy identity matching."""
import re
import unicodedata

_TRANS = str.maketrans({"ä": "a", "ö": "o", "ü": "u", "Ä": "A", "Ö": "O", "Ü": "U", "ß": "ss",
                        "ø": "o", "Ø": "O", "æ": "ae", "ł": "l", "Ł": "L"})
PARTICLES = {"van", "von", "der", "de", "den", "du", "la", "le", "di", "da", "del", "dos", "y", "zu", "ter"}
SUFFIXES = {"jr", "sr", "ii", "iii", "iv"}


def tokens(name):
    s = (name or "").translate(_TRANS)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    # German transliteration variants: Stoecker == Stöcker == Stocker
    s = re.sub(r"([aou])e", r"\1", s)
    if "," in s:  # "Last, First" -> "First Last"
        last, first = s.split(",", 1)
        s = first + " " + last
    return [t for t in re.sub(r"[^a-z ]+", " ", s).split() if t not in SUFFIXES]


def key(name):
    """(surname, first initial) — coarse key for merging co-advisors of one student."""
    t = [x for x in tokens(name) if x not in PARTICLES]
    if not t:
        return None
    return (t[-1], t[0][0] if len(t) > 1 else "")


def same_person(a, b):
    ka, kb = key(a), key(b)
    if not ka or not kb or ka[0] != kb[0]:
        return False
    return not ka[1] or not kb[1] or ka[1] == kb[1]
