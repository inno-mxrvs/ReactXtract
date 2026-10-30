import csv
import json
import re
import time
from datetime import timedelta
from pathlib import Path

import fitz
from django.contrib import messages
from django.core import signing
from django.db import transaction
from django.db.models import Q, Sum
from django.http import FileResponse, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from .lookups import (
    normalize_reagent_catalyst_values,
    normalize_solvent_values,
    reaction_lookup_metadata,
)
from .models import ExtractionJob, Reaction, SourceDocument
from .services import ExtractionDiscarded, run_extraction


ALLOWED_EXTENSIONS = {'.pdf'}
# Source PDFs are reduced to page chunks before being sent to the API, so the
# original local upload may exceed the API's per-request file limit.
MAX_FILE_SIZE = 250 * 1024 * 1024
REACTION_FIELDS = [
    'products', 'starting_materials', 'reagents', 'catalysts', 'solvents',
    'reaction_time', 'reaction_pressure', 'reaction_temperature',
    'other_conditions', 'reaction_stages', 'reaction_description_type', 'yield',
]
DRAFT_SIGNING_SALT = 'reactxtract.reaction-draft.v1'


def home(request):
    _discard_abandoned_jobs()
    recent_jobs = ExtractionJob.objects.exclude(
        status__in=[ExtractionJob.Status.DRAFT, ExtractionJob.Status.PROCESSING],
    )[:6]
    return render(request, 'index.html', {'recent_jobs': recent_jobs})


def _discard_job(job):
    documents = list(job.documents.all())
    for document in documents:
        if document.file:
            document.file.delete(save=False)
        if document.extracted_text_file:
            document.extracted_text_file.delete(save=False)
    job.delete()


def _discard_abandoned_jobs():
    for job in ExtractionJob.objects.filter(status=ExtractionJob.Status.DRAFT).prefetch_related('documents'):
        _discard_job(job)
    processing = ExtractionJob.objects.filter(status=ExtractionJob.Status.PROCESSING)
    processing.update(discard_requested=True)
    stale_before = timezone.now() - timedelta(hours=1)
    for job in processing.filter(created_at__lt=stale_before).prefetch_related('documents'):
        _discard_job(job)


def _validate_uploads(files):
    if not files:
        return 'Choose at least one PDF.'
    for uploaded in files:
        if Path(uploaded.name).suffix.lower() not in ALLOWED_EXTENSIONS:
            return f'{uploaded.name}: only PDF files are supported.'
        if uploaded.size > MAX_FILE_SIZE:
            return f'{uploaded.name}: source PDFs must be 250 MB or smaller.'
    return ''


def _prepare_draft_reactions(reaction_data):
    reactions = []
    for index, item in enumerate(reaction_data, start=1):
        metadata = item.get('field_metadata') or {}
        confidence_scores = {
            field: float((metadata.get(field) or {}).get('confidence') or 0)
            for field in REACTION_FIELDS
        }
        field_evidence = {
            field: {
                'source_file': str((metadata.get(field) or {}).get('source_file') or ''),
                'page': str((metadata.get(field) or {}).get('page') or ''),
                'quote': str((metadata.get(field) or {}).get('quote') or ''),
                'bbox': (metadata.get(field) or {}).get('bbox') or {
                    'left': 0, 'top': 0, 'right': 0, 'bottom': 0,
                },
            }
            for field in REACTION_FIELDS
        }
        seen_evidence = set()
        source_evidence = []
        for evidence in field_evidence.values():
            key = (evidence['source_file'], evidence['page'], evidence['quote'])
            if evidence['quote'] and key not in seen_evidence:
                seen_evidence.add(key)
                source_evidence.append(evidence)
        reagents, _ = normalize_reagent_catalyst_values(item.get('reagents') or [])
        catalysts, _ = normalize_reagent_catalyst_values(item.get('catalysts') or [])
        solvents, lookup_metadata = reaction_lookup_metadata(
            item.get('solvents') or [],
            item.get('other_conditions') or '',
            item.get('reagents') or [],
            item.get('catalysts') or [],
        )
        reactions.append({
            'form_key': f'draft_{index}',
            'display_id': f'{index:04d}',
            'reaction_number': index,
            'products': item.get('products') or [],
            'starting_materials': item.get('starting_materials') or [],
            'reagents': reagents,
            'catalysts': catalysts,
            'solvents': solvents,
            'reaction_time': item.get('reaction_time') or '',
            'reaction_pressure': item.get('reaction_pressure') or '',
            'reaction_temperature': item.get('reaction_temperature') or '',
            'other_conditions': item.get('other_conditions') or '',
            'reaction_stages': str(item.get('reaction_stages') or ''),
            'reaction_description_type': item.get('reaction_description_type') or '',
            'reaction_yield': item.get('yield') or '',
            'source_evidence': source_evidence,
            'confidence_scores': confidence_scores,
            'field_evidence': field_evidence,
            'lookup_metadata': lookup_metadata,
            'reviewer_notes': '',
        })
    return reactions


