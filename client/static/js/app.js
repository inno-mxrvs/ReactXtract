const input = document.querySelector('#documents');
const dropZone = document.querySelector('#drop-zone');
const fileList = document.querySelector('#file-list');
const extractButton = document.querySelector('#extract-button');
const extractionForm = document.querySelector('#extraction-form');
const processingOverlay = document.querySelector('#processing-overlay');
const processingElapsed = document.querySelector('#processing-elapsed');
const unsavedReview = document.querySelector('[data-unsaved-review]');
let allowDraftExit = false;

if (unsavedReview) {
    const warning = 'This extraction has not been saved. Leaving this page will discard the extracted fields. Continue?';

    document.querySelectorAll('[data-draft-resolution]').forEach((form) => {
        form.addEventListener('submit', () => {
            allowDraftExit = true;
        });
    });

    document.addEventListener('click', (event) => {
        const link = event.target.closest('a[href]');
        if (
            !link || event.button !== 0 || event.ctrlKey || event.metaKey || event.shiftKey || event.altKey
            || link.target === '_blank' || link.hasAttribute('download')
        ) return;
        const href = link.getAttribute('href') || '';
        if (!href || href.startsWith('#') || href.includes('/usage.csv')) return;
        if (!window.confirm(warning)) {
            event.preventDefault();
            return;
        }
        allowDraftExit = true;
    });

    window.addEventListener('beforeunload', (event) => {
        if (allowDraftExit) return;
        event.preventDefault();
        event.returnValue = '';
    });
}

const formatBytes = (bytes) => {
    if (!bytes) return '0 B';
    const units = ['B', 'KB', 'MB', 'GB'];
    const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
    return `${(bytes / (1024 ** index)).toFixed(index ? 1 : 0)} ${units[index]}`;
};

const renderFiles = () => {
    if (!input || !fileList) return;
    fileList.innerHTML = '';
    [...input.files].forEach((file, index) => {
        const row = document.createElement('div');
        row.className = 'file-row';
        row.innerHTML = `<span class="file-row__number">${String(index + 1).padStart(2, '0')}</span><span><strong></strong><small>${formatBytes(file.size)}</small></span><b>PDF</b>`;
        row.querySelector('strong').textContent = file.name;
        fileList.append(row);
    });
    if (extractButton) extractButton.disabled = input.files.length === 0;
};

input?.addEventListener('change', renderFiles);
['dragenter', 'dragover'].forEach((name) => dropZone?.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.add('drop-zone--active');
}));
['dragleave', 'drop'].forEach((name) => dropZone?.addEventListener(name, (event) => {
    event.preventDefault();
    dropZone.classList.remove('drop-zone--active');
}));
dropZone?.addEventListener('drop', (event) => {
    const pdfs = [...event.dataTransfer.files].filter((file) => file.name.toLowerCase().endsWith('.pdf'));
    if (!pdfs.length || !input) return;
    const transfer = new DataTransfer();
    pdfs.forEach((file) => transfer.items.add(file));
    input.files = transfer.files;
    renderFiles();
});

extractionForm?.addEventListener('submit', () => {
    if (processingOverlay) processingOverlay.hidden = false;
    if (extractButton) extractButton.disabled = true;
    const startedAt = performance.now();
    const updateElapsed = () => {
        if (!processingElapsed) return;
        const totalSeconds = Math.floor((performance.now() - startedAt) / 1000);
        const hours = Math.floor(totalSeconds / 3600);
        const minutes = Math.floor((totalSeconds % 3600) / 60);
        const seconds = totalSeconds % 60;
        const clock = hours
            ? `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`
            : `${String(minutes).padStart(2, '0')}:${String(seconds).padStart(2, '0')}`;
        processingElapsed.textContent = `Elapsed ${clock}`;
    };
    updateElapsed();
    window.setInterval(updateElapsed, 1000);
});

window.setTimeout(() => document.querySelectorAll('.toast').forEach((toast) => toast.remove()), 7000);

