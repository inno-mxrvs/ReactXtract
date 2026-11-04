import re
from copy import copy
from io import BytesIO
from pathlib import Path

from django.conf import settings
from django.utils import timezone
from openpyxl import load_workbook
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.formatting.rule import ColorScaleRule


TEMPLATE_FILENAME = 'ReactXtract_Per_File_Product_Accuracy_Template.xlsx'
TEMPLATE_SHEET = 'File Review Template'
FIRST_PRODUCT_ROW = 9
FIELDS_PER_PRODUCT = 12
TEMPLATE_PRODUCT_BLOCKS = 20

REACTION_FIELDS = (
    ('Products', 'products'),
    ('Starting materials', 'starting_materials'),
    ('Reagents', 'reagents'),
    ('Catalysts', 'catalysts'),
    ('Solvents', 'solvents'),
    ('Reaction time', 'reaction_time'),
    ('Reaction pressure', 'reaction_pressure'),
    ('Reaction temperature', 'reaction_temperature'),
    ('Other reaction conditions', 'other_conditions'),
    ('Number of reaction stages', 'reaction_stages'),
    ('Type of reaction description', 'reaction_description_type'),
    ('Yield', 'yield'),
)

INVALID_SHEET_CHARACTERS = re.compile(r'[:\\/?*\[\]]')


def _template_path():
    return settings.PROJECT_DIR / TEMPLATE_FILENAME


def _unique_sheet_title(value, used_titles):
    title = INVALID_SHEET_CHARACTERS.sub('-', str(value or '')).strip().strip("'") or 'Source file'
    title = title[:31]
    candidate = title
    suffix_number = 2
    while candidate.casefold() in used_titles:
        suffix = f' ({suffix_number})'
        candidate = f'{title[:31 - len(suffix)]}{suffix}'
        suffix_number += 1
    used_titles.add(candidate.casefold())
    return candidate


def _normalized_filename(value):
    return Path(str(value or '').replace('\\', '/')).name.casefold()


def _reaction_source_filename(reaction):
    evidence = reaction.field_evidence or {}
    preferred = evidence.get('products') or {}
    if preferred.get('source_file'):
        return preferred['source_file']
    for field_name in (key for _, key in REACTION_FIELDS):
        item = evidence.get(field_name) or {}
        if item.get('source_file'):
            return item['source_file']
    for item in reaction.source_evidence or []:
        if item.get('source_file'):
            return item['source_file']
    return ''


def _group_reactions_by_document(job, documents, reactions):
    grouped = {document.id: [] for document in documents}
    if not documents:
        return grouped
    normalized_documents = {
        document.id: _normalized_filename(document.original_name)
        for document in documents
    }
    for reaction in reactions:
        source_name = _normalized_filename(_reaction_source_filename(reaction))
        selected = next(
            (
                document for document in documents
                if source_name and (
                    source_name == normalized_documents[document.id]
                    or source_name in normalized_documents[document.id]
                    or normalized_documents[document.id] in source_name
                )
            ),
            documents[0],
        )
        grouped[selected.id].append(reaction)
    return grouped


def _product_entries(reactions):
    entries = []
    for reaction in reactions:
        products = reaction.products or ['']
        entries.extend((reaction, product) for product in products)
    return entries


def _copy_product_block(sheet, source_start, destination_start):
    for offset in range(FIELDS_PER_PRODUCT):
        source_row = source_start + offset
        destination_row = destination_start + offset
        sheet.row_dimensions[destination_row].height = sheet.row_dimensions[source_row].height
        for column in range(1, 10):
            source = sheet.cell(source_row, column)
            destination = sheet.cell(destination_row, column)
            destination.value = source.value
            if source.has_style:
                destination._style = copy(source._style)
            destination.number_format = source.number_format
            destination.font = copy(source.font)
            destination.fill = copy(source.fill)
            destination.border = copy(source.border)
            destination.alignment = copy(source.alignment)
            destination.protection = copy(source.protection)
    sheet.merge_cells(
        start_row=destination_start, start_column=1,
        end_row=destination_start + FIELDS_PER_PRODUCT - 1, end_column=1,
    )
    sheet.merge_cells(
        start_row=destination_start, start_column=2,
        end_row=destination_start + FIELDS_PER_PRODUCT - 1, end_column=2,
    )