def _saved_reactions_for_display(job):
    reactions = list(job.reactions.all())
    for reaction in reactions:
        reaction.form_key = str(reaction.id)
        reaction.display_id = f'{reaction.id:04d}'
        _, reaction.lookup_metadata = reaction_lookup_metadata(
            reaction.solvents,
            reaction.other_conditions,
            reaction.reagents,
            reaction.catalysts,
        )
    return reactions


def _job_context(job, *, reactions=None, draft_token=''):
    displayed = _saved_reactions_for_display(job) if reactions is None else reactions
    return {
        'job': job,
        'reactions': displayed,
        'display_reaction_count': len(displayed),
        'is_draft': bool(draft_token),
        'draft_token': draft_token,
    }


@require_POST
def extract_documents(request):
    _discard_abandoned_jobs()
    files = request.FILES.getlist('documents')
    validation_error = _validate_uploads(files)
    if validation_error:
        messages.error(request, validation_error)
        return redirect('home')

    title = request.POST.get('title', '').strip() or Path(files[0].name).stem
    job = ExtractionJob.objects.create(title=title)
    for uploaded in files:
        SourceDocument.objects.create(job=job, original_name=uploaded.name, file=uploaded, file_size=uploaded.size)

    started = time.perf_counter()
    draft_reactions = []
    discarded = False
    try:
        reaction_data = run_extraction(job)
        draft_reactions = _prepare_draft_reactions(reaction_data)
        job.status = ExtractionJob.Status.DRAFT if draft_reactions else ExtractionJob.Status.COMPLETED
        job.reaction_count = 0
    except ExtractionDiscarded:
        discarded = True
    except Exception as error:
        try:
            job.refresh_from_db(fields=['discard_requested'])
        except ExtractionJob.DoesNotExist:
            discarded = True
        else:
            if job.discard_requested:
                discarded = True
            else:
                job.status = ExtractionJob.Status.FAILED
                job.error_message = str(error)
    finally:
        if not discarded:
            totals = job.token_usages.aggregate(
                prompt=Sum('prompt_tokens'), completion=Sum('completion_tokens'),
                total=Sum('total_tokens'), cost=Sum('estimated_cost_usd'),
            )
            job.total_prompt_tokens = totals['prompt'] or 0
            job.total_completion_tokens = totals['completion'] or 0
            job.total_tokens = totals['total'] or 0
            job.estimated_cost_usd = totals['cost'] or 0
            job.completed_at = timezone.now() if job.status != ExtractionJob.Status.DRAFT else None
            job.processing_duration_ms = round((time.perf_counter() - started) * 1000)
            job.save()

    if discarded:
        _discard_job(job)
        messages.info(request, 'The active extraction was discarded.')
        return redirect('home')

    if job.status == ExtractionJob.Status.FAILED:
        messages.error(request, f'Extraction stopped: {job.error_message}')
        return redirect('job_detail', job_id=job.id)
    if not draft_reactions:
        messages.success(request, 'Extraction completed. No source-supported reactions were found.')
        return redirect('job_detail', job_id=job.id)

    draft_token = signing.dumps(
        {'job_id': str(job.id), 'reactions': draft_reactions},
        salt=DRAFT_SIGNING_SALT,
        compress=True,
    )
    messages.warning(
        request,
        f'{len(draft_reactions)} reaction(s) are ready for review. No extracted fields are saved until you click Save work.',
    )
    return render(request, 'job_detail.html', _job_context(job, reactions=draft_reactions, draft_token=draft_token))