const reactionTreeNodes = [...document.querySelectorAll('[data-reaction-target]')];
const reactionPanels = [...document.querySelectorAll('[data-reaction-panel]')];

const showReactionPanel = (targetId) => {
    reactionPanels.forEach((panel) => panel.classList.toggle('is-hidden', panel.id !== targetId));
    reactionTreeNodes.forEach((node) => {
        const active = node.dataset.reactionTarget === targetId;
        node.classList.toggle('is-active', active);
        node.setAttribute('aria-selected', String(active));
    });
    document.querySelector(`#${targetId} input, #${targetId} textarea`)?.focus({preventScroll: true});
};

reactionTreeNodes.forEach((node) => node.addEventListener('click', () => showReactionPanel(node.dataset.reactionTarget)));

const copyText = async (value) => {
    if (navigator.clipboard && window.isSecureContext) {
        await navigator.clipboard.writeText(value);
        return;
    }
    const helper = document.createElement('textarea');
    helper.value = value;
    helper.style.position = 'fixed';
    helper.style.opacity = '0';
    document.body.append(helper);
    helper.select();
    document.execCommand('copy');
    helper.remove();
};

document.querySelectorAll('[data-copy-target]').forEach((button) => {
    button.addEventListener('click', async () => {
        const field = document.getElementById(button.dataset.copyTarget);
        if (!field) return;
        const originalText = button.textContent;
        try {
            await copyText(field.value);
            button.textContent = 'Copied';
            button.classList.add('is-copied');
        } catch {
            button.textContent = 'Retry';
        }
        window.setTimeout(() => {
            button.textContent = originalText;
            button.classList.remove('is-copied');
        }, 1400);
    });
});

const pdfViewer = document.querySelector('#pdf-viewer');
const pdfCanvas = document.querySelector('#pdf-canvas');
const openPdfLink = document.querySelector('#open-pdf-link');
const downloadTextLink = document.querySelector('#download-text-link');
const pdfPreviousPage = document.querySelector('#pdf-prev-page');
const pdfNextPage = document.querySelector('#pdf-next-page');
const pdfPageNumber = document.querySelector('#pdf-page-number');
const pdfPageCount = document.querySelector('#pdf-page-count');
const pdfHighlightStatus = document.querySelector('#pdf-highlight-status');
const documentTabs = [...document.querySelectorAll('[data-document-url]')];
let activeDocumentTab = documentTabs.find((tab) => tab.classList.contains('is-active')) || documentTabs[0];
let activePdfPage = 1;

const renderPdfPage = (page = 1, quote = '', bbox = '', fieldValue = '') => {
    if (!activeDocumentTab || !pdfViewer) return;
    const pageCount = Number.parseInt(activeDocumentTab.dataset.pageCount, 10) || 1;
    activePdfPage = Math.min(Math.max(Number.parseInt(page, 10) || 1, 1), pageCount);
    const params = new URLSearchParams();
    if (quote && quote.toLowerCase() !== 'not reported.') params.set('q', quote);
    if (fieldValue && fieldValue.toLowerCase() !== 'not reported.') params.set('v', fieldValue);
    if (bbox && bbox !== '0,0,0,0') params.set('bbox', bbox);
    const suffix = params.toString() ? `?${params}` : '';
    pdfCanvas?.classList.add('is-loading');
    pdfViewer.src = `/documents/${activeDocumentTab.dataset.documentId}/page/${activePdfPage}/image/${suffix}`;
    if (openPdfLink) openPdfLink.href = `${activeDocumentTab.dataset.documentUrl}#page=${activePdfPage}`;
    if (downloadTextLink) downloadTextLink.href = activeDocumentTab.dataset.textUrl;
    if (pdfPageNumber) {
        pdfPageNumber.value = activePdfPage;
        pdfPageNumber.max = pageCount;
    }
    if (pdfPageCount) pdfPageCount.textContent = pageCount;
    if (pdfPreviousPage) pdfPreviousPage.disabled = activePdfPage <= 1;
    if (pdfNextPage) pdfNextPage.disabled = activePdfPage >= pageCount;
};

