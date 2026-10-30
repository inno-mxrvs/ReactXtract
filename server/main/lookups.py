import re
import unicodedata
import xml.etree.ElementTree as ET
from functools import lru_cache

from django.conf import settings


LOOKUP_DIRECTORY = 'lookup list'
SOLVENT_LOOKUP_FILE = 'solvent list.xml'
REACTION_CONDITION_LOOKUP_FILE = 'reaction condition.xml'
REAGENT_CATALYST_LOOKUP_FILE = 'ReagCat.txt'


def _normalize_lookup_term(value):
    text = unicodedata.normalize('NFKC', str(value or ''))
    text = text.replace('&gamma;', 'gamma').replace('γ', 'gamma')
    text = text.casefold().strip()
    text = re.sub(r'[‐‑‒–—−]', '-', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip(' .;,')


def _display_name(value):
    return str(value or '').replace('&gamma;', 'γ').strip()


@lru_cache(maxsize=8)
def _load_lookup(path_string, modified_ns):
    del modified_ns  # Included in the cache key so edited XML reloads automatically.
    root = ET.parse(path_string).getroot()
    entries = []
    term_index = {}
    for item in root.findall('Item'):
        entry = {
            'type': root.attrib.get('type', ''),
            'code': item.attrib.get('code', ''),
            'name': _display_name(item.attrib.get('name', '')),
            'synonyms': [
                synonym.strip()
                for synonym in item.attrib.get('synonyms', '').split(';')
                if synonym.strip()
            ],
        }
        entries.append(entry)
        for term in [entry['name'], *entry['synonyms']]:
            normalized = _normalize_lookup_term(term)
            if normalized and normalized not in term_index:
                term_index[normalized] = entry
    return entries, term_index


def _lookup(filename):
    path = settings.PROJECT_DIR / LOOKUP_DIRECTORY / filename
    if not path.exists():
        return [], {}
    return _load_lookup(str(path), path.stat().st_mtime_ns)


def _split_workname_aliases(value):
    # Commas followed by whitespace separate aliases in ReagCat. Commas in
    # locants such as N,N'- or 1,8- do not have following whitespace.
    return [alias.strip() for alias in re.split(r',\s+', str(value or '')) if alias.strip()]


@lru_cache(maxsize=4)
def _load_reagent_catalyst_lookup(path_string, modified_ns):
    del modified_ns
    records = []
    current = {}
    in_features = False
    with open(path_string, encoding='cp1252') as lookup_file:
        for line in lookup_file:
            line = line.rstrip('\r\n')
            if line == '[MERKMALE]':
                in_features = True
                continue
            if not in_features:
                continue
            if line == '@.':
                if current:
                    records.append(current)
                    current = {}
                continue
            match = re.match(r'^@:([^=]+)=(.*)$', line)
            if match:
                current[match.group(1)] = match.group(2).strip()
    if current:
        records.append(current)

    entries = []
    term_candidates = {}
    for record in records:
        canonical = record.get('MNAME', '').strip()
        workname = record.get('WORKNAME', '').strip()
        entry = {
            'type': 'REAGCAT',
            'code': record.get('XRN', '').strip(),
            'name': canonical,
            'workname': workname,
            'has_canonical_name': bool(canonical),
        }
        entries.append(entry)
        aliases = [canonical, workname, *_split_workname_aliases(workname)]
        for alias in aliases:
            normalized = _normalize_lookup_term(alias)
            if normalized:
                term_candidates.setdefault(normalized, []).append(entry)

    # An ambiguous alias such as "phosphorus" must not silently pick one of
    # multiple records. Specific WORKNAME aliases remain usable.
    term_index = {
        term: candidates[0]
        for term, candidates in term_candidates.items()
        if len({candidate['code'] for candidate in candidates}) == 1
    }
    return entries, term_index


def _reagent_catalyst_lookup():
    path = settings.PROJECT_DIR / LOOKUP_DIRECTORY / REAGENT_CATALYST_LOOKUP_FILE
    if not path.exists():
        return [], {}
    return _load_reagent_catalyst_lookup(str(path), path.stat().st_mtime_ns)


def normalize_solvent_values(values):
    """Canonicalize exact known names/synonyms and retain every unknown value."""
    _, term_index = _lookup(SOLVENT_LOOKUP_FILE)
    normalized_values = []
    matches = []
    for value in values or []:
        original = str(value or '').strip()
        if not original:
            continue
        entry = term_index.get(_normalize_lookup_term(original))
        canonical = entry['name'] if entry else original
        normalized_values.append(canonical)
        matches.append({
            'input': original,
            'value': canonical,
            'matched': bool(entry),
            'lookup_type': entry['type'] if entry else '',
            'code': entry['code'] if entry else '',
        })
    return normalized_values, matches


def normalize_reagent_catalyst_values(values):
    """Use MNAME when available; retain unmatched or non-canonical values."""
    _, term_index = _reagent_catalyst_lookup()
    normalized_values = []
    matches = []
    for value in values or []:
        original = str(value or '').strip()
        if not original:
            continue
        entry = term_index.get(_normalize_lookup_term(original))
        canonical = entry['name'] if entry and entry['has_canonical_name'] else original
        normalized_values.append(canonical)
        matches.append({
            'input': original,
            'value': canonical,
            'matched': bool(entry),
            'canonicalized': bool(entry and entry['has_canonical_name']),
            'lookup_type': entry['type'] if entry else '',
            'code': entry['code'] if entry else '',
            'workname': entry['workname'] if entry else '',
        })
    return normalized_values, matches


def match_reaction_conditions(value):
    """Tag known condition phrases without rewriting the source-supported text."""
    text = _normalize_lookup_term(value)
    if not text:
        return []
    entries, _ = _lookup(REACTION_CONDITION_LOOKUP_FILE)
    candidates = []
    for entry in entries:
        terms = [entry['name'], *entry['synonyms']]
        for term in terms:
            normalized_term = _normalize_lookup_term(term)
            match = re.search(
                rf'(?<![\w]){re.escape(normalized_term)}(?![\w])',
                text,
            )
            if match:
                candidates.append((entry, term, match.span(), len(normalized_term)))
                break

    # Prefer a specific phrase such as "Microwave irradiation" over the
    # overlapping generic term "Irradiation".
    selected = []
    seen_codes = set()
    for entry, matched_term, span, length in sorted(candidates, key=lambda item: item[3], reverse=True):
        if entry['code'] in seen_codes:
            continue
        if any(start <= span[0] and end >= span[1] for _, _, (start, end), _ in selected):
            continue
        seen_codes.add(entry['code'])
        selected.append((entry, matched_term, span, length))
    selected.sort(key=lambda item: (item[2][0], int(item[0]['code'])))
    return [{
        'value': entry['name'],
        'matched_text': matched_term,
        'lookup_type': entry['type'],
        'code': entry['code'],
    } for entry, matched_term, _, _ in selected]


def reaction_lookup_metadata(solvents, other_conditions, reagents=None, catalysts=None):
    normalized_solvents, solvent_matches = normalize_solvent_values(solvents)
    _, reagent_matches = normalize_reagent_catalyst_values(reagents)
    _, catalyst_matches = normalize_reagent_catalyst_values(catalysts)
    return normalized_solvents, {
        'solvents': solvent_matches,
        'reagents': reagent_matches,
        'catalysts': catalyst_matches,
        'reaction_conditions': match_reaction_conditions(other_conditions),
        'non_exhaustive': True,
    }