def records(request):
    _discard_abandoned_jobs()
    query = request.GET.get('q', '').strip()
    status = request.GET.get('status', '').strip()
    jobs = ExtractionJob.objects.exclude(
        status__in=[ExtractionJob.Status.DRAFT, ExtractionJob.Status.PROCESSING],
    ).prefetch_related('documents')
    if query:
        jobs = jobs.filter(Q(title__icontains=query) | Q(documents__original_name__icontains=query)).distinct()
    if status in ExtractionJob.Status.values:
        jobs = jobs.filter(status=status)
    return render(request, 'records.html', {'jobs': jobs, 'query': query, 'status': status})


def job_detail(request, job_id):
    job = get_object_or_404(
        ExtractionJob.objects.prefetch_related('documents', 'reactions', 'token_usages'),
        id=job_id,
    )
    if job.status == ExtractionJob.Status.DRAFT:
        _discard_job(job)
        messages.info(request, 'The unsaved extraction was discarded.')
        return redirect('records')
    if job.status == ExtractionJob.Status.PROCESSING:
        job.discard_requested = True
        job.save(update_fields=['discard_requested'])
        messages.info(request, 'The active extraction was marked for discard.')
        return redirect('records')
    return render(request, 'job_detail.html', _job_context(job))


@require_POST
def discard_draft(request, job_id):
    job = get_object_or_404(ExtractionJob.objects.prefetch_related('documents'), id=job_id)
    if job.status != ExtractionJob.Status.DRAFT:
        messages.error(request, 'Only an unsaved extraction can be discarded.')
        return redirect('job_detail', job_id=job.id)
    _discard_job(job)
    messages.info(request, 'The unsaved extraction was discarded.')
    return redirect('records')


def _split_lines(value):
    values = [line.strip() for line in value.splitlines() if line.strip()]
    return values


def _split_normalized_solvents(value):
    normalized, _ = normalize_solvent_values(_split_lines(value))
    return normalized


def _split_normalized_reagent_catalyst(value):
    normalized, _ = normalize_reagent_catalyst_values(_split_lines(value))
    return normalized


