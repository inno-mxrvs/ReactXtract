import base64
import json
import os
import re
import time
import unicodedata
from concurrent.futures import ThreadPoolExecutor, as_completed
from decimal import Decimal, ROUND_HALF_UP

import fitz
from django.conf import settings
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.base import ContentFile

from .lookups import (
    normalize_reaction_conditions,
    normalize_reagent_catalyst_values,
    normalize_solvent_values,
)
from .models import AITokenUsage


REACTION_FIELDS = [
    'products', 'starting_materials', 'reagents', 'catalysts', 'solvents',
    'reaction_time', 'reaction_pressure', 'reaction_temperature',
    'other_conditions', 'reaction_stages', 'reaction_description_type', 'yield',
]
STAGE_REACTION_FIELDS = [
    field for field in REACTION_FIELDS if field != 'reaction_stages'
]


def _field_metadata_schema():
    return {
        'type': 'object',
        'additionalProperties': False,
        'properties': {
            'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
            'source_file': {'type': 'string'},
            'page': {'type': 'string'},
            'quote': {'type': 'string'},
            'bbox': {
                'type': 'object', 'additionalProperties': False,
                'properties': {
                    'left': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'top': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'right': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'bottom': {'type': 'number', 'minimum': 0, 'maximum': 1},
                },
                'required': ['left', 'top', 'right', 'bottom'],
            },
        },
        'required': ['confidence', 'source_file', 'page', 'quote', 'bbox'],
    }


STAGE_DETAIL_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'stage_number': {'type': 'integer', 'minimum': 1},
        'description': {'type': 'string'},
        'starting_materials': {'type': 'array', 'items': {'type': 'string'}},
        'products': {'type': 'array', 'items': {'type': 'string'}},
        'reagents': {'type': 'array', 'items': {'type': 'string'}},
        'catalysts': {'type': 'array', 'items': {'type': 'string'}},
        'solvents': {'type': 'array', 'items': {'type': 'string'}},
        'reaction_time': {'type': 'string'},
        'reaction_pressure': {'type': 'string'},
        'reaction_temperature': {'type': 'string'},
        'other_conditions': {'type': 'string'},
        'reaction_description_type': {'type': 'string'},
        'yield': {'type': 'string'},
        'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
        'source_file': {'type': 'string'},
        'page': {'type': 'string'},
        'quote': {'type': 'string'},
    },
    'required': [
        'stage_number', 'description', 'starting_materials', 'products',
        'reagents', 'catalysts', 'solvents', 'reaction_time',
        'reaction_pressure', 'reaction_temperature', 'other_conditions',
        'reaction_description_type', 'yield',
        'confidence', 'source_file', 'page', 'quote',
    ],
}


REACTION_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'reactions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'products': {'type': 'array', 'items': {'type': 'string'}},
                    'starting_materials': {'type': 'array', 'items': {'type': 'string'}},
                    'reagents': {'type': 'array', 'items': {'type': 'string'}},
                    'catalysts': {'type': 'array', 'items': {'type': 'string'}},
                    'solvents': {'type': 'array', 'items': {'type': 'string'}},
                    'reaction_time': {'type': 'string'},
                    'reaction_pressure': {'type': 'string'},
                    'reaction_temperature': {'type': 'string'},
                    'other_conditions': {'type': 'string'},
                    'reaction_stages': {'type': 'string'},
                    'reaction_description_type': {'type': 'string'},
                    'yield': {'type': 'string'},
                    'stage_details': {
                        'type': 'array',
                        'items': STAGE_DETAIL_SCHEMA,
                    },
                    'field_metadata': {
                        'type': 'object',
                        'additionalProperties': False,
                        'properties': {field: _field_metadata_schema() for field in REACTION_FIELDS},
                        'required': REACTION_FIELDS,
                    },
                },
                'required': REACTION_FIELDS + ['stage_details', 'field_metadata'],
            },
        },
    },
    'required': ['reactions'],
}

EXTRACTION_OPERATIONAL_APPENDIX = """

Application requirements for hybrid PDF extraction:
- Analyze only the supplied SOURCE PAGE blocks and attached VISUAL CROP images.
- SOURCE PAGE blocks contain PyMuPDF native text reconstructed in column-aware reading order and may include separately extracted tables.
- VISUAL CROP images contain only bounded reaction-scheme or structure regions; full PDF pages are not attached when a crop can supply the visual evidence.
- The prompt maps every source page and visual crop to its original source page number and original normalized crop rectangle. Always report the original source page number and convert a crop-relative bbox back into original-page normalized coordinates.
- Prefer the structured native table rows when present, while checking an attached visual page when layout, arrows, structures, merged cells, or symbols carry information not represented in text.
- Use the section keywords to focus on explicit procedures, schemes, and experimental descriptions.
- Return each unavailable list field as [] and each unavailable scalar as "".
- The scalar fields include reaction_temperature, reaction_description_type, and yield. Return each as "" when unavailable and include field_metadata for each one.
- Keep distinct reactions separate. Do not collapse substrate-scope examples into a generic reaction.
- Treat every separately labeled product or compound example in a scheme, table, scope, or experimental section as its own reaction record when the source gives reaction-specific support. Never replace enumerated examples with one generic family record.
- When a source reports an inseparable or separable mixture containing two or more identified products, return each identified product as a separate product value and a separate reaction record. Never use a phrase such as "inseparable mixture of A and B" as one product name. Preserve mixture status and any reported product ratio under Other reaction conditions or Yield, as applicable.
- For every field, return field_metadata containing a confidence from 0 to 1, source filename, original page number, a short exact supporting quote, and bbox.
- Confidence must measure support in the supplied source, not general chemical plausibility. Use 0 when the field is empty.
- The quote must be short enough to locate in the PDF text. If unavailable, use empty strings for source_file, page, and quote.
- bbox is the visual source region with left, top, right, and bottom coordinates normalized from 0 to 1 against the original page. Enclose the supporting quote or table cell. Use zeros when unavailable.
- When a product or another value is supported only by a scheme drawing, structure, or image label, set bbox to the tight visual region containing that exact structure and label. Do not cite an unrelated nearby sentence merely because it mentions a ratio, condition, or compound number.
- Local solvent, reagent/catalyst, and reaction-condition lookup vocabularies are non-exhaustive. Extract every source-supported value even when it may not appear in a controlled list; never omit, reject, or lower confidence solely because a value is uncommon or absent from a lookup.
- Populate yield only when the cited evidence explicitly contains the word "yield" (including forms such as yielded, yields, or yield%). A bare percentage may be a concentration, solvent composition, selectivity, conversion, or another measurement and is not sufficient yield evidence.
- When more than one numeric reaction temperature is reported in the same unit, return one range ordered from the lowest to the highest value. Do not infer a numeric value for room temperature or another qualitative temperature.
- Format a reaction-temperature range with "-" instead of the word "to", for example "0 °C - room temperature".
- For reaction_stages, return only the explicitly supported stage count, or "Undetermined" when the source cannot establish it. Do not add work-up, purification, extraction, crystallization, solvent exchange, or repeated reagent-addition operations as stages.
- For a reaction with two or more explicitly supported stages, return one ordered stage_details entry per stage. Every stage entry must independently contain its source-supported products or intermediate, starting materials, reagents, catalysts, solvents, reaction time, reaction pressure, reaction temperature, other reaction conditions, type of reaction description, yield, concise transformation description, confidence, and exact source evidence. Do not copy a parent reaction's combined values into every stage; assign each value only to the stage where the source supports its use. Return [] when a stage breakdown is not explicitly supported; never invent a missing intermediate merely to match the stage count.
- Never return a numeric reaction_stages value greater than 1 with an empty stage_details array. When individual stages cannot be supported, return reaction_stages as "Undetermined" and stage_details as [].
- Never return a bare number such as "14" as a product. A numeric source label must include an explicit role, such as "compound 14", and must be formed by a source-supported preparative transformation. Atom assignments and locants such as H14, C14, H-14, C-14, or NMR peak annotations are characterization data, not products or reactions.
"""