def _resize_product_capacity(sheet, product_count):
    source_start = FIRST_PRODUCT_ROW + ((TEMPLATE_PRODUCT_BLOCKS - 1) * FIELDS_PER_PRODUCT)
    if product_count > TEMPLATE_PRODUCT_BLOCKS:
        for block_index in range(TEMPLATE_PRODUCT_BLOCKS, product_count):
            destination_start = FIRST_PRODUCT_ROW + (block_index * FIELDS_PER_PRODUCT)
            _copy_product_block(sheet, source_start, destination_start)

    available_blocks = max(TEMPLATE_PRODUCT_BLOCKS, product_count)
    if product_count < available_blocks:
        delete_start = FIRST_PRODUCT_ROW + (product_count * FIELDS_PER_PRODUCT)
        delete_count = (available_blocks - product_count) * FIELDS_PER_PRODUCT
        for merged_range in list(sheet.merged_cells.ranges):
            if merged_range.min_row >= delete_start:
                sheet.unmerge_cells(str(merged_range))
        sheet.delete_rows(delete_start, delete_count)

    sheet.conditional_formatting = ConditionalFormattingList()
    if not product_count:
        sheet.data_validations.dataValidation = []
        sheet['C7'] = '=""'
        sheet['E7'] = '=""'
        sheet['G7'] = '=0'
        return

    last_row = FIRST_PRODUCT_ROW + (product_count * FIELDS_PER_PRODUCT) - 1
    for validation in sheet.data_validations.dataValidation:
        validation.sqref = f'E{FIRST_PRODUCT_ROW}:E{last_row} G{FIRST_PRODUCT_ROW}:G{last_row}'
    for column in ('E', 'G'):
        sheet.conditional_formatting.add(
            f'{column}{FIRST_PRODUCT_ROW}:{column}{last_row}',
            ColorScaleRule(start_type='min', start_color='F8696B', mid_type='percentile',
                           mid_value=50, mid_color='FFEB84', end_type='max', end_color='63BE7B'),
        )
    sheet['C7'] = f'=IFERROR(AVERAGE(E{FIRST_PRODUCT_ROW}:E{last_row}),"")'
    sheet['E7'] = f'=IFERROR(AVERAGE(G{FIRST_PRODUCT_ROW}:G{last_row}),"")'
    sheet['G7'] = f'=COUNT(G{FIRST_PRODUCT_ROW}:G{last_row})'


def _display_value(reaction, field_name, selected_product):
    if field_name == 'products':
        return selected_product
    if field_name == 'yield':
        return reaction.reaction_yield
    value = getattr(reaction, field_name)
    if isinstance(value, list):
        return '\n'.join(str(item) for item in value)
    return str(value or '')


def _confidence_percent(reaction, field_name):
    value = reaction.confidence_scores.get(field_name, 0) if reaction.confidence_scores else 0
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0
    return numeric * 100 if 0 <= numeric <= 1 else numeric


def _populate_product_block(sheet, block_index, reaction, selected_product):
    start = FIRST_PRODUCT_ROW + (block_index * FIELDS_PER_PRODUCT)
    sheet.cell(start, 1, selected_product or 'Unnamed product')
    sheet.cell(start, 2, f'RX-{reaction.reaction_number:04d}')
    for offset, (label, field_name) in enumerate(REACTION_FIELDS):
        row = start + offset
        metadata = (reaction.field_evidence or {}).get(field_name) or {}
        sheet.cell(row, 3, label)
        sheet.cell(row, 4, _display_value(reaction, field_name, selected_product))
        sheet.cell(row, 5, _confidence_percent(reaction, field_name))
        sheet.cell(row, 6, '')
        sheet.cell(row, 7, '')
        sheet.cell(row, 8, str(metadata.get('page') or ''))
        note_parts = [str(metadata.get('quote') or '').strip()]
        if reaction.reviewer_notes:
            note_parts.append(f'Reviewer notes: {reaction.reviewer_notes}')
        sheet.cell(row, 9, '\n'.join(part for part in note_parts if part))