@require_POST
def save_reactions(request, job_id):
    job = get_object_or_404(ExtractionJob, id=job_id)
    draft_token = request.POST.get('draft_token', '')
    if draft_token:
        try:
            draft = signing.loads(draft_token, salt=DRAFT_SIGNING_SALT)
        except signing.BadSignature:
            messages.error(request, 'The unsaved extraction draft is invalid and was not saved.')
            return redirect('job_detail', job_id=job.id)
        if str(draft.get('job_id')) != str(job.id):
            messages.error(request, 'The extraction draft does not belong to this job and was not saved.')
            return redirect('job_detail', job_id=job.id)
        if job.status != ExtractionJob.Status.DRAFT or job.reactions.exists():
            messages.error(request, 'This extraction draft has already been saved or is no longer available.')
            return redirect('job_detail', job_id=job.id)

        draft_reactions = draft.get('reactions') or []
        with transaction.atomic():
            for index, item in enumerate(draft_reactions, start=1):
                prefix = f'reaction_draft_{index}_'
                Reaction.objects.create(
                    job=job,
                    reaction_number=index,
                    products=_split_lines(request.POST.get(prefix + 'products', '')),
                    starting_materials=_split_lines(request.POST.get(prefix + 'starting_materials', '')),
                    reagents=_split_normalized_reagent_catalyst(request.POST.get(prefix + 'reagents', '')),
                    catalysts=_split_normalized_reagent_catalyst(request.POST.get(prefix + 'catalysts', '')),
                    solvents=_split_normalized_solvents(request.POST.get(prefix + 'solvents', '')),
                    reaction_time=request.POST.get(prefix + 'reaction_time', '').strip(),
                    reaction_pressure=request.POST.get(prefix + 'reaction_pressure', '').strip(),
                    reaction_temperature=request.POST.get(prefix + 'reaction_temperature', '').strip(),
                    other_conditions=request.POST.get(prefix + 'other_conditions', '').strip(),
                    reaction_stages=request.POST.get(prefix + 'reaction_stages', '').strip(),
                    reaction_description_type=request.POST.get(prefix + 'reaction_description_type', '').strip(),
                    reaction_yield=request.POST.get(prefix + 'reaction_yield', '').strip(),
                    reviewer_notes=request.POST.get(prefix + 'reviewer_notes', '').strip(),
                    source_evidence=item.get('source_evidence') or [],
                    confidence_scores=item.get('confidence_scores') or {},
                    field_evidence=item.get('field_evidence') or {},
                )
            job.status = ExtractionJob.Status.COMPLETED
            job.reaction_count = len(draft_reactions)
            job.completed_at = timezone.now()
            job.save(update_fields=['status', 'reaction_count', 'completed_at'])
        messages.success(request, f'Saved {len(draft_reactions)} reaction record(s).')
        return redirect('job_detail', job_id=job.id)

    with transaction.atomic():
        for reaction in job.reactions.all():
            prefix = f'reaction_{reaction.id}_'
            reaction.products = _split_lines(request.POST.get(prefix + 'products', ''))
            reaction.starting_materials = _split_lines(request.POST.get(prefix + 'starting_materials', ''))
            reaction.reagents = _split_normalized_reagent_catalyst(request.POST.get(prefix + 'reagents', ''))
            reaction.catalysts = _split_normalized_reagent_catalyst(request.POST.get(prefix + 'catalysts', ''))
            reaction.solvents = _split_normalized_solvents(request.POST.get(prefix + 'solvents', ''))
            reaction.reaction_time = request.POST.get(prefix + 'reaction_time', '').strip()
            reaction.reaction_pressure = request.POST.get(prefix + 'reaction_pressure', '').strip()
            reaction.reaction_temperature = request.POST.get(prefix + 'reaction_temperature', '').strip()
            reaction.other_conditions = request.POST.get(prefix + 'other_conditions', '').strip()
            reaction.reaction_stages = request.POST.get(prefix + 'reaction_stages', '').strip()
            reaction.reaction_description_type = request.POST.get(prefix + 'reaction_description_type', '').strip()
            reaction.reaction_yield = request.POST.get(prefix + 'reaction_yield', '').strip()
            reaction.reviewer_notes = request.POST.get(prefix + 'reviewer_notes', '').strip()
            reaction.save()
    messages.success(request, 'Saved changes to the reaction records.')
    return redirect('job_detail', job_id=job.id)


def _reaction_row(reaction):
    _, lookup_metadata = reaction_lookup_metadata(
        reaction.solvents, reaction.other_conditions, reaction.reagents, reaction.catalysts,
    )
    return [
        str(reaction.job_id), reaction.job.title, reaction.reaction_number,
        reaction.job.model_name, reaction.job.total_prompt_tokens,
        reaction.job.total_completion_tokens, reaction.job.total_tokens,
        reaction.job.estimated_cost_usd, reaction.job.processing_duration_ms,
        reaction.job.completed_at.isoformat() if reaction.job.completed_at else '',
        ' | '.join(reaction.products), reaction.confidence_scores.get('products', 0),
        ' | '.join(reaction.starting_materials), reaction.confidence_scores.get('starting_materials', 0),
        ' | '.join(reaction.reagents), reaction.confidence_scores.get('reagents', 0),
        ' | '.join(reaction.catalysts), reaction.confidence_scores.get('catalysts', 0),
        ' | '.join(reaction.solvents), reaction.confidence_scores.get('solvents', 0),
        reaction.reaction_time, reaction.confidence_scores.get('reaction_time', 0),
        reaction.reaction_pressure, reaction.confidence_scores.get('reaction_pressure', 0),
        reaction.reaction_temperature, reaction.confidence_scores.get('reaction_temperature', 0),
        reaction.other_conditions, reaction.confidence_scores.get('other_conditions', 0),
        reaction.reaction_stages, reaction.confidence_scores.get('reaction_stages', 0),
        reaction.reaction_description_type, reaction.confidence_scores.get('reaction_description_type', 0),
        reaction.reaction_yield, reaction.confidence_scores.get('yield', 0),
        json.dumps(lookup_metadata['reagents'], ensure_ascii=False),
        json.dumps(lookup_metadata['catalysts'], ensure_ascii=False),
        json.dumps(lookup_metadata['solvents'], ensure_ascii=False),
        json.dumps(lookup_metadata['reaction_conditions'], ensure_ascii=False),
        json.dumps(reaction.field_evidence, ensure_ascii=False), reaction.reviewer_notes,
    ]