DUPLICATE_DECISION_SCHEMA = {
    'type': 'object',
    'additionalProperties': False,
    'properties': {
        'decisions': {
            'type': 'array',
            'items': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'pair_id': {'type': 'integer'},
                    'is_duplicate': {'type': 'boolean'},
                    'confidence': {'type': 'number', 'minimum': 0, 'maximum': 1},
                    'reason': {'type': 'string'},
                },
                'required': ['pair_id', 'is_duplicate', 'confidence', 'reason'],
            },
        },
    },
    'required': ['decisions'],
}

DUPLICATE_DECISION_INSTRUCTIONS = """Decide whether each supplied pair describes the exact same chemical reaction.
Return one decision for every pair_id. Mark a pair as duplicate only when the evidence clearly identifies the same
reaction or experimental example. Similar transformations, shared products, alternative methods, optimization runs,
and separate substrate-scope examples are not duplicates. If uncertain, return is_duplicate false. Do not extract,
rewrite, merge, or supplement any reaction fields. The application will merge confirmed pairs locally.
"""

MISSING_VALUES = {'', 'not reported', 'not reported.', 'none', 'n/a', 'na', 'unknown'}
LIST_FIELDS = {'products', 'starting_materials', 'reagents', 'catalysts', 'solvents'}
AI_DUPLICATE_CONFIDENCE_THRESHOLD = Decimal('0.90')
AI_DUPLICATE_BATCH_SIZE = 50
SUBSCRIPT_TRANSLATION = str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉')
CHEMICAL_TOKEN_PATTERN = re.compile(
    r'(?<![A-Za-z0-9])'
    r'[A-Z][A-Za-z0-9]*(?:\([A-Za-z0-9]+\)[A-Za-z0-9]*)?'
    r'(?:[·∙][0-9]*[A-Z][A-Za-z0-9]*)*'
    r'(?![A-Za-z0-9])'
)
ELEMENTAL_MOLECULE_PATTERN = re.compile(r'^(?:H|N|O|F|Cl|Br|I|S|P|D)\d+$')
UPPERCASE_NUMBER_TOKEN_PATTERN = re.compile(r'^([A-Z]{2,})(\d+)([a-z]?)$')
ONE_LETTER_ELEMENT_SYMBOLS = frozenset('HBCNOFPSKVYIWUD')


class ExtractionDiscarded(Exception):
    """Raised when the reviewer leaves an active extraction without saving."""


def _raise_if_discard_requested(job):
    if job is None:
        return
    try:
        job.refresh_from_db(fields=['discard_requested'])
    except ObjectDoesNotExist as error:
        raise ExtractionDiscarded('The extraction was discarded.') from error
    if job.discard_requested:
        raise ExtractionDiscarded('The extraction was discarded.')


def get_extraction_instructions():
    instruction_path = settings.PROJECT_DIR / 'ReactXtract_Strict_Instructions_updated.txt'
    try:
        instructions = instruction_path.read_text(encoding='utf-8').strip()
    except FileNotFoundError as error:
        raise RuntimeError(f'Extraction instruction file is missing: {instruction_path}') from error
    if not instructions:
        raise RuntimeError(f'Extraction instruction file is empty: {instruction_path}')
    return instructions + EXTRACTION_OPERATIONAL_APPENDIX


def get_extraction_keywords():
    instructions = get_extraction_instructions()
    match = re.search(r'(?im)^keywords\s*:\s*(.+)$', instructions)
    if not match:
        return []
    return [keyword.strip().lower() for keyword in match.group(1).split(',') if keyword.strip()]


def format_chemical_subscripts(value):
    """Restore unambiguous formula subscripts flattened by PDF text layers."""
    if not isinstance(value, str) or not any(character.isdigit() for character in value):
        return value

    def format_token(match):
        token = match.group(0)
        uppercase_count = sum(character.isupper() for character in token)
        if uppercase_count < 2 and not ELEMENTAL_MOLECULE_PATTERN.fullmatch(token):
            return token
        uppercase_number = UPPERCASE_NUMBER_TOKEN_PATTERN.fullmatch(token)
        if uppercase_number and (
            uppercase_number.group(2).startswith('0')
            or not set(uppercase_number.group(1)) <= ONE_LETTER_ELEMENT_SYMBOLS
        ):
            return token

        characters = []
        for index, character in enumerate(token):
            previous = token[index - 1] if index else ''
            if character.isascii() and character.isdigit() and (previous.isalpha() or previous == ')'):
                characters.append(character.translate(SUBSCRIPT_TRANSLATION))
            elif (
                character.isascii() and character.isdigit()
                and index > 0 and token[index - 1].isascii() and token[index - 1].isdigit()
                and characters and characters[-1] in '₀₁₂₃₄₅₆₇₈₉'
            ):
                characters.append(character.translate(SUBSCRIPT_TRANSLATION))
            else:
                characters.append(character)
        return ''.join(characters)

    formatted = CHEMICAL_TOKEN_PATTERN.sub(format_token, value)
    # Deuterated-solvent notation is conventionally written with a subscript,
    # but the lowercase d form is intentionally outside the formula-token rule.
    return re.sub(
        r'(?<=-[dD])(\d+)',
        lambda match: match.group(1).translate(SUBSCRIPT_TRANSLATION),
        formatted,
    )


def _format_reaction_chemical_typography(reaction):
    formatted = dict(reaction)
    for field in REACTION_FIELDS:
        value = reaction.get(field)
        if isinstance(value, list):
            formatted[field] = [format_chemical_subscripts(item) for item in value]
        elif isinstance(value, str):
            formatted[field] = format_chemical_subscripts(value)
    formatted['stage_details'] = []
    for item in reaction.get('stage_details') or []:
        stage = dict(item)
        for field in STAGE_REACTION_FIELDS:
            value = item.get(field)
            if isinstance(value, list):
                stage[field] = [format_chemical_subscripts(entry) for entry in value]
            elif isinstance(value, str):
                stage[field] = format_chemical_subscripts(value)
        formatted['stage_details'].append(stage)
    return formatted


def _normalize_reaction_lookups(reaction):
    normalized = dict(reaction)
    normalized['solvents'], _ = normalize_solvent_values(reaction.get('solvents') or [])
    normalized['reagents'], _ = normalize_reagent_catalyst_values(reaction.get('reagents') or [])
    normalized['catalysts'], _ = normalize_reagent_catalyst_values(reaction.get('catalysts') or [])
    normalized['other_conditions'] = normalize_reaction_conditions(
        reaction.get('other_conditions') or ''
    )
    return normalized