def _document_cost(job, document):
    return sum(
        (usage.estimated_cost_usd for usage in job.token_usages.all() if usage.document_id == document.id),
        start=0,
    )


def _populate_file_sheet(sheet, job, document, reactions):
    entries = _product_entries(reactions)
    _resize_product_capacity(sheet, len(entries))
    sheet['A3'] = 'Products extracted'
    sheet['B3'] = len(entries)
    sheet['C3'] = 'Reactions extracted'
    sheet['D3'] = len(reactions)
    sheet['E3'] = 'Processed / saved date'
    sheet['F3'] = timezone.localtime(job.completed_at).replace(tzinfo=None) if job.completed_at else ''
    sheet['F3'].number_format = 'yyyy-mm-dd hh:mm:ss'
    for cell in sheet[3]:
        cell.fill = copy(sheet['A4'].fill)
        cell.border = copy(sheet['A4'].border)
        cell.alignment = copy(sheet['A4'].alignment)
    sheet['B4'] = document.original_name
    sheet['B5'] = f'{job.title} / {job.id}'
    sheet['A6'] = 'Job total processing cost (USD)'
    sheet['B6'] = float(job.estimated_cost_usd)
    sheet['B6'].number_format = '$0.000000'
    sheet['C6'] = 'File extraction cost (USD)'
    sheet['D6'] = float(_document_cost(job, document))
    sheet['D6'].number_format = '$0.000000'
    sheet['E6'] = 'Job total tokens'
    sheet['F6'] = job.total_tokens
    sheet['G6'] = 'Total time until save (seconds)'
    sheet['H6'] = round(job.total_duration_ms / 1000, 1)
    sheet['I6'] = f'Model: {job.model_name}'
    for cell in sheet[6]:
        cell.fill = copy(sheet['A4'].fill)
        cell.border = copy(sheet['A4'].border)
        cell.alignment = copy(sheet['A4'].alignment)
    for block_index, (reaction, product) in enumerate(entries):
        _populate_product_block(sheet, block_index, reaction, product)


def build_accuracy_workbook(jobs):
    workbook = load_workbook(_template_path())
    template = workbook[TEMPLATE_SHEET]
    jobs = list(jobs)
    file_records = []
    for job in jobs:
        documents = list(job.documents.all())
        reactions = list(job.reactions.all())
        grouped = _group_reactions_by_document(job, documents, reactions)
        for document in documents:
            file_records.append((job, document, grouped.get(document.id, [])))

    if not file_records:
        template.title = 'No saved files'
        template['B4'] = 'No saved source files were available.'
    else:
        sheets = [template]
        for _ in file_records[1:]:
            copied = workbook.copy_worksheet(template)
            copied.data_validations = copy(template.data_validations)
            sheets.append(copied)
        used_titles = {'instructions'}
        multiple_jobs = len(jobs) > 1
        for sheet, (job, document, reactions) in zip(sheets, file_records):
            label = f'{job.title} - {Path(document.original_name).stem}' if multiple_jobs else Path(document.original_name).stem
            sheet.title = _unique_sheet_title(label, used_titles)
            _populate_file_sheet(sheet, job, document, reactions)

    if 'Instructions' in workbook.sheetnames:
        workbook.remove(workbook['Instructions'])

    output = BytesIO()
    workbook.save(output)
    output.seek(0)
    return output