CSV_HEADERS = [
    'Job ID', 'Job title', 'Reaction number', 'Model/deployment', 'Job prompt tokens',
    'Job completion tokens', 'Job total tokens', 'Job estimated cost USD',
    'Processing duration ms', 'Saved at',
    'Products', 'Products confidence', 'Starting materials', 'Starting materials confidence',
    'Reagents', 'Reagents confidence', 'Catalysts', 'Catalysts confidence',
    'Solvents', 'Solvents confidence', 'Reaction time', 'Reaction time confidence',
    'Reaction pressure', 'Reaction pressure confidence',
    'Reaction temperature', 'Reaction temperature confidence',
    'Other reaction conditions', 'Other conditions confidence',
    'Number of reaction stages', 'Reaction stages confidence',
    'Type of reaction description', 'Type of reaction description confidence',
    'Yield', 'Yield confidence',
    'Reagent lookup matches', 'Catalyst lookup matches', 'Solvent lookup matches',
    'Reaction condition lookup matches',
    'Field evidence', 'Reviewer notes',
]


def _csv_response(reactions, filename):
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(CSV_HEADERS)
    for reaction in reactions:
        writer.writerow(_reaction_row(reaction))
    return response


def export_job_csv(request, job_id):
    job = get_object_or_404(ExtractionJob, id=job_id)
    return _csv_response(job.reactions.all(), f'reactxtract-{job.id}.csv')


def export_all_csv(request):
    return _csv_response(Reaction.objects.select_related('job').all(), 'reactxtract-all-reactions.csv')


def export_usage_csv(request, job_id):
    job = get_object_or_404(ExtractionJob, id=job_id)
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    response['Content-Disposition'] = f'attachment; filename="reactxtract-{job.id}-token-usage.csv"'
    response.write('\ufeff')
    writer = csv.writer(response)
    writer.writerow(['Phase', 'Document', 'Chunk', 'Model/deployment', 'Prompt tokens', 'Completion tokens', 'Total tokens', 'Estimated cost USD', 'Created'])
    for usage in job.token_usages.select_related('document'):
        writer.writerow([
            usage.get_phase_display(), usage.document.original_name if usage.document else 'All candidates',
            usage.chunk_number, usage.model_name, usage.prompt_tokens, usage.completion_tokens,
            usage.total_tokens, usage.estimated_cost_usd, usage.created_at.isoformat(),
        ])
    return response