DEGREE_SIGN = chr(176)
EN_DASH = chr(8211)
TEMPERATURE_VALUE_PATTERN = re.compile(
    rf'(?<![\w.])([+-]?\d+(?:\.\d+)?)\s*{DEGREE_SIGN}?\s*(C|K|F)\b',
    re.I,
)
TEMPERATURE_TO_RANGE_PATTERN = re.compile(
    rf'(?P<left>(?:[+-]?\d+(?:\.\d+)?\s*{DEGREE_SIGN}?\s*[CKF]|room temperature|ambient temperature))'
    rf'\s+to\s+'
    rf'(?P<right>(?:[+-]?\d+(?:\.\d+)?\s*{DEGREE_SIGN}?\s*[CKF]|room temperature|ambient temperature))',
    re.I,
)
YIELD_EVIDENCE_PATTERN = re.compile(r'\byield(?:ed|ing|s)?\b', re.I)
BARE_NUMERIC_PRODUCT_PATTERN = re.compile(r'^\(?\d+\)?$')
MIXTURE_PRODUCT_PREFIX_PATTERN = re.compile(
    r'^(?:an?\s+)?(?:(?:inseparable|separable)\s+)?mixture\s+of\s+',
    re.I,
)
MIXTURE_RATIO_SUFFIX_PATTERN = re.compile(
    r'\s+(?:in\s+)?(?:an?\s+)?(?:exo[:/]endo\s+)?ratio\b.*$',
    re.I,
)


def _format_number(value):
    return str(int(value)) if float(value).is_integer() else f'{value:g}'


def normalize_temperature_range(value):
    """Collapse multiple explicit temperatures in one unit to lowest-to-highest."""
    text = str(value or '').strip()
    text = TEMPERATURE_TO_RANGE_PATTERN.sub(r'\g<left> - \g<right>', text)
    matches = TEMPERATURE_VALUE_PATTERN.findall(text)
    if len(matches) < 2:
        return text
    units = {unit.upper() for _, unit in matches}
    if len(units) != 1:
        return text
    numbers = [float(number) for number, _ in matches]
    lowest, highest = min(numbers), max(numbers)
    unit = units.pop()
    if lowest == highest:
        return f'{_format_number(lowest)} {DEGREE_SIGN}{unit}'
    return f'{_format_number(lowest)}{EN_DASH}{_format_number(highest)} {DEGREE_SIGN}{unit}'


def _blank_field_metadata():
    return {
        'confidence': 0,
        'source_file': '',
        'page': '',
        'quote': '',
        'bbox': {'left': 0, 'top': 0, 'right': 0, 'bottom': 0},
    }


def split_product_values(products):
    """Split only explicit source mixture phrases into distinct product values."""
    separated = []
    seen = set()
    for raw_value in products or []:
        value = str(raw_value or '').strip()
        if not value:
            continue
        values = [value]
        prefix_match = MIXTURE_PRODUCT_PREFIX_PATTERN.match(value)
        if prefix_match:
            mixture = MIXTURE_RATIO_SUFFIX_PATTERN.sub('', value[prefix_match.end():])
            mixture = mixture.strip(' .;,')
            parts = [
                part.strip(' .;,')
                for part in re.split(r'\s+(?:and|&)\s+|\s+\+\s+', mixture, flags=re.I)
            ]
            if len(parts) >= 2 and all(parts):
                values = parts
        for product in values:
            if BARE_NUMERIC_PRODUCT_PATTERN.fullmatch(product):
                continue
            key = product.casefold()
            if key not in seen:
                seen.add(key)
                separated.append(product)
    return separated


def _separate_product_candidates(reaction):
    """Return one reaction candidate per product while retaining shared evidence."""
    products = split_product_values(reaction.get('products') or [])
    candidates = []
    for product in products:
        candidate = dict(reaction)
        candidate['products'] = [product]
        candidates.append(candidate)
    return candidates


def _validate_and_normalize_reaction_fields(reaction):
    """Apply deterministic safeguards after AI extraction and before consolidation."""
    normalized = dict(reaction)
    metadata = dict(reaction.get('field_metadata') or {})
    normalized['field_metadata'] = metadata
    products = split_product_values(reaction.get('products') or [])
    normalized['products'] = products
    if not products:
        metadata['products'] = _blank_field_metadata()
    stage_details = []
    for item in reaction.get('stage_details') or []:
        stage = dict(item)
        stage['products'] = split_product_values(item.get('products') or [])
        stage['starting_materials'] = [
            str(value).strip() for value in item.get('starting_materials') or [] if str(value).strip()
        ]
        stage['reagents'], _ = normalize_reagent_catalyst_values(item.get('reagents') or [])
        stage['catalysts'], _ = normalize_reagent_catalyst_values(item.get('catalysts') or [])
        stage['solvents'], _ = normalize_solvent_values(item.get('solvents') or [])
        stage['reaction_time'] = str(item.get('reaction_time') or '').strip()
        stage['reaction_pressure'] = str(item.get('reaction_pressure') or '').strip()
        stage['reaction_temperature'] = normalize_temperature_range(
            item.get('reaction_temperature') or ''
        )
        stage['other_conditions'] = normalize_reaction_conditions(
            item.get('other_conditions') or ''
        )
        stage['reaction_description_type'] = str(
            item.get('reaction_description_type') or ''
        ).strip()
        stage['yield'] = str(item.get('yield') or '').strip()
        stage_details.append(stage)
    normalized['stage_details'] = stage_details
    normalized['reaction_temperature'] = normalize_temperature_range(
        reaction.get('reaction_temperature') or ''
    )
    reaction_stages = str(reaction.get('reaction_stages') or '').strip()
    try:
        stated_stage_count = int(reaction_stages)
    except (TypeError, ValueError):
        stated_stage_count = 0
    if stage_details:
        normalized['reaction_stages'] = str(len(stage_details))
    elif stated_stage_count > 1:
        normalized['reaction_stages'] = 'Undetermined'
        metadata['reaction_stages'] = _blank_field_metadata()
    elif reaction_stages.casefold().strip(' .') in MISSING_VALUES:
        normalized['reaction_stages'] = 'Undetermined'

    reaction_yield = str(reaction.get('yield') or '').strip()
    yield_metadata = metadata.get('yield') or {}
    yield_quote = str(yield_metadata.get('quote') or '')
    if reaction_yield and not YIELD_EVIDENCE_PATTERN.search(yield_quote):
        normalized['yield'] = ''
        metadata['yield'] = _blank_field_metadata()
    return normalized


def _prepare_extracted_reaction(reaction):
    formatted = _format_reaction_chemical_typography(reaction)
    normalized = _normalize_reaction_lookups(formatted)
    return _validate_and_normalize_reaction_fields(normalized)


