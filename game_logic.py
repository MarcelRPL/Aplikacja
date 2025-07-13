import re
import random

LETTER_POINTS = {
    "a": 1, "b": 3, "c": 3, "d": 2,
    "e": 1, "f": 4, "g": 2, "h": 4,
    "i": 1, "j": 8, "k": 5, "l": 1,
    "m": 3, "n": 1, "o": 1, "p": 3,
    "q": 10, "r": 1, "s": 1, "t": 1,
    "u": 1, "v": 4, "w": 4, "x": 8,
    "y": 4, "z": 10, "ą": 5, "ć": 6,
    "ę": 5, "ł": 3, "ń": 7, "ó": 7,
    "ś": 5, "ź": 9, "ż": 5
}

VALID_WORD_RE = re.compile(r"^[a-ząćęłńóśźż]+$")


def load_words(min_length=6):
    with open("data/slowa.txt", encoding="utf-8") as f:
        return set(
            word.strip().lower()
            for word in f 
            if len(word.strip()) >= min_length and VALID_WORD_RE.fullmatch(word.strip().lower())
            )
    

def valid_word(word, start, end, dictionary):
    return (
        word in dictionary and
        word.startswith(start) and
        word.endswith(end)
    )


def calculate_score(word):
    return sum(LETTER_POINTS.get(c, 0) for c in word.lower())


def random_letter():
    
    letters = ["a", "b", "c", "d", "e", "f", "g", "h", "i", "j", "k", "l", "m", "n", "o", "p", "q", "r", "s", "t", "u", "v", "w", "x", "y", "z"]
    letter = letters[random.randint(0, 25)]

    return letter