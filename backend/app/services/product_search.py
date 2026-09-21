"""Shared product matching: exact identifier, stocked first, name prefix before substring."""
import re
import unicodedata
from sqlalchemy import case, func

_TRANSLATE = str.maketrans('يكى۰۱۲۳۴۵۶۷۸۹٠١٢٣٤٥٦٧٨٩', 'یکی01234567890123456789')
_ALPHABET = {c: i + 20 for i, c in enumerate('ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی')}

def normalize(value):
    value = str(value or '').translate(_TRANSLATE).replace('\u200c', ' ')
    return re.sub(r'\s+', ' ', ''.join(c for c in unicodedata.normalize('NFKD', value) if not unicodedata.combining(c))).strip().casefold()

def alphabet_key(value):
    return tuple(_ALPHABET.get(c, 0 if c.isspace() else int(c)+1 if c.isascii() and c.isdigit() else 1000+ord(c)) for c in normalize(value))

def compare_names(a, b):
    a,b=alphabet_key(a),alphabet_key(b)
    return (a>b)-(a<b)

def name_column(column):
    return func.product_search_normalize(column)

def literal_like(value):
    return value.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')

def rank(column, query):
    q=literal_like(normalize(query)); n=name_column(column)
    return case((n == normalize(query),0),(n.like(q+'%', escape='\\'),1),
                (n.like('% '+q+'%', escape='\\'),2),else_=3)
