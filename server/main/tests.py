import shutil
import tempfile
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import fitz
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .lookups import (
    match_reaction_conditions,
    normalize_reagent_catalyst_values,
    normalize_solvent_values,
)
from .models import AITokenUsage, ExtractionJob, Reaction, SourceDocument
from .services import (
    REACTION_FIELDS,
    REACTION_SCHEMA,
    _format_reaction_chemical_typography,
    build_native_page_context,
    chunk_page_numbers,
    consolidate_reactions,
    extract_column_aware_text,
    extract_document_reactions,
    extract_native_tables,
    format_chemical_subscripts,
    get_extraction_instructions,
    load_extracted_text_pages,
    select_keyword_pages,
    select_keyword_pages_from_text,
)
from .views import _find_quote_rectangles, _prepare_draft_reactions, _split_lines


TEST_MEDIA_ROOT = Path(__file__).resolve().parents[2] / '.test-media'


def make_pdf(page_texts):
    document = fitz.open()
    try:
        for text in page_texts:
            page = document.new_page()
            page.insert_text((72, 72), text)
        return document.tobytes()
    finally:
        document.close()


def field_metadata(source='article.pdf', page='1', quote='Supporting source text.'):
    return {
        field: {
            'confidence': 0.91, 'source_file': source, 'page': page, 'quote': quote,
            'bbox': {'left': 0.1, 'top': 0.1, 'right': 0.8, 'bottom': 0.2},
        }
        for field in REACTION_FIELDS
    }