def export_job_json(request, job_id):
    job = get_object_or_404(ExtractionJob.objects.prefetch_related('documents', 'reactions', 'token_usages'), id=job_id)
    payload = {
        'job': {
            'id': str(job.id), 'title': job.title, 'status': job.status,
            'model': job.model_name, 'reaction_count': job.reaction_count,
            'processing_duration_ms': job.processing_duration_ms,
            'created_at': job.created_at.isoformat(),
            'saved_at': job.completed_at.isoformat() if job.completed_at else None,
            'token_usage': {
                'prompt_tokens': job.total_prompt_tokens,
                'completion_tokens': job.total_completion_tokens,
                'total_tokens': job.total_tokens,
                'estimated_cost_usd': str(job.estimated_cost_usd),
            },
        },
        'documents': [
            {
                'filename': item.original_name,
                'pages': item.page_count,
                'file_size': item.file_size,
                'vision_pages': item.selected_pages,
                'extracted_text_file': item.extracted_text_file.name if item.extracted_text_file else '',
            }
            for item in job.documents.all()
        ],
        'reactions': [
            {
                'reaction_number': item.reaction_number,
                'products': item.products,
                'starting_materials': item.starting_materials,
                'reagents': item.reagents,
                'catalysts': item.catalysts,
                'solvents': item.solvents,
                'reaction_time': item.reaction_time,
                'reaction_pressure': item.reaction_pressure,
                'reaction_temperature': item.reaction_temperature,
                'other_reaction_conditions': item.other_conditions,
                'number_of_reaction_stages': item.reaction_stages,
                'type_of_reaction_description': item.reaction_description_type,
                'yield': item.reaction_yield,
                'lookup_metadata': reaction_lookup_metadata(
                    item.solvents,
                    item.other_conditions,
                    item.reagents,
                    item.catalysts,
                )[1],
                'source_evidence': item.source_evidence,
                'confidence_scores': item.confidence_scores,
                'field_evidence': item.field_evidence,
                'reviewer_notes': item.reviewer_notes,
            }
            for item in job.reactions.all()
        ],
        'ai_calls': [
            {
                'phase': item.phase,
                'document': item.document.original_name if item.document else None,
                'chunk_number': item.chunk_number,
                'model': item.model_name,
                'prompt_tokens': item.prompt_tokens,
                'completion_tokens': item.completion_tokens,
                'total_tokens': item.total_tokens,
                'estimated_cost_usd': str(item.estimated_cost_usd),
            }
            for item in job.token_usages.all()
        ],
    }
    response = JsonResponse(payload, json_dumps_params={'ensure_ascii': False, 'indent': 2})
    response['Content-Disposition'] = f'attachment; filename="reactxtract-{job.id}.json"'
    return response


PDF_SEARCH_TRANSLATION = str.maketrans({
    **dict(zip('₀₁₂₃₄₅₆₇₈₉', '0123456789')),
    **dict(zip('⁰¹²³⁴⁵⁶⁷⁸⁹', '0123456789')),
    '⁺': '+', '⁻': '-', '−': '-', '–': '-', '—': '-',
})
PDF_HIGHLIGHT_STOP_WORDS = {
    'the', 'and', 'for', 'with', 'from', 'was', 'were', 'after', 'before',
    'into', 'then', 'this', 'that', 'not', 'reported', 'reaction', 'mixture',
}


def _pdf_search_text(value):
    return ' '.join(str(value or '').translate(PDF_SEARCH_TRANSLATION).split()).strip()


def _unique_quads(quads, limit=16):
    unique = []
    seen = set()
    for quad in quads:
        rect = quad.rect if hasattr(quad, 'rect') else fitz.Rect(quad)
        key = tuple(round(value, 1) for value in (rect.x0, rect.y0, rect.x1, rect.y1))
        if key not in seen:
            seen.add(key)
            unique.append(quad)
        if len(unique) >= limit:
            break
    return unique


def _quote_anchor_quads(page, quote):
    quote = _pdf_search_text(quote)
    if not quote or quote.lower() == 'not reported.':
        return []
    words = quote.split()
    candidates = [quote]
    for length in (18, 14, 10, 7, 5):
        if len(words) >= length:
            candidates.extend((' '.join(words[:length]), ' '.join(words[-length:])))
    seen = set()
    for candidate in candidates:
        candidate = candidate.strip(' .,:;()[]{}')
        if len(candidate) < 6 or candidate.casefold() in seen:
            continue
        seen.add(candidate.casefold())
        quads = page.search_for(candidate, quads=True)
        if quads:
            return _unique_quads(quads)
    return []