def select_keyword_pages_from_text(page_texts, keywords=None, context_pages=None):
    keywords = keywords if keywords is not None else get_extraction_keywords()
    context_pages = settings.AI_KEYWORD_CONTEXT_PAGES if context_pages is None else context_pages
    page_count = len(page_texts)
    strong_hits = set()
    fallback_hits = set()
    references_page = page_count
    normalized_page_texts = []
    reaction_signatures = [
        r'\bscheme\s+\d+[a-z]?\b',
        r'\breagents?\s+and\s+conditions\b',
        r'\b(?:general|representative)\s+(?:procedure|synthesis|example)\b',
        r'\bexperimental\s+section\b',
        r'\bsynthetic\s+methodology\b',
        r'\b(?:reaction|substrate)\s+scope\b',
        r'\boptimized\s+process\b',
        r'\bcharacterization\s+data\b',
    ]
    recipe_markers = [
        r'\bmmol\b', r'\bequiv(?:alent)?s?\b', r'\breaction mixture\b',
        r'\bwas added\b', r'\bwere added\b', r'\bstirred\b', r'\breflux(?:ed)?\b',
        r'\bafforded\b', r'\bisolated\b', r'\byield(?:ed|s)?\b',
    ]
    for index, source_text in enumerate(page_texts):
        lines = [' '.join(line.split()) for line in str(source_text or '').splitlines()]
        page_text = '\n'.join(lines).lower()
        normalized_page_texts.append(page_text)
        reference_line = next(
            (
                position
                for position, line in enumerate(lines)
                if len(line) <= 60 and re.search(r'\breferences\b', line, re.I)
            ),
            None,
        )
        if reference_line is not None:
            before_references = '\n'.join(lines[:reference_line]).lower()
            has_reaction_content_before_references = (
                bool(VISUAL_CONTENT_PATTERN.search(before_references))
                or any(re.search(pattern, before_references, re.I) for pattern in reaction_signatures)
                or sum(bool(re.search(pattern, before_references, re.I)) for pattern in recipe_markers) >= 3
            )
            # Keep a mixed final content/references page so schemes or procedures
            # above the References heading are not discarded with later citations.
            boundary = index + 1 if has_reaction_content_before_references else index
            references_page = min(references_page, boundary)
        if any(re.search(pattern, page_text, re.I) for pattern in reaction_signatures):
            strong_hits.add(index)
        recipe_score = sum(bool(re.search(pattern, page_text, re.I)) for pattern in recipe_markers)
        yield_mentions = len(re.findall(r'\byield(?:ed|s)?\b', page_text, re.I))
        if recipe_score >= 3 or (index > 0 and yield_mentions >= 2):
            strong_hits.add(index)
        for line in lines:
            lowered = line.lower()
            matched = [keyword for keyword in keywords if keyword in lowered]
            if not matched:
                continue
            fallback_hits.add(index)
            if (index > 0 and len(line) <= 180 and any(' ' in keyword for keyword in matched)) or (
                len(line) <= 120 and re.match(r'^\d+(?:\.\d+)*\.?\s+', line)
            ):
                strong_hits.add(index)

    hits = {index for index in (strong_hits or fallback_hits) if index < references_page}
    textful_pages = sum(len(text) >= 200 for text in normalized_page_texts)
    spectra_caption_pages = sum(
        bool(re.search(r'\b(?:nmr|hrms|ir|mass)\s+spectrum\s+of\s+compound\b', text, re.I))
        for text in normalized_page_texts
    )
    if textful_pages <= 1 and spectra_caption_pages < max(2, page_count // 3):
        hits = set(range(references_page))

    if not hits:
        return list(range(references_page or page_count))
    expanded = set()
    for index in hits:
        start = max(0, index - context_pages)
        end = min(references_page, index + context_pages + 1)
        expanded.update(range(start, end))
    return sorted(expanded)


def select_keyword_pages(pdf_path, keywords=None, context_pages=None):
    document = fitz.open(pdf_path)
    try:
        page_texts = [document[index].get_text('text') for index in range(document.page_count)]
    finally:
        document.close()
    return len(page_texts), select_keyword_pages_from_text(page_texts, keywords, context_pages)


def chunk_page_numbers(page_numbers, max_pages=None):
    max_pages = max_pages or settings.AI_PDF_CHUNK_PAGES
    return [page_numbers[index:index + max_pages] for index in range(0, len(page_numbers), max_pages)]


ADAPTIVE_SECTION_START_PATTERN = re.compile(
    r'(?im)^\s*(?:\d+(?:\.\d+){1,4}\.?\s+)?'
    r'(?:(?:general|representative)\s+)?'
    r'(?:synthesis|preparation|experimental|reaction\s+scope|substrate\s+scope|'
    r'optimization|synthetic\s+route)\b'
)


def adaptive_chunk_page_numbers(
    page_numbers,
    page_texts,
    *,
    visual_page_candidates=None,
    max_pages=None,
    single_call_max_pages=None,
    single_call_max_chars=None,
    chunk_max_chars=None,
    overlap_pages=None,
):
    """Group selected pages by continuity, size, and clear reaction-section starts."""
    pages = sorted({int(page) for page in page_numbers})
    if not pages:
        return []
    if not settings.AI_ADAPTIVE_CHUNKING:
        return chunk_page_numbers(pages, max_pages=max_pages)

    max_pages = max(1, max_pages or settings.AI_PDF_CHUNK_PAGES)
    single_call_max_pages = max(
        1,
        single_call_max_pages or settings.AI_SINGLE_CALL_MAX_PAGES,
    )
    single_call_max_chars = max(
        1000,
        single_call_max_chars or settings.AI_SINGLE_CALL_MAX_CHARS,
    )
    chunk_max_chars = max(1000, chunk_max_chars or settings.AI_CHUNK_MAX_CHARS)
    overlap_pages = settings.AI_CHUNK_OVERLAP_PAGES if overlap_pages is None else overlap_pages
    overlap_pages = max(0, min(2, int(overlap_pages)))
    chunk_page_limit = min(max_pages, single_call_max_pages)
    selected_visual_pages = set(visual_page_candidates or []).intersection(pages)
    reaction_dense = len(selected_visual_pages) >= 2

    if reaction_dense:
        dense_page_limit = max(1, settings.AI_REACTION_DENSE_CHUNK_PAGES)
        # Dense visual pages generate much larger structured responses. Divide
        # them without overlap so independent chunks can run concurrently.
        if len(pages) > dense_page_limit:
            return [
                pages[index:index + dense_page_limit]
                for index in range(0, len(pages), dense_page_limit)
            ]

    def page_length(page):
        return len(page_texts[page]) if 0 <= page < len(page_texts) else 0

    is_contiguous = all(right == left + 1 for left, right in zip(pages, pages[1:]))
    total_chars = sum(page_length(page) for page in pages)
    if (
        is_contiguous
        and len(pages) <= min(max_pages, single_call_max_pages)
        and total_chars <= single_call_max_chars
    ):
        return [pages]

    continuous_runs = []
    current_run = []
    for page in pages:
        if current_run and page != current_run[-1] + 1:
            continuous_runs.append(current_run)
            current_run = []
        current_run.append(page)
    if current_run:
        continuous_runs.append(current_run)

    chunks = []
    for run in continuous_runs:
        current = []
        current_chars = 0
        for page in run:
            text = page_texts[page] if 0 <= page < len(page_texts) else ''
            page_chars = len(text)
            starts_section = bool(ADAPTIVE_SECTION_START_PATTERN.search(text[:1600]))
            exceeds_limit = current and (
                len(current) >= chunk_page_limit
                or current_chars + page_chars > chunk_max_chars
            )
            section_boundary = current and len(current) >= 2 and starts_section
            if exceeds_limit or section_boundary:
                chunks.append(current)
                overlap = (
                    current[-overlap_pages:]
                    if overlap_pages and exceeds_limit and not section_boundary
                    else []
                )
                current = list(overlap)
                current_chars = sum(page_length(item) for item in current)
            current.append(page)
            current_chars += page_chars
        if current:
            chunks.append(current)
    return chunks


def build_pdf_chunk(pdf_path, page_numbers):
    source = fitz.open(pdf_path)
    chunk = fitz.open()
    try:
        for page_index in page_numbers:
            chunk.insert_pdf(source, from_page=page_index, to_page=page_index)
        return chunk.tobytes(garbage=4, deflate=True)
    finally:
        chunk.close()
        source.close()


def _expanded_clip(page, rectangle, horizontal_margin=16, vertical_margin=24):
    clip = fitz.Rect(
        rectangle.x0 - horizontal_margin,
        rectangle.y0 - vertical_margin,
        rectangle.x1 + horizontal_margin,
        rectangle.y1 + vertical_margin,
    )
    return clip & page.rect


def _reaction_scheme_rectangles(page):
    """Locate likely reaction figures without sending the complete PDF page."""
    page_area = max(1, page.rect.width * page.rect.height)
    rectangles = []
    for image in page.get_images(full=True):
        for rectangle in page.get_image_rects(image[0]):
            width_ratio = rectangle.width / max(1, page.rect.width)
            height_ratio = rectangle.height / max(1, page.rect.height)
            area_ratio = (rectangle.width * rectangle.height) / page_area
            if width_ratio >= 0.25 and height_ratio >= 0.05 and area_ratio >= 0.015:
                rectangles.append(_expanded_clip(page, rectangle))
    if rectangles:
        return rectangles

    # Vector-only schemes may have no embedded raster image. Crop a bounded
    # region immediately above a short Scheme caption rather than the full page.
    for block in page.get_text('blocks', sort=True):
        block_text = ' '.join(str(block[4] or '').split())
        if len(block_text) > 240 or not re.match(r'(?i)^scheme\s+\d+[a-z]?\b', block_text):
            continue
        caption = fitz.Rect(block[:4])
        rectangles.append(fitz.Rect(
            page.rect.x0 + page.rect.width * 0.03,
            max(page.rect.y0, caption.y0 - page.rect.height * 0.38),
            page.rect.x1 - page.rect.width * 0.03,
            min(page.rect.y1, caption.y1 + 30),
        ))
    return rectangles


def build_reaction_scheme_crops(pdf_path, page_numbers):
    """Render only reaction-scheme regions and retain original-page mapping."""
    document = fitz.open(pdf_path)
    crops = []
    try:
        for page_index in page_numbers:
            page = document[page_index]
            for region_number, clip in enumerate(_reaction_scheme_rectangles(page), start=1):
                scale = min(
                    2.5,
                    1600 / max(1, clip.width),
                    1600 / max(1, clip.height),
                )
                pixmap = page.get_pixmap(
                    matrix=fitz.Matrix(max(1.5, scale), max(1.5, scale)),
                    clip=clip,
                    alpha=False,
                    annots=False,
                )
                crops.append({
                    'page_index': page_index,
                    'region_number': region_number,
                    'bbox': {
                        'left': clip.x0 / page.rect.width,
                        'top': clip.y0 / page.rect.height,
                        'right': clip.x1 / page.rect.width,
                        'bottom': clip.y1 / page.rect.height,
                    },
                    'png_bytes': pixmap.tobytes('png'),
                })
    finally:
        document.close()
    return crops


TABLE_CAPTION_PATTERN = re.compile(r'^\s*table\s+s?\d+[.:\s]', re.I)
VISUAL_CONTENT_PATTERN = re.compile(
    r'\b(?:scheme\s+\d+|reaction\s+scheme|reaction\s+scope|substrate\s+scope|graphical\s+abstract|reagents?\s+and\s+conditions)\b',
    re.I,
)


def extract_column_aware_text(page):
    blocks = []
    for block in page.get_text('blocks'):
        if len(block) < 7 or block[6] != 0:
            continue
        text = '\n'.join(line.strip() for line in str(block[4]).splitlines() if line.strip())
        if text:
            blocks.append({
                'rect': fitz.Rect(block[:4]),
                'text': text,
            })
    if not blocks:
        return ''

    page_width = page.rect.width
    midpoint = page.rect.x0 + (page_width / 2)
    spanning = []
    column_blocks = []
    for block in blocks:
        rect = block['rect']
        crosses_gutter = rect.x0 < midpoint - (page_width * 0.12) and rect.x1 > midpoint + (page_width * 0.12)
        if rect.width >= page_width * 0.68 or crosses_gutter:
            spanning.append(block)
        else:
            column_blocks.append(block)

    left_chars = sum(len(block['text']) for block in column_blocks if block['rect'].x0 < midpoint)
    right_chars = sum(len(block['text']) for block in column_blocks if block['rect'].x0 >= midpoint)
    uses_columns = left_chars >= 100 and right_chars >= 100
    if not uses_columns:
        return '\n'.join(
            block['text'] for block in sorted(blocks, key=lambda item: (item['rect'].y0, item['rect'].x0))
        )

    ordered = []
    remaining = set(range(len(column_blocks)))
    vertical_cursor = page.rect.y0 - 1
    for separator in sorted(spanning, key=lambda item: (item['rect'].y0, item['rect'].x0)):
        band_indices = [
            index for index in remaining
            if vertical_cursor < column_blocks[index]['rect'].y0 < separator['rect'].y0
        ]
        for side in ('left', 'right'):
            side_blocks = [
                column_blocks[index] for index in band_indices
                if (column_blocks[index]['rect'].x0 < midpoint) == (side == 'left')
            ]
            ordered.extend(sorted(side_blocks, key=lambda item: (item['rect'].y0, item['rect'].x0)))
        remaining.difference_update(band_indices)
        ordered.append(separator)
        vertical_cursor = max(vertical_cursor, separator['rect'].y1)

    for side in ('left', 'right'):
        side_blocks = [
            column_blocks[index] for index in remaining
            if (column_blocks[index]['rect'].x0 < midpoint) == (side == 'left')
        ]
        ordered.extend(sorted(side_blocks, key=lambda item: (item['rect'].y0, item['rect'].x0)))
    return '\n'.join(block['text'] for block in ordered)


def _has_table_caption(text):
    return any(
        len(line.strip()) <= 180 and TABLE_CAPTION_PATTERN.search(line)
        for line in str(text or '').splitlines()
    )


def extract_native_tables(page, page_text=''):
    if not _has_table_caption(page_text):
        return []
    tables = []
    for table in page.find_tables().tables:
        rows = []
        for row in table.extract():
            cleaned = [' '.join(str(cell or '').split()) for cell in row]
            if any(cleaned):
                rows.append(cleaned)
        if len(rows) >= 2 and max((len(row) for row in rows), default=0) >= 2:
            tables.append(rows)
    return tables


def _table_as_text(table, table_number):
    width = max(len(row) for row in table)
    lines = [f'[DETECTED TABLE {table_number}]']
    for row_number, row in enumerate(table, start=1):
        cells = row + [''] * (width - len(row))
        lines.append(f'Row {row_number}: ' + ' | '.join(cells))
    return '\n'.join(lines)


EXTRACTED_TEXT_PAGE_SEPARATOR = '\n\n<<< REACTXTRACT PAGE BREAK >>>\n\n'


def extract_pdf_text_pages(pdf_path, source_name):
    """Extract every PDF page once into durable, chunk-ready text sections."""
    document = fitz.open(pdf_path)
    page_texts = []
    page_sections = []
    visual_pages = []
    try:
        for page_index in range(document.page_count):
            page = document[page_index]
            text = extract_column_aware_text(page)
            tables = extract_native_tables(page, text)
            compact_length = len(''.join(text.split()))
            has_images = bool(page.get_images(full=True))
            needs_vision = (
                settings.AI_INPUT_MODE == 'vision'
                or (
                    settings.AI_INPUT_MODE == 'hybrid'
                    and (
                        bool(VISUAL_CONTENT_PATTERN.search(text))
                        or (_has_table_caption(text) and not tables)
                        or (compact_length < 300 and has_images)
                    )
                )
            )
            if needs_vision:
                visual_pages.append(page_index)
            section = [
                f'=== SOURCE FILE: {source_name} | ORIGINAL PAGE: {page_index + 1} ===',
                '[NATIVE TEXT — COLUMN-AWARE READING ORDER]',
                text or '[No usable native text on this page.]',
            ]
            section.extend(_table_as_text(table, number) for number, table in enumerate(tables, start=1))
            page_texts.append(text)
            page_sections.append('\n'.join(section))
    finally:
        document.close()
    if settings.AI_INPUT_MODE == 'text':
        visual_pages = []
    return page_texts, page_sections, visual_pages


def serialize_extracted_text_pages(page_sections):
    return EXTRACTED_TEXT_PAGE_SEPARATOR.join(page_sections)


def load_extracted_text_pages(extracted_text_file):
    extracted_text_file.open('rb')
    try:
        contents = extracted_text_file.read().decode('utf-8')
    finally:
        extracted_text_file.close()
    return contents.split(EXTRACTED_TEXT_PAGE_SEPARATOR) if contents else []


def build_native_page_context(pdf_path, page_numbers, source_name):
    document = fitz.open(pdf_path)
    sections = []
    visual_pages = []
    try:
        for page_index in page_numbers:
            page = document[page_index]
            text = extract_column_aware_text(page)
            tables = extract_native_tables(page, text)
            compact_length = len(''.join(text.split()))
            has_images = bool(page.get_images(full=True))
            needs_vision = (
                settings.AI_INPUT_MODE == 'vision'
                or (
                    settings.AI_INPUT_MODE == 'hybrid'
                    and (
                        bool(VISUAL_CONTENT_PATTERN.search(text))
                        or (_has_table_caption(text) and not tables)
                        or (compact_length < 300 and has_images)
                    )
                )
            )
            if needs_vision:
                visual_pages.append(page_index)
            section = [
                f'=== SOURCE FILE: {source_name} | ORIGINAL PAGE: {page_index + 1} ===',
                '[NATIVE TEXT — COLUMN-AWARE READING ORDER]',
                text or '[No usable native text on this page.]',
            ]
            section.extend(_table_as_text(table, number) for number, table in enumerate(tables, start=1))
            sections.append('\n'.join(section))
        if settings.AI_INPUT_MODE == 'text':
            visual_pages = []
        return '\n\n'.join(sections), visual_pages
    finally:
        document.close()


def _client_and_model():
    from openai import AzureOpenAI, OpenAI

    azure_endpoint = os.environ.get('AZURE_OPENAI_ENDPOINT', '').strip()
    if azure_endpoint:
        required = ['AZURE_OPENAI_API_KEY', 'AZURE_OPENAI_DEPLOYMENT']
        missing = [name for name in required if not os.environ.get(name, '').strip()]
        if missing:
            raise RuntimeError(f'Missing Azure OpenAI settings: {", ".join(missing)}')
        return AzureOpenAI(
            api_key=os.environ['AZURE_OPENAI_API_KEY'],
            api_version=os.environ.get('AZURE_OPENAI_RESPONSES_API_VERSION', '2025-03-01-preview'),
            azure_endpoint=azure_endpoint,
            timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
            # Retries are handled locally so every attempt can be audited.
            max_retries=0,
        ), os.environ['AZURE_OPENAI_DEPLOYMENT']

    if not os.environ.get('OPENAI_API_KEY', '').strip():
        raise RuntimeError('Set OPENAI_API_KEY or the Azure OpenAI settings in .env.')
    model = os.environ.get('OPENAI_MODEL') or os.environ.get('MODEL_NAME') or 'gpt-4.1'
    return OpenAI(
        api_key=os.environ['OPENAI_API_KEY'],
        timeout=settings.AI_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ), model


def _estimated_cost(prompt_tokens, completion_tokens):
    value = (
        Decimal(prompt_tokens) * settings.AI_INPUT_COST_PER_MILLION
        + Decimal(completion_tokens) * settings.AI_OUTPUT_COST_PER_MILLION
    ) / Decimal(1_000_000)
    return value.quantize(Decimal('0.000001'), rounding=ROUND_HALF_UP)


def _usage_reasoning_tokens(usage):
    details = getattr(usage, 'output_tokens_details', None)
    if isinstance(details, dict):
        return int(details.get('reasoning_tokens', 0) or 0)
    return int(getattr(details, 'reasoning_tokens', 0) or 0)


def _save_usage(
    response,
    *,
    job,
    document,
    phase,
    chunk_number,
    model,
    duration_ms=0,
    attempt_number=1,
):
    usage = getattr(response, 'usage', None)
    prompt_tokens = int(getattr(usage, 'input_tokens', 0) or 0)
    completion_tokens = int(getattr(usage, 'output_tokens', 0) or 0)
    total_tokens = int(getattr(usage, 'total_tokens', prompt_tokens + completion_tokens) or 0)
    AITokenUsage.objects.create(
        job=job,
        document=document,
        phase=phase,
        chunk_number=chunk_number,
        model_name=model,
        attempt_number=attempt_number,
        status=AITokenUsage.Status.COMPLETED,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        reasoning_tokens=_usage_reasoning_tokens(usage),
        total_tokens=total_tokens,
        estimated_cost_usd=_estimated_cost(prompt_tokens, completion_tokens),
        duration_ms=max(0, int(duration_ms or 0)),
    )


def _save_failed_attempt(
    error,
    *,
    job,
    document,
    phase,
    chunk_number,
    model,
    duration_ms,
    attempt_number,
):
    is_timeout = 'timeout' in type(error).__name__.casefold()
    AITokenUsage.objects.create(
        job=job,
        document=document,
        phase=phase,
        chunk_number=chunk_number,
        model_name=model,
        attempt_number=attempt_number,
        status=AITokenUsage.Status.TIMEOUT if is_timeout else AITokenUsage.Status.FAILED,
        error_type=type(error).__name__[:120],
        error_message=str(error)[:2000],
        duration_ms=max(0, int(duration_ms or 0)),
    )


def _response_json(response):
    status = str(getattr(response, 'status', 'completed') or 'completed')
    if status not in {'completed', 'ResponseStatus.COMPLETED'}:
        error = getattr(response, 'error', None) or getattr(response, 'incomplete_details', None)
        raise RuntimeError(f'AI response ended with status {status}: {error or "no details"}')
    output_text = getattr(response, 'output_text', '')
    if not output_text:
        raise RuntimeError('AI response contained no structured output.')
    return json.loads(output_text)


def _reasoning_options(model):
    effort = settings.AI_REASONING_EFFORT
    if not effort or effort not in {'none', 'minimal', 'low', 'medium', 'high', 'xhigh'}:
        return {}
    # Do not send reasoning options to models known not to support them. Azure
    # deployment names that contain the underlying GPT-5/o-series name work too.
    normalized_model = str(model or '').lower().replace('_', '-')
    if not re.search(r'(^|-)gpt-?5(?:[.-]|$)|(^|-)o[134](?:[.-]|$)', normalized_model):
        return {}
    # GPT-5.5 deployments reject "minimal" and expose "none" as their
    # lowest-latency reasoning level. Keep older environment files compatible.
    if effort == 'minimal' and re.search(r'(^|-)gpt-?5[.-]5(?:[.-]|$)', normalized_model):
        effort = 'none'
    return {'reasoning': {'effort': effort}}


def _create_structured_response(client, model, content, *, instructions, schema, schema_name):
    started = time.perf_counter()
    response = client.responses.create(
        model=model,
        instructions=instructions,
        input=[{'role': 'user', 'content': content}],
        text={
            'format': {
                'type': 'json_schema',
                'name': schema_name,
                'strict': True,
                'schema': schema,
            },
        },
        **_reasoning_options(model),
    )
    return response, round((time.perf_counter() - started) * 1000)


def _retryable_ai_error(error):
    error_name = type(error).__name__.casefold()
    status_code = int(getattr(error, 'status_code', 0) or 0)
    return (
        'timeout' in error_name
        or 'connection' in error_name
        or 'ratelimit' in error_name
        or status_code == 429
        or status_code >= 500
    )


def _create_structured_response_with_retries(
    client,
    model,
    content,
    *,
    instructions,
    schema,
    schema_name,
):
    attempts = []
    for attempt_number in range(1, settings.AI_MAX_RETRIES + 2):
        started = time.perf_counter()
        try:
            response, duration_ms = _create_structured_response(
                client,
                model,
                content,
                instructions=instructions,
                schema=schema,
                schema_name=schema_name,
            )
        except Exception as error:
            duration_ms = round((time.perf_counter() - started) * 1000)
            attempts.append({
                'attempt_number': attempt_number,
                'duration_ms': duration_ms,
                'error': error,
            })
            if attempt_number > settings.AI_MAX_RETRIES or not _retryable_ai_error(error):
                return None, attempts, error
            continue
        attempts.append({
            'attempt_number': attempt_number,
            'duration_ms': duration_ms,
            'response': response,
        })
        return response, attempts, None
    return None, attempts, RuntimeError('AI request did not produce a response.')


def _record_ai_attempts(attempts, *, job, document, phase, chunk_number, model):
    for attempt in attempts:
        if attempt.get('response') is not None:
            _save_usage(
                attempt['response'],
                job=job,
                document=document,
                phase=phase,
                chunk_number=chunk_number,
                model=model,
                duration_ms=attempt['duration_ms'],
                attempt_number=attempt['attempt_number'],
            )
        else:
            _save_failed_attempt(
                attempt['error'],
                job=job,
                document=document,
                phase=phase,
                chunk_number=chunk_number,
                model=model,
                duration_ms=attempt['duration_ms'],
                attempt_number=attempt['attempt_number'],
            )


def _call_responses(client, model, content, *, job, document=None, phase, chunk_number=1):
    response, attempts, error = _create_structured_response_with_retries(
        client,
        model,
        content,
        instructions=get_extraction_instructions(),
        schema=REACTION_SCHEMA,
        schema_name='chemical_reaction_extraction',
    )
    _record_ai_attempts(
        attempts,
        job=job,
        document=document,
        phase=phase,
        chunk_number=chunk_number,
        model=model,
    )
    if error:
        raise error
    return _response_json(response)


def extract_document_reactions(job, document, client, model):
    page_texts, page_sections, visual_page_candidates = extract_pdf_text_pages(
        document.file.path,
        document.original_name,
    )
    page_count = len(page_texts)
    selected_pages = select_keyword_pages_from_text(page_texts)
    text_filename = f'{os.path.splitext(document.original_name)[0]}.txt'
    if document.extracted_text_file:
        document.extracted_text_file.delete(save=False)
    document.extracted_text_file.save(
        text_filename,
        ContentFile(serialize_extracted_text_pages(page_sections).encode('utf-8')),
        save=False,
    )
    document.page_count = page_count
    document.file_size = document.file.size
    document.selected_pages = [page + 1 for page in selected_pages]
    document.save(update_fields=['extracted_text_file', 'page_count', 'file_size', 'selected_pages'])

    # Reload the durable UTF-8 artifact so AI chunks use the generated text file,
    # rather than extracting the PDF again for each chunk.
    stored_page_sections = load_extracted_text_pages(document.extracted_text_file)
    visual_page_candidates = set(visual_page_candidates)

    candidates = []
    chunks = adaptive_chunk_page_numbers(
        selected_pages,
        page_texts,
        visual_page_candidates=visual_page_candidates,
    )
    document._extraction_chunk_count = len(chunks)
    chunk_requests = []
    for chunk_number, page_numbers in enumerate(chunks, start=1):
        _raise_if_discard_requested(job)
        native_context = '\n\n'.join(stored_page_sections[page] for page in page_numbers)
        visual_pages = [page for page in page_numbers if page in visual_page_candidates]
        content = []
        visual_crops = build_reaction_scheme_crops(document.file.path, visual_pages)
        for crop_number, crop in enumerate(visual_crops, start=1):
            bbox = crop['bbox']
            content.append({
                'type': 'input_text',
                'text': (
                    f'VISUAL CROP {crop_number}: original page {crop["page_index"] + 1}, '
                    f'original normalized bbox '
                    f'({bbox["left"]:.5f}, {bbox["top"]:.5f}, '
                    f'{bbox["right"]:.5f}, {bbox["bottom"]:.5f}). '
                    'Interpret this crop only as visual evidence for that original page. '
                    'Convert crop-relative locations back to original-page normalized bbox coordinates.'
                ),
            })
            content.append({
                'type': 'input_image',
                'image_url': 'data:image/png;base64,' + base64.b64encode(crop['png_bytes']).decode('ascii'),
            })
        visual_mapping = ', '.join(
            f'crop {position} = original page {crop["page_index"] + 1}'
            for position, crop in enumerate(visual_crops, start=1)
        ) or 'No visual crops attached; use the native source text and detected tables.'
        content.append({
            'type': 'input_text',
            'text': (
                f'SOURCE FILE: {document.original_name}\n'
                f'SOURCE CHUNK: {chunk_number} of {len(chunks)}\n'
                f'VISUAL PAGE MAP: {visual_mapping}\n\n'
                f'{native_context}\n\n'
                'Extract every distinct reaction supported by these source pages and return field-level confidence and evidence.'
            ),
        })
        chunk_requests.append((chunk_number, content))

    results = {}
    max_workers = min(settings.AI_MAX_PARALLEL_REQUESTS, len(chunk_requests))
    if max_workers <= 1:
        for chunk_number, content in chunk_requests:
            results[chunk_number] = _call_responses(
                client,
                model,
                content,
                job=job,
                document=document,
                phase=AITokenUsage.Phase.EXTRACTION,
                chunk_number=chunk_number,
            )
            _raise_if_discard_requested(job)
    else:
        instructions = get_extraction_instructions()
        with ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix='reactxtract-ai') as executor:
            future_chunks = {
                executor.submit(
                    _create_structured_response_with_retries,
                    client,
                    model,
                    content,
                    instructions=instructions,
                    schema=REACTION_SCHEMA,
                    schema_name='chemical_reaction_extraction',
                ): chunk_number
                for chunk_number, content in chunk_requests
            }
            for future in as_completed(future_chunks):
                chunk_number = future_chunks[future]
                response, attempts, error = future.result()
                _record_ai_attempts(
                    attempts,
                    job=job,
                    document=document,
                    phase=AITokenUsage.Phase.EXTRACTION,
                    chunk_number=chunk_number,
                    model=model,
                )
                if error:
                    raise error
                results[chunk_number] = _response_json(response)
                _raise_if_discard_requested(job)

    for chunk_number in sorted(results):
        result = results[chunk_number]
        for reaction in result.get('reactions', []):
            prepared = _prepare_extracted_reaction(reaction)
            candidates.extend(_separate_product_candidates(prepared))
    return candidates


