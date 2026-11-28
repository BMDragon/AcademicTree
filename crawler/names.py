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


def given_initials(name):
    t = [x for x in tokens(name) if x not in PARTICLES]
    return {x[0] for x in t[:-1]}


def same_person(a, b):
    """Same surname, and the first given name of one matches (by initial) any
    given name of the other: "Gustav Dirichlet" ~ "Johann Peter Gustav Lejeune
    Dirichlet", "Barish, Barry C." ~ "Barry Clark Barish"."""
    ka, kb = key(a), key(b)
    if not ka or not kb or ka[0] != kb[0]:
        return False
    if not ka[1] or not kb[1]:
        return True
    return ka[1] in given_initials(b) or kb[1] in given_initials(a)


def _norm_word(w):
    w = w.translate(_TRANS)
    w = unicodedata.normalize("NFKD", w).encode("ascii", "ignore").decode()
    return re.sub(r"([aou])e", r"\1", w.lower())


def surname(name):
    t = [x for x in tokens(name) if x not in PARTICLES]
    return t[-1] if t else None


def is_eponym(label, person_name):
    """True if `label` contains the person's surname as a capitalised word:
    "Frobenius method", "Fermi's golden rule", "Bose–Einstein statistics",
    "Schrödinger equation". Lower-case uses ("first-born") don't count."""
    sn = surname(person_name)
    if not sn or len(sn) < 3:
        return False
    for w in re.findall(r"[^\W\d_]+", label or ""):
        if w[0].isupper() and _norm_word(w) == sn:
            return True
    return False