def _field_value_quads(page, field_value):
    value = _pdf_search_text(field_value)
    if not value or value.lower() == 'not reported.':
        return []

    phrases = [
        _pdf_search_text(part).strip(' .,:;()[]{}')
        for part in re.split(r'[\n;|]+', str(field_value or ''))
    ]
    quads = []
    for phrase in phrases:
        if len(phrase) >= 2 and phrase.lower() != 'not reported.':
            quads.extend(page.search_for(phrase, quads=True))
    if quads:
        return _unique_quads(quads)

    # AI wording can include surrounding labels or punctuation. Fall back to
    # distinctive extracted tokens, including flattened molecular formulae.
    tokens = {
        token for token in re.findall(r'[A-Za-z0-9][A-Za-z0-9+./−–-]{1,}', value)
        if token.casefold() not in PDF_HIGHLIGHT_STOP_WORDS
        and (len(token) >= 4 or any(character.isdigit() for character in token))
    }
    for token in sorted(tokens, key=len, reverse=True):
        quads.extend(page.search_for(token, quads=True)[:4])
        if len(quads) >= 16:
            break
    return _unique_quads(quads)


def _find_quote_rectangles(page, quote, field_value=''):
    quote_quads = _quote_anchor_quads(page, quote)
    value_quads = _field_value_quads(page, field_value)
    if value_quads and quote_quads:
        anchor = fitz.Rect(quote_quads[0].rect)
        for quad in quote_quads[1:]:
            anchor.include_rect(quad.rect)
        anchor.x0 -= 24
        anchor.y0 -= 18
        anchor.x1 += 24
        anchor.y1 += 18
        nearby = [quad for quad in value_quads if anchor.intersects(quad.rect)]
        if nearby:
            return _unique_quads(nearby)
    return value_quads or quote_quads


def pdf_page_image(request, document_id, page_number):
    document = get_object_or_404(SourceDocument, id=document_id)
    pdf = fitz.open(document.file.path)
    try:
        if page_number < 1 or page_number > pdf.page_count:
            return HttpResponse('PDF page not found.', status=404, content_type='text/plain')
        page = pdf[page_number - 1]
        quote = request.GET.get('q', '')[:1000]
        field_value = request.GET.get('v', '')[:2000]
        rectangles = _find_quote_rectangles(page, quote, field_value)
        bbox_values = request.GET.get('bbox', '').split(',')
        if not rectangles and len(bbox_values) == 4:
            try:
                left, top, right, bottom = [max(0, min(1, float(value))) for value in bbox_values]
                if right > left and bottom > top:
                    rectangles = [fitz.Rect(
                        left * page.rect.width, top * page.rect.height,
                        right * page.rect.width, bottom * page.rect.height,
                    )]
            except ValueError:
                pass
        for rectangle in rectangles:
            annotation = page.add_highlight_annot(rectangle)
            annotation.set_colors(stroke=(1, 0.42, 0))
            annotation.set_opacity(0.42)
            annotation.update()
        pixmap = page.get_pixmap(matrix=fitz.Matrix(1.65, 1.65), alpha=False, annots=True)
        response = HttpResponse(pixmap.tobytes('png'), content_type='image/png')
        response['Cache-Control'] = 'private, no-store' if quote or field_value else 'private, max-age=3600'
        response['X-Frame-Options'] = 'SAMEORIGIN'
        return response
    finally:
        pdf.close()


def pdf_document(request, document_id):
    document = get_object_or_404(SourceDocument, id=document_id)
    response = FileResponse(
        document.file.open('rb'),
        content_type='application/pdf',
        as_attachment=False,
        filename=document.original_name,
    )
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    response['X-Frame-Options'] = 'SAMEORIGIN'
    return response


def extracted_text_document(request, document_id):
    document = get_object_or_404(SourceDocument, id=document_id)
    if not document.extracted_text_file:
        return HttpResponse('Extracted text is not available.', status=404, content_type='text/plain')
    filename = f'{Path(document.original_name).stem}.txt'
    response = FileResponse(
        document.extracted_text_file.open('rb'),
        content_type='text/plain; charset=utf-8',
        as_attachment=True,
        filename=filename,
    )
    response['Cache-Control'] = 'private, max-age=3600'
    response['X-Content-Type-Options'] = 'nosniff'
    return response