def _normalize_text(value):
    text = unicodedata.normalize('NFKC', str(value or '')).casefold()
    text = re.sub(r'[\u2010-\u2015]', '-', text)
    text = re.sub(r'\s+', ' ', text).strip(' .;,')
    return '' if text in MISSING_VALUES else text


def _field_values(candidate, field):
    value = candidate.get(field, [] if field in LIST_FIELDS else '')
    values = value if isinstance(value, list) else [value]
    return tuple(sorted({_normalize_text(item) for item in values if _normalize_text(item)}))


def _reaction_ids(candidate):
    identifiers = set()
    for product in candidate.get('products', []):
        normalized = _normalize_text(product)
        patterns = (
            r'\b(?:compound|product|intermediate)\s+([a-z][a-z0-9-]*-\d+[a-z0-9-]*|\d+[a-z]?)\b',
            r'\(([a-z]*-?\d+[a-z][a-z0-9-]*)\)\s*$',
            r'^([a-z]*-?\d+[a-z][a-z0-9-]*)$',
        )
        for pattern in patterns:
            identifiers.update(re.findall(pattern, normalized, re.I))
    return frozenset(identifiers)


def _source_locations(candidate):
    locations = set()
    for metadata in candidate.get('field_metadata', {}).values():
        source_file = _normalize_text(metadata.get('source_file'))
        page = _normalize_text(metadata.get('page'))
        if source_file and page:
            locations.add((source_file, page))
    return frozenset(locations)