@override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT)
class ReactXtractViewsTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(TEST_MEDIA_ROOT, ignore_errors=True)

    def test_home_loads_with_hybrid_pdf_extraction(self):
        response = self.client.get(reverse('home'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Hybrid AI extraction')
        self.assertContains(response, 'saves column-aware text and detected tables first')
        self.assertContains(response, 'Elapsed 00:00')
        self.assertNotContains(response, 'Tesseract')

    def test_unavailable_values_remain_blank(self):
        metadata = {
            field: {
                'confidence': 0,
                'source_file': '',
                'page': '',
                'quote': '',
                'bbox': {'left': 0, 'top': 0, 'right': 0, 'bottom': 0},
            }
            for field in REACTION_FIELDS
        }
        item = {
            'products': [], 'starting_materials': [], 'reagents': [],
            'catalysts': [], 'solvents': [], 'reaction_time': '',
            'reaction_pressure': '', 'other_conditions': '',
            'reaction_stages': '', 'field_metadata': metadata,
        }

        prepared = _prepare_draft_reactions([item])[0]
        job = ExtractionJob.objects.create(title='Blank defaults')
        reaction = Reaction.objects.create(job=job, reaction_number=1)

        self.assertEqual(prepared['products'], [])
        self.assertEqual(prepared['reaction_pressure'], '')
        self.assertEqual(prepared['field_evidence']['products']['source_file'], '')
        self.assertEqual(prepared['source_evidence'], [])
        self.assertEqual(_split_lines(''), [])
        self.assertEqual(reaction.reaction_time, '')
        self.assertEqual(reaction.reaction_pressure, '')
        self.assertEqual(reaction.reaction_temperature, '')
        self.assertEqual(reaction.other_conditions, '')
        self.assertEqual(reaction.reaction_stages, '')
        self.assertEqual(reaction.reaction_description_type, '')
        self.assertEqual(reaction.reaction_yield, '')

    @patch('main.views.run_extraction')
    def test_extraction_stays_unsaved_until_save_work(self, mocked_extraction):
        mocked_extraction.return_value = [{
            'products': ['Product A'], 'starting_materials': ['Starting material A'],
            'reagents': ['Base A'], 'catalysts': ['Catalyst A'], 'solvents': ['Solvent A'],
            'reaction_time': '2 h', 'reaction_pressure': '',
            'other_conditions': '80 °C', 'reaction_stages': '1',
            'field_metadata': field_metadata(page='4', quote='Product A was obtained after 2 h.'),
        }]
        upload = SimpleUploadedFile('article.pdf', make_pdf(['Product A was obtained after 2 h.']), content_type='application/pdf')
        response = self.client.post(reverse('extract_documents'), {'title': 'Test paper', 'documents': [upload]})
        job = ExtractionJob.objects.get()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(job.status, ExtractionJob.Status.DRAFT)
        self.assertEqual(job.reaction_count, 0)
        self.assertFalse(job.reactions.exists())
        self.assertContains(response, 'Review before saving')
        self.assertContains(response, 'Save work')
        self.assertContains(response, 'data-unsaved-review')
        self.assertContains(response, 'data-draft-resolution', count=2)
        self.assertContains(response, 'app.js?v=20261030.1')
        self.assertContains(response, 'RX-0001')
        self.assertContains(response, '91%')
        self.assertContains(response, 'alt="Rendered source PDF page"')
        self.assertContains(response, reverse('pdf_page_image', args=[job.documents.get().id, 1]))
        self.assertContains(response, 'styles.css?v=20261030.2')
        self.assertContains(response, 'data-individual-highlights', count=5)
        self.assertContains(response, 'data-value-highlights', count=5)
        self.assertContains(response, reverse('pdf_document', args=[job.documents.get().id]))

        draft_token = response.context['draft_token']
        save_response = self.client.post(reverse('save_reactions', args=[job.id]), {
            'draft_token': draft_token,
            'reaction_draft_1_products': 'Reviewed Product A',
            'reaction_draft_1_starting_materials': 'Starting material A',
            'reaction_draft_1_reagents': 'Base A',
            'reaction_draft_1_catalysts': 'Catalyst A',
            'reaction_draft_1_solvents': 'Solvent A',
            'reaction_draft_1_reaction_time': '2 h',
            'reaction_draft_1_reaction_pressure': '',
            'reaction_draft_1_other_conditions': '80 °C',
            'reaction_draft_1_reaction_stages': '1',
            'reaction_draft_1_reviewer_notes': 'Reviewed before saving.',
        })
        self.assertRedirects(save_response, reverse('job_detail', args=[job.id]))
        job.refresh_from_db()
        self.assertEqual(job.status, ExtractionJob.Status.COMPLETED)
        self.assertEqual(job.reaction_count, 1)
        self.assertIsNotNone(job.completed_at)
        self.assertGreater(job.total_duration_ms, 0)
        self.assertGreaterEqual(job.total_duration_ms, job.processing_duration_ms)
        reaction = job.reactions.get()
        self.assertEqual(reaction.products, ['Reviewed Product A'])
        self.assertEqual(reaction.reaction_pressure, '')
        self.assertEqual(reaction.confidence_scores['products'], 0.91)
        self.assertEqual(reaction.field_evidence['products']['page'], '4')
        detail_response = self.client.get(reverse('job_detail', args=[job.id]))
        self.assertContains(detail_response, 'Reaction tree')
        self.assertContains(detail_response, 'RX-0001')
        self.assertContains(detail_response, 'data-field-evidence')
        self.assertContains(detail_response, '91%')
        self.assertContains(detail_response, 'Extraction')
        self.assertContains(detail_response, 'Total to save')
        self.assertContains(detail_response, 'Saved')
        self.assertNotContains(detail_response, 'data-unsaved-review')

    @patch('main.views.run_extraction')
    def test_tampered_draft_is_not_saved(self, mocked_extraction):
        mocked_extraction.return_value = [{
            'products': ['Product A'], 'starting_materials': ['S'], 'reagents': ['R'],
            'catalysts': ['C'], 'solvents': ['water'], 'reaction_time': '1 h',
            'reaction_pressure': '', 'other_conditions': 'room temperature',
            'reaction_stages': '1', 'field_metadata': field_metadata(),
        }]
        upload = SimpleUploadedFile('article.pdf', make_pdf(['Reaction']), content_type='application/pdf')
        response = self.client.post(reverse('extract_documents'), {'documents': [upload]})
        job = ExtractionJob.objects.get()
        token = response.context['draft_token']
        self.client.post(reverse('save_reactions', args=[job.id]), {
            'draft_token': token[:-1] + ('a' if token[-1] != 'a' else 'b'),
            'reaction_draft_1_products': 'Tampered product',
        })
        job.refresh_from_db()
        self.assertEqual(job.status, ExtractionJob.Status.DRAFT)
        self.assertFalse(job.reactions.exists())

    def test_records_discards_unsaved_job_and_uploaded_file(self):
        job = ExtractionJob.objects.create(title='Discard me', status=ExtractionJob.Status.DRAFT)
        upload = SimpleUploadedFile('temporary.pdf', make_pdf(['Temporary extraction']), content_type='application/pdf')
        document = SourceDocument.objects.create(
            job=job, original_name='temporary.pdf', file=upload,
            extracted_text_file=SimpleUploadedFile('temporary.txt', b'Extracted text'),
            page_count=1,
        )
        AITokenUsage.objects.create(
            job=job, document=document, phase=AITokenUsage.Phase.EXTRACTION,
            model_name='test-model', total_tokens=10,
        )
        uploaded_path = Path(document.file.path)
        extracted_text_path = Path(document.extracted_text_file.path)
        self.assertTrue(uploaded_path.exists())
        self.assertTrue(extracted_text_path.exists())

        response = self.client.get(reverse('records'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExtractionJob.objects.filter(id=job.id).exists())
        self.assertFalse(SourceDocument.objects.filter(id=document.id).exists())
        self.assertFalse(AITokenUsage.objects.filter(job_id=job.id).exists())
        self.assertFalse(uploaded_path.exists())
        self.assertFalse(extracted_text_path.exists())
        self.assertNotContains(response, 'Discard me')

    def test_records_hides_processing_job_and_requests_safe_discard(self):
        job = ExtractionJob.objects.create(title='Active extraction')
        upload = SimpleUploadedFile(
            'active.pdf', make_pdf(['Active extraction']), content_type='application/pdf',
        )
        document = SourceDocument.objects.create(
            job=job, original_name='active.pdf', file=upload, page_count=1,
        )
        uploaded_path = Path(document.file.path)

        response = self.client.get(reverse('records'))

        self.assertEqual(response.status_code, 200)
        job.refresh_from_db()
        self.assertTrue(job.discard_requested)
        self.assertTrue(uploaded_path.exists())
        self.assertNotContains(response, 'Active extraction')

    def test_records_deletes_stale_processing_job_and_all_associated_files(self):
        job = ExtractionJob.objects.create(title='Stale extraction')
        first = SourceDocument.objects.create(
            job=job,
            original_name='first.pdf',
            file=SimpleUploadedFile('first.pdf', make_pdf(['First']), content_type='application/pdf'),
            page_count=1,
        )
        second = SourceDocument.objects.create(
            job=job,
            original_name='second.pdf',
            file=SimpleUploadedFile('second.pdf', make_pdf(['Second']), content_type='application/pdf'),
            page_count=1,
        )
        AITokenUsage.objects.create(
            job=job, document=first, phase=AITokenUsage.Phase.EXTRACTION,
            model_name='test-model', total_tokens=10,
        )
        paths = [Path(first.file.path), Path(second.file.path)]
        ExtractionJob.objects.filter(id=job.id).update(
            created_at=timezone.now() - timedelta(hours=2),
        )

        response = self.client.get(reverse('records'))

        self.assertEqual(response.status_code, 200)
        self.assertFalse(ExtractionJob.objects.filter(id=job.id).exists())
        self.assertFalse(SourceDocument.objects.filter(job_id=job.id).exists())
        self.assertFalse(AITokenUsage.objects.filter(job_id=job.id).exists())
        self.assertTrue(all(not path.exists() for path in paths))
        self.assertNotContains(response, 'Stale extraction')

    def test_reopening_unsaved_job_discards_it(self):
        job = ExtractionJob.objects.create(title='Abandoned review', status=ExtractionJob.Status.DRAFT)

        response = self.client.get(reverse('job_detail', args=[job.id]))

        self.assertRedirects(response, reverse('records'))
        self.assertFalse(ExtractionJob.objects.filter(id=job.id).exists())

    def test_explicit_discard_removes_only_unsaved_job(self):
        draft = ExtractionJob.objects.create(title='Discard explicitly', status=ExtractionJob.Status.DRAFT)
        completed = ExtractionJob.objects.create(title='Keep saved', status=ExtractionJob.Status.COMPLETED)

        response = self.client.post(reverse('discard_draft', args=[draft.id]))

        self.assertRedirects(response, reverse('records'))
        self.assertFalse(ExtractionJob.objects.filter(id=draft.id).exists())
        self.assertTrue(ExtractionJob.objects.filter(id=completed.id).exists())

    def test_pdf_page_image_renders_and_accepts_highlight_quote(self):
        job = ExtractionJob.objects.create(title='PDF test')
        upload = SimpleUploadedFile('source.pdf', make_pdf(['Experimental Procedure produced Product A after 2 h.']), content_type='application/pdf')
        document = SourceDocument.objects.create(job=job, original_name='source.pdf', file=upload, page_count=1)
        response = self.client.get(
            reverse('pdf_page_image', args=[document.id, 1]),
            {'q': 'text not present', 'bbox': '0.1,0.1,0.8,0.2'},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'image/png')
        self.assertTrue(response.content.startswith(b'\x89PNG'))

    def test_highlight_finds_extracted_formula_with_unicode_subscripts(self):
        pdf = fitz.open(stream=make_pdf([
            'The organic layers were dried over anhydrous Na2SO4 and concentrated.'
        ]), filetype='pdf')
        try:
            page = pdf[0]
            rectangles = _find_quote_rectangles(
                page,
                'The organic layers were dried over anhydrous Na2SO4 and concentrated.',
                'Na₂SO₄',
            )
            matched_text = ' '.join(page.get_textbox(quad.rect) for quad in rectangles)
        finally:
            pdf.close()

        self.assertTrue(rectangles)
        self.assertIn('Na2SO4', matched_text)

    def test_highlight_finds_each_line_of_a_multi_value_field(self):
        pdf = fitz.open(stream=make_pdf([
            'Acetic anhydride and pyridine were added to the reaction mixture.'
        ]), filetype='pdf')
        try:
            page = pdf[0]
            rectangles = _find_quote_rectangles(
                page,
                'Acetic anhydride and pyridine were added to the reaction mixture.',
                'Acetic anhydride\npyridine',
            )
            matched_text = ' '.join(page.get_textbox(quad.rect) for quad in rectangles)
        finally:
            pdf.close()

        self.assertIn('Acetic anhydride', matched_text)
        self.assertIn('pyridine', matched_text)

    def test_individual_value_highlight_excludes_other_field_values(self):
        pdf = fitz.open(stream=make_pdf([
            'Tetrahydrofuran and dichloromethane were used as reaction solvents.'
        ]), filetype='pdf')
        try:
            page = pdf[0]
            rectangles = _find_quote_rectangles(
                page,
                'Tetrahydrofuran and dichloromethane were used as reaction solvents.',
                'dichloromethane',
            )
            matched_text = ' '.join(page.get_textbox(quad.rect) for quad in rectangles)
        finally:
            pdf.close()

        self.assertIn('dichloromethane', matched_text.lower())
        self.assertNotIn('tetrahydrofuran', matched_text.lower())

    def test_pdf_document_is_served_inline_for_native_embed(self):
        job = ExtractionJob.objects.create(title='Embedded PDF test')
        pdf_bytes = make_pdf(['Embedded source document'])
        upload = SimpleUploadedFile('source document.pdf', pdf_bytes, content_type='application/pdf')
        document = SourceDocument.objects.create(job=job, original_name='source document.pdf', file=upload, page_count=1)

        response = self.client.get(reverse('pdf_document', args=[document.id]))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response['Content-Type'], 'application/pdf')
        self.assertTrue(response['Content-Disposition'].startswith('inline;'))
        self.assertEqual(b''.join(response.streaming_content), pdf_bytes)
        response.close()

    def test_csv_and_json_exports_include_cost_confidence_and_evidence(self):
        job = ExtractionJob.objects.create(
            title='Costed paper', status=ExtractionJob.Status.COMPLETED,
            model_name='test-model', total_prompt_tokens=100,
            total_completion_tokens=25, total_tokens=125,
            estimated_cost_usd=Decimal('0.000400'),
            processing_duration_ms=65432, total_duration_ms=125432,
            completed_at=timezone.now(),
        )
        Reaction.objects.create(
            job=job, reaction_number=1, products=['P'], starting_materials=['S'],
            reagents=['R'], catalysts=['C'], solvents=['water'],
            confidence_scores={'products': 0.88},
            field_evidence={'products': {'source_file': 'source.pdf', 'page': '1', 'quote': 'P was isolated.'}},
        )
        AITokenUsage.objects.create(
            job=job, phase=AITokenUsage.Phase.EXTRACTION, model_name='test-model',
            prompt_tokens=100, completion_tokens=25, total_tokens=125,
            estimated_cost_usd=Decimal('0.000400'),
        )

        csv_response = self.client.get(reverse('export_job_csv', args=[job.id]))
        self.assertContains(csv_response, 'Products confidence')
        self.assertContains(csv_response, 'Extraction processing duration ms')
        self.assertContains(csv_response, 'Total duration until save ms')
        self.assertContains(csv_response, 'Saved at')
        self.assertContains(csv_response, 'Reagent lookup matches')
        self.assertContains(csv_response, 'Catalyst lookup matches')
        self.assertContains(csv_response, 'Solvent lookup matches')
        self.assertContains(csv_response, '0.88')
        self.assertContains(csv_response, '0.000400')
        usage_response = self.client.get(reverse('export_usage_csv', args=[job.id]))
        self.assertContains(usage_response, 'Prompt tokens')
        json_response = self.client.get(reverse('export_job_json', args=[job.id])).json()
        self.assertEqual(json_response['job']['token_usage']['total_tokens'], 125)
        self.assertEqual(json_response['job']['processing_duration_ms'], 65432)
        self.assertEqual(json_response['job']['total_duration_ms'], 125432)
        self.assertIsNotNone(json_response['job']['saved_at'])
        self.assertEqual(json_response['reactions'][0]['confidence_scores']['products'], 0.88)
        self.assertEqual(json_response['reactions'][0]['field_evidence']['products']['page'], '1')
        self.assertTrue(json_response['reactions'][0]['lookup_metadata']['non_exhaustive'])
        self.assertEqual(json_response['reactions'][0]['lookup_metadata']['solvents'][0]['code'], '277')

        records_response = self.client.get(reverse('records'))
        self.assertContains(records_response, '1m 5s')
        self.assertContains(records_response, '2m 5s')
        self.assertContains(records_response, 'Total to save')
        self.assertContains(records_response, 'Saved at')


class ChunkingTests(TestCase):
    def test_keyword_selection_uses_matching_pages_and_context(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as handle:
            path = handle.name
            handle.write(make_pdf(['Introduction', 'Experimental Procedure for the reaction', 'Scope table', 'References']))
        try:
            page_count, selected = select_keyword_pages(path, keywords=['experimental procedure'], context_pages=1)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(page_count, 4)
        self.assertEqual(selected, [0, 1, 2])

    def test_page_chunker_preserves_page_order(self):
        self.assertEqual(chunk_page_numbers([0, 1, 4, 7, 8], max_pages=2), [[0, 1], [4, 7], [8]])

    def test_scheme_and_conditions_are_selected_without_section_keyword(self):
        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as handle:
            path = handle.name
            handle.write(make_pdf([
                'Introduction',
                'SCHEME 1 Reagents and conditions: NaBH4, MeOH, 0 C, 30 min.',
                'The reaction afforded compound 12 in 68% yield.',
                'References',
                'Example citation: Synthesis of unrelated compounds.',
            ]))
        try:
            page_count, selected = select_keyword_pages(path, keywords=[], context_pages=1)
        finally:
            Path(path).unlink(missing_ok=True)
        self.assertEqual(page_count, 5)
        self.assertEqual(selected, [0, 1, 2])

    def test_runtime_instructions_use_strict_rules_and_hybrid_appendix(self):
        instructions = get_extraction_instructions()
        self.assertIn('Experimental Procedure', instructions)
        self.assertIn('Synthetic Methodology', instructions)
        self.assertIn('hybrid PDF extraction', instructions)
        self.assertIn('column-aware reading order', instructions)
        self.assertIn('field_metadata', instructions)
        self.assertIn('a transformation arrow, and an identifiable product', instructions)
        self.assertIn('Representative Procedure', instructions)
        self.assertIn('Unicode subscript', instructions)
        self.assertIn('Mandatory Reaction Evidence Gate', instructions)
        self.assertIn('Mandatory Final Validation', instructions)
        self.assertIn('The evidence must support both the field value and its assigned role', instructions)
        self.assertIn('Do not create a reaction record solely because a chemical name', instructions)
        self.assertIn('lookup vocabularies are non-exhaustive', instructions)
        self.assertIn('### 8. Reaction Temperature', instructions)
        self.assertIn('### 11. Type of Reaction Description', instructions)
        self.assertIn('### 12. Yield', instructions)
        schema_fields = REACTION_SCHEMA['properties']['reactions']['items']['properties']
        self.assertIn('reaction_temperature', schema_fields)
        self.assertIn('reaction_description_type', schema_fields)
        self.assertIn('yield', schema_fields)


class OptionalLookupNormalizationTests(TestCase):
    def test_reagent_and_catalyst_workname_aliases_use_mname(self):
        values, matches = normalize_reagent_catalyst_values([
            'Et3N', 'DMAP', 'pyridine', 'new organocatalyst',
        ])

        self.assertEqual(values, [
            'triethylamine',
            '4-dimethylaminopyridine',
            'pyridine',
            'new organocatalyst',
        ])
        self.assertTrue(all(item['matched'] for item in matches[:3]))
        self.assertTrue(matches[0]['canonicalized'])
        self.assertEqual(matches[0]['code'], 'I2')
        self.assertFalse(matches[3]['matched'])

    def test_reagent_entry_without_mname_is_tagged_but_not_rewritten(self):
        values, matches = normalize_reagent_catalyst_values(['PCl5'])

        self.assertEqual(values, ['PCl5'])
        self.assertTrue(matches[0]['matched'])
        self.assertFalse(matches[0]['canonicalized'])

    def test_ambiguous_reagent_alias_is_not_normalized(self):
        values, matches = normalize_reagent_catalyst_values(['phosphorus'])

        self.assertEqual(values, ['phosphorus'])
        self.assertFalse(matches[0]['matched'])

    def test_known_solvent_synonyms_normalize_and_unknown_values_are_retained(self):
        values, matches = normalize_solvent_values(['THF', 'CH₂Cl₂', 'new bio-derived solvent'])

        self.assertEqual(values, [
            'tetrahydrofuran',
            'dichloromethane',
            'new bio-derived solvent',
        ])
        self.assertEqual(matches[0]['code'], '255')
        self.assertEqual(matches[1]['code'], '106')
        self.assertTrue(matches[0]['matched'])
        self.assertFalse(matches[2]['matched'])
        self.assertEqual(matches[2]['value'], 'new bio-derived solvent')

    def test_reaction_conditions_are_tagged_without_rewriting_full_text(self):
        conditions = 'The reaction was heated under an inert atmosphere in a sealed tube.'
        matches = match_reaction_conditions(conditions)

        self.assertEqual(
            {(item['code'], item['value']) for item in matches},
            {('38', 'Inert atmosphere'), ('45', 'Sealed tube')},
        )
        self.assertEqual(conditions, 'The reaction was heated under an inert atmosphere in a sealed tube.')

    def test_draft_exposes_advisory_lookup_metadata(self):
        item = {
            'solvents': ['DCM', 'unlisted solvent'],
            'reagents': ['Et3N', 'unlisted reagent'],
            'catalysts': ['DMAP'],
            'other_conditions': 'Microwave irradiation under inert atmosphere',
            'field_metadata': field_metadata(),
        }

        prepared = _prepare_draft_reactions([item])[0]

        self.assertEqual(prepared['solvents'], ['dichloromethane', 'unlisted solvent'])
        self.assertEqual(prepared['reagents'], ['triethylamine', 'unlisted reagent'])
        self.assertEqual(prepared['catalysts'], ['4-dimethylaminopyridine'])
        self.assertTrue(prepared['lookup_metadata']['non_exhaustive'])
        self.assertFalse(prepared['lookup_metadata']['solvents'][1]['matched'])
        self.assertEqual(prepared['lookup_metadata']['reagents'][0]['code'], 'I2')
        self.assertEqual(prepared['lookup_metadata']['catalysts'][0]['code'], 'I29')
        self.assertEqual(
            {item['code'] for item in prepared['lookup_metadata']['reaction_conditions']},
            {'38', '43'},
        )


class NativePdfExtractionTests(TestCase):
    @override_settings(MEDIA_ROOT=TEST_MEDIA_ROOT, AI_INPUT_MODE='hybrid')
    @patch('main.services._call_responses', return_value={'reactions': []})
    def test_pdf_is_saved_as_text_and_ai_chunk_uses_saved_text(self, mocked_call):
        job = ExtractionJob.objects.create(title='Text-first extraction')
        upload = SimpleUploadedFile(
            'article.pdf',
            make_pdf([
                'Experimental Procedure. Starting material A was added and stirred.',
                'The reaction afforded Product A in 80% yield after 2 h.',
            ]),
            content_type='application/pdf',
        )
        document = SourceDocument.objects.create(job=job, original_name='article.pdf', file=upload)

        extract_document_reactions(job, document, object(), 'test-model')

        document.refresh_from_db()
        self.assertTrue(document.extracted_text_file.name.endswith('.txt'))
        self.assertTrue(Path(document.extracted_text_file.path).exists())
        stored_pages = load_extracted_text_pages(document.extracted_text_file)
        self.assertEqual(len(stored_pages), 2)
        self.assertIn('ORIGINAL PAGE: 1', stored_pages[0])
        self.assertIn('Experimental Procedure', stored_pages[0])
        self.assertIn('Product A', stored_pages[1])
        sent_content = mocked_call.call_args.args[2]
        sent_text = next(item['text'] for item in sent_content if item['type'] == 'input_text')
        self.assertIn(stored_pages[0], sent_text)
        self.assertIn(stored_pages[1], sent_text)

    def test_keyword_selection_operates_on_extracted_page_text(self):
        selected = select_keyword_pages_from_text([
            'Introduction only.',
            'Experimental Procedure. The reaction mixture was stirred and afforded Product A in 80% yield.',
            'Characterization data for Product A.',
            'References',
        ], keywords=['experimental procedure'], context_pages=1)

        self.assertEqual(selected, [0, 1, 2])

    def test_two_column_text_is_emitted_column_by_column(self):
        document = fitz.open()
        try:
            page = document.new_page(width=600, height=800)
            page.insert_textbox(fitz.Rect(40, 100, 280, 190), 'LEFT-FIRST ' + ('left text ' * 20), fontsize=9)
            page.insert_textbox(fitz.Rect(40, 300, 280, 390), 'LEFT-SECOND ' + ('left detail ' * 20), fontsize=9)
            page.insert_textbox(fitz.Rect(330, 120, 570, 210), 'RIGHT-FIRST ' + ('right text ' * 20), fontsize=9)
            page.insert_textbox(fitz.Rect(330, 280, 570, 370), 'RIGHT-SECOND ' + ('right detail ' * 20), fontsize=9)

            text = extract_column_aware_text(page)
        finally:
            document.close()

        self.assertLess(text.index('LEFT-FIRST'), text.index('LEFT-SECOND'))
        self.assertLess(text.index('LEFT-SECOND'), text.index('RIGHT-FIRST'))
        self.assertLess(text.index('RIGHT-FIRST'), text.index('RIGHT-SECOND'))

    def test_native_table_is_extracted_as_rows_and_columns(self):
        document = fitz.open()
        try:
            page = document.new_page()
            xs, ys = [50, 200, 350], [100, 130, 160]
            for x in xs:
                page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                page.draw_line((xs[0], y), (xs[-1], y))
            page.insert_text((50, 80), 'Table 1. Optimization results')
            page.insert_text((60, 120), 'Reagent')
            page.insert_text((210, 120), 'Yield')
            page.insert_text((60, 150), 'Na2CO3')
            page.insert_text((210, 150), '82%')

            tables = extract_native_tables(page, page.get_text('text'))
        finally:
            document.close()

        self.assertEqual(tables, [[['Reagent', 'Yield'], ['Na2CO3', '82%']]])

    @override_settings(AI_INPUT_MODE='hybrid')
    def test_hybrid_context_keeps_native_table_and_routes_scheme_to_vision(self):
        document = fitz.open()
        try:
            table_page = document.new_page()
            xs, ys = [50, 200, 350], [100, 130, 160]
            for x in xs:
                table_page.draw_line((x, ys[0]), (x, ys[-1]))
            for y in ys:
                table_page.draw_line((xs[0], y), (xs[-1], y))
            table_page.insert_text((50, 80), 'Table 1. Optimization results')
            table_page.insert_text((60, 120), 'Base')
            table_page.insert_text((210, 120), 'Yield')
            table_page.insert_text((60, 150), 'K2CO3')
            table_page.insert_text((210, 150), '91%')
            scheme_page = document.new_page()
            scheme_page.insert_text((50, 80), 'Scheme 1. Reagents and conditions')
            pdf_bytes = document.tobytes()
        finally:
            document.close()

        with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as handle:
            path = handle.name
            handle.write(pdf_bytes)
        try:
            context, visual_pages = build_native_page_context(path, [0, 1], 'article.pdf')
        finally:
            Path(path).unlink(missing_ok=True)

        self.assertIn('ORIGINAL PAGE: 1', context)
        self.assertIn('[NATIVE TEXT — COLUMN-AWARE READING ORDER]', context)
        self.assertIn('[DETECTED TABLE 1]', context)
        self.assertIn('Row 2: K2CO3 | 91%', context)
        self.assertEqual(visual_pages, [1])


class ChemicalTypographyTests(TestCase):
    def test_flattened_formula_digits_are_restored_as_unicode_subscripts(self):
        value = 'Na2SO4, NaHCO3, CH2Cl2, K2CO3, CuSO4·5H2O, Pd(PPh3)4, and DMSO-d6'
        self.assertEqual(
            format_chemical_subscripts(value),
            'Na₂SO₄, NaHCO₃, CH₂Cl₂, K₂CO₃, CuSO₄·5H₂O, '
            'Pd(PPh₃)₄, and DMSO-d₆',
        )

    def test_non_formula_numbers_are_not_changed(self):
        value = '1,2-dichloro compound 3a (L-6), 20 mL, 24 h, 80 °C, page 14, RX0001'
        self.assertEqual(format_chemical_subscripts(value), value)

    def test_only_field_values_are_formatted_and_source_quote_remains_exact(self):
        reaction = {
            'products': ['Product A'],
            'reagents': ['Na2SO4'],
            'other_conditions': 'washed with NaHCO3',
            'field_metadata': {
                'reagents': {'quote': 'dried over Na2SO4', 'confidence': 0.96},
            },
        }

        formatted = _format_reaction_chemical_typography(reaction)

        self.assertEqual(formatted['reagents'], ['Na₂SO₄'])
        self.assertEqual(formatted['other_conditions'], 'washed with NaHCO₃')
        self.assertEqual(formatted['field_metadata']['reagents']['quote'], 'dried over Na2SO4')


class LocalFirstConsolidationTests(TestCase):
    def candidate(self, product, *, page='1', time='2 h', reagent='Base A', confidence=0.91, quote=None):
        metadata = field_metadata(
            page=page,
            quote=quote or f'{product} was obtained after {time}.',
        )
        for field in REACTION_FIELDS:
            metadata[field]['confidence'] = confidence
        return {
            'products': [product],
            'starting_materials': ['Starting material A'],
            'reagents': [reagent],
            'catalysts': ['Catalyst A'],
            'solvents': ['Solvent A'],
            'reaction_time': time,
            'reaction_pressure': '',
            'other_conditions': 'room temperature',
            'reaction_stages': '1',
            'field_metadata': metadata,
        }

    @patch('main.services._call_duplicate_resolution')
    def test_exact_duplicates_merge_locally_without_ai_and_keep_original_evidence(self, resolver):
        weaker = self.candidate('Compound 4a', confidence=0.72, quote='Original weaker quote.')
        stronger = self.candidate(' compound  4A ', confidence=0.96, quote='Original stronger quote.')

        result = consolidate_reactions(None, [weaker, stronger], None, 'test-model')

        resolver.assert_not_called()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['products'], [' compound  4A '])
        self.assertEqual(result[0]['field_metadata']['products']['confidence'], 0.96)
        self.assertEqual(result[0]['field_metadata']['products']['quote'], 'Original stronger quote.')

    @patch('main.services._call_duplicate_resolution')
    def test_distinct_reactions_remain_separate_without_ai(self, resolver):
        first = self.candidate('Compound 4a', page='2')
        second = self.candidate('Compound 5b', page='8')

        result = consolidate_reactions(None, [first, second], None, 'test-model')

        resolver.assert_not_called()
        self.assertEqual(len(result), 2)

    @patch('main.services._call_duplicate_resolution')
    def test_ambiguous_pair_merges_only_after_high_confidence_ai_confirmation(self, resolver):
        first = self.candidate('Compound 4a', page='2', time='2 h', confidence=0.94)
        second = self.candidate('Compound 4a', page='12', time='overnight', confidence=0.88)
        resolver.return_value = {
            'decisions': [{'pair_id': 1, 'is_duplicate': True, 'confidence': 0.95, 'reason': 'Same example.'}],
        }

        result = consolidate_reactions(None, [first, second], object(), 'test-model')

        resolver.assert_called_once()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['reaction_time'], '2 h')
        self.assertEqual(result[0]['field_metadata']['reaction_time']['confidence'], 0.94)

    @patch('main.services._call_duplicate_resolution')
    def test_uncertain_ai_duplicate_decision_preserves_both_reactions(self, resolver):
        first = self.candidate('Compound 4a', page='2', time='2 h')
        second = self.candidate('Compound 4a', page='12', time='overnight')
        resolver.return_value = {
            'decisions': [{'pair_id': 1, 'is_duplicate': True, 'confidence': 0.70, 'reason': 'Possibly same.'}],
        }

        result = consolidate_reactions(None, [first, second], object(), 'test-model')

        self.assertEqual(len(result), 2)