pdfViewer?.addEventListener('load', () => pdfCanvas?.classList.remove('is-loading'));

const openDocument = (tab, page = 1, quote = '', bbox = '', fieldValue = '') => {
    if (!tab || !pdfViewer) return;
    activeDocumentTab = tab;
    documentTabs.forEach((item) => {
        const active = item === tab;
        item.classList.toggle('is-active', active);
        item.setAttribute('aria-selected', String(active));
    });
    renderPdfPage(page, quote, bbox, fieldValue);
};

documentTabs.forEach((tab) => tab.addEventListener('click', () => openDocument(tab)));
pdfPreviousPage?.addEventListener('click', () => renderPdfPage(activePdfPage - 1));
pdfNextPage?.addEventListener('click', () => renderPdfPage(activePdfPage + 1));
pdfPageNumber?.addEventListener('change', () => renderPdfPage(pdfPageNumber.value));

const activateFieldEvidence = (container, selectedValue = '') => {
    const sourceFile = (container.dataset.sourceFile || '').trim();
    const page = Number.parseInt(container.dataset.page, 10);
    const quote = (container.dataset.quote || '').trim();
    const bbox = (container.dataset.bbox || '').trim();
    const fieldValue = selectedValue.trim() || (container.querySelector('input, textarea')?.value || '').trim();
    document.querySelectorAll('[data-field-evidence]').forEach((field) => field.classList.toggle('is-source-active', field === container));
    document.querySelectorAll('[data-highlight-value]').forEach((button) => {
        button.classList.toggle('is-active', button.closest('[data-field-evidence]') === container && button.dataset.highlightValue === selectedValue);
    });
    if (!sourceFile || !page || sourceFile.toLowerCase() === 'not reported.') {
        if (pdfHighlightStatus) pdfHighlightStatus.textContent = 'No source location was reported for this field.';
        return;
    }
    const normalizedSource = sourceFile.toLowerCase();
    const matchingTab = documentTabs.find((tab) => tab.dataset.documentName.trim().toLowerCase() === normalizedSource)
        || documentTabs.find((tab) => normalizedSource.includes(tab.dataset.documentName.trim().toLowerCase()))
        || activeDocumentTab;
    const fieldLabel = container.querySelector('label')?.textContent || 'field';
    if (pdfHighlightStatus) {
        pdfHighlightStatus.textContent = selectedValue
            ? `Highlighted “${selectedValue}” for ${fieldLabel} on page ${page}.`
            : `Highlighted source words for ${fieldLabel} on page ${page}.`;
    }
    openDocument(matchingTab, page, quote, bbox, fieldValue);
};

document.querySelectorAll('[data-field-evidence]').forEach((container) => {
    container.addEventListener('focusin', (event) => {
        if (!event.target.closest('[data-highlight-value]')) activateFieldEvidence(container);
    });
    container.addEventListener('click', (event) => {
        if (!event.target.closest('[data-highlight-value]')) activateFieldEvidence(container);
    });
});

const syncIndividualHighlightValues = (container) => {
    const input = container.querySelector('textarea, input');
    const target = container.querySelector('[data-value-highlights]');
    if (!input || !target) return;
    const values = [...new Set(input.value.split(/\r?\n/).map((value) => value.trim()).filter(Boolean))];
    target.replaceChildren(...values.map((value) => {
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'value-highlight-chip';
        button.dataset.highlightValue = value;
        button.textContent = value;
        button.title = `Highlight only “${value}” in the source PDF`;
        button.addEventListener('click', (event) => {
            event.stopPropagation();
            activateFieldEvidence(container, value);
        });
        return button;
    }));
    target.hidden = values.length === 0;
};

document.querySelectorAll('[data-individual-highlights]').forEach((container) => {
    syncIndividualHighlightValues(container);
    container.querySelector('textarea, input')?.addEventListener('input', () => syncIndividualHighlightValues(container));
});