def _reported_field_matches(left, right):
    matches = 0
    conflicts = 0
    for field in REACTION_FIELDS:
        left_values = _field_values(left, field)
        right_values = _field_values(right, field)
        if not left_values or not right_values:
            continue
        if left_values == right_values:
            matches += 1
        else:
            conflicts += 1
    return matches, conflicts


def _is_exact_duplicate(left, right):
    left_fields = tuple(_field_values(left, field) for field in REACTION_FIELDS)
    right_fields = tuple(_field_values(right, field) for field in REACTION_FIELDS)
    # Identical generic conditions are not enough: separate scope examples can
    # legitimately share every condition while differing only in an omitted product.
    if left_fields[0] and left_fields == right_fields:
        return True

    same_products = bool(_field_values(left, 'products')) and (
        _field_values(left, 'products') == _field_values(right, 'products')
    )
    same_ids = bool(_reaction_ids(left) & _reaction_ids(right))
    same_location = bool(_source_locations(left) & _source_locations(right))
    matches, conflicts = _reported_field_matches(left, right)

    # A product on the same cited source page is the same extracted record unless
    # its reported reaction details conflict. Across files/pages, require a strong
    # compound identifier plus corroborating normalized field values.
    if same_products and same_location and conflicts == 0:
        return True
    return same_ids and matches >= 3 and conflicts == 0


def _is_ambiguous_duplicate(left, right):
    same_products = bool(_field_values(left, 'products')) and (
        _field_values(left, 'products') == _field_values(right, 'products')
    )
    same_ids = bool(_reaction_ids(left) & _reaction_ids(right))
    same_location = bool(_source_locations(left) & _source_locations(right))
    matches, conflicts = _reported_field_matches(left, right)
    return same_products or same_ids or (same_location and matches >= 2 and conflicts <= 2)


def _metadata_score(metadata):
    try:
        confidence = float(metadata.get('confidence', 0) or 0)
    except (TypeError, ValueError):
        confidence = 0
    evidence = sum(bool(_normalize_text(metadata.get(key))) for key in ('source_file', 'page', 'quote'))
    bbox = metadata.get('bbox') or {}
    has_bbox = any(float(bbox.get(key, 0) or 0) for key in ('left', 'top', 'right', 'bottom'))
    return confidence, evidence, has_bbox


def _merge_original_candidates(candidates):
    """Select complete field/evidence pairs from originals; never synthesize metadata."""
    merged = {}
    merged_metadata = {}
    for field in REACTION_FIELDS:
        choices = []
        for position, candidate in enumerate(candidates):
            values = _field_values(candidate, field)
            metadata = candidate.get('field_metadata', {}).get(field, {})
            choices.append((bool(values), _metadata_score(metadata), -position, candidate.get(field), metadata))
        _, _, _, value, metadata = max(choices, key=lambda choice: choice[:3])
        merged[field] = value
        # Copy the selected original metadata without allowing AI decisions to alter it.
        merged_metadata[field] = json.loads(json.dumps(metadata))
    merged['field_metadata'] = merged_metadata
    stage_candidate = max(
        enumerate(candidates),
        key=lambda item: (
            len(item[1].get('stage_details') or []),
            _metadata_score((item[1].get('field_metadata') or {}).get('reaction_stages') or {}),
            -item[0],
        ),
    )[1]
    merged['stage_details'] = json.loads(json.dumps(stage_candidate.get('stage_details') or []))
    return merged


def _candidate_summary(index, candidate):
    return {
        'candidate_id': index,
        'reaction_ids': sorted(_reaction_ids(candidate)),
        'source_locations': [list(location) for location in sorted(_source_locations(candidate))],
        'fields': {field: candidate.get(field) for field in REACTION_FIELDS},
        'stage_details': candidate.get('stage_details') or [],
    }


def _call_duplicate_resolution(client, model, pairs, *, job, batch_number):
    content = [{
        'type': 'input_text',
        'text': 'AMBIGUOUS DUPLICATE PAIRS:\n' + json.dumps({'pairs': pairs}, ensure_ascii=False),
    }]
    response, attempts, error = _create_structured_response_with_retries(
        client,
        model,
        content,
        instructions=DUPLICATE_DECISION_INSTRUCTIONS,
        schema=DUPLICATE_DECISION_SCHEMA,
        schema_name='reaction_duplicate_decisions',
    )
    _record_ai_attempts(
        attempts,
        job=job,
        document=None,
        phase=AITokenUsage.Phase.CONSOLIDATION,
        chunk_number=batch_number,
        model=model,
    )
    if error:
        raise error
    return _response_json(response)


def consolidate_reactions(job, candidates, client, model):
    if len(candidates) <= 1:
        return candidates

    parents = list(range(len(candidates)))

    def find(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    def union(left, right):
        left_root, right_root = find(left), find(right)
        if left_root != right_root:
            parents[right_root] = left_root

    ambiguous = []
    pair_id = 1
    for left_index in range(len(candidates)):
        for right_index in range(left_index + 1, len(candidates)):
            left, right = candidates[left_index], candidates[right_index]
            if _is_exact_duplicate(left, right):
                union(left_index, right_index)
            elif _is_ambiguous_duplicate(left, right):
                ambiguous.append({
                    'pair_id': pair_id,
                    'left_index': left_index,
                    'right_index': right_index,
                    'left': _candidate_summary(left_index, left),
                    'right': _candidate_summary(right_index, right),
                })
                pair_id += 1

    ambiguous = [
        pair for pair in ambiguous
        if find(pair['left_index']) != find(pair['right_index'])
    ]

    # Only unresolved likely duplicates are sent to AI, in a compact decision-only form.
    for batch_number, start in enumerate(range(0, len(ambiguous), AI_DUPLICATE_BATCH_SIZE), start=1):
        _raise_if_discard_requested(job)
        batch = ambiguous[start:start + AI_DUPLICATE_BATCH_SIZE]
        ai_pairs = [
            {'pair_id': item['pair_id'], 'left': item['left'], 'right': item['right']}
            for item in batch
        ]
        result = _call_duplicate_resolution(client, model, ai_pairs, job=job, batch_number=batch_number)
        _raise_if_discard_requested(job)
        pair_lookup = {item['pair_id']: item for item in batch}
        for decision in result.get('decisions', []):
            pair = pair_lookup.get(decision.get('pair_id'))
            try:
                confidence = Decimal(str(decision.get('confidence', 0)))
            except Exception:
                confidence = Decimal('0')
            if pair and decision.get('is_duplicate') is True and confidence >= AI_DUPLICATE_CONFIDENCE_THRESHOLD:
                union(pair['left_index'], pair['right_index'])

    groups = {}
    for index, candidate in enumerate(candidates):
        groups.setdefault(find(index), []).append(candidate)
    return [_merge_original_candidates(group) for group in groups.values()]


def run_extraction(job):
    _raise_if_discard_requested(job)
    client, model = _client_and_model()
    job.model_name = model
    job.save(update_fields=['model_name'])
    candidates = []
    documents = list(job.documents.all())
    for document in documents:
        candidates.extend(extract_document_reactions(job, document, client, model))
        _raise_if_discard_requested(job)
    source_chunk_count = sum(
        getattr(document, '_extraction_chunk_count', len(chunk_page_numbers(document.selected_pages)))
        for document in documents
    )
    if source_chunk_count <= 1:
        return candidates
    return consolidate_reactions(job, candidates, client, model)

