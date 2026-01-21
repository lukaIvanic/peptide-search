/**
 * Main application entry point.
 */

import * as api from './js/api.js?v=dev45';
import { initTour } from './js/tour.js?v=dev45';
import { markMilestone, renderChecklist, resetMilestones } from './js/onboarding.js?v=dev45';
import {
    appStore,
    setSearchResults,
    setSearching,
    togglePaperSelection,
    clearBatchSelection,
    setSelectedPapers,
    getSelectedPapers,
    isPaperSelected,
    setSelectedProvider,
    getSelectedProvider,
    setPapers,
    updatePaperStatus,
    addPaperToList,
    openDrawer,
    closeDrawer,
    setDrawerContent,
} from './js/state.js?v=dev45';
import {
    $,
    renderProviderBadge,
    renderConnectionBadge,
    renderSearchResults,
    renderBatchCount,
    renderPapersTable,
    renderQueueStats,
    renderDrawer,
    setDrawerOpen,
    setSearchCount,
    setDrawerCallbacks,
} from './js/renderers.js?v=dev45';

let sseConnection = null;
let failureModalState = null;
let failureModalItems = [];
const PAPER_FILTERS_STORAGE_KEY = 'dashboard_paper_filters_v3';
const PAPER_FILTERS_ALLOWED_STATUS = new Set([
    '',
    'processing',
    'queued',
    'failed',
    'stored',
    'cancelled',
    'none',
]);
const PAPER_FILTERS_ALLOWED_SOURCE = new Set([
    '',
    'pmc',
    'europepmc',
    'arxiv',
    'semanticscholar',
    'upload',
]);
const PAPER_FILTERS_ALLOWED_SORT = new Set([
    'recent',
    'oldest',
    'runs',
]);
const paperFilters = {
    query: '',
    status: '',
    source: '',
    sort: 'recent',
};
const DASHBOARD_ONBOARDING_KEY = 'onboarding_dashboard_v1';
const DASHBOARD_STEPS = [
    { key: 'searched', label: 'Run a search' },
    { key: 'enqueued', label: 'Start batch extraction' },
    { key: 'opened_paper', label: 'Open a paper drawer' },
];

// Initialize application
async function init() {
    // Load provider info
    try {
        const health = await api.getHealth();
        appStore.set({ provider: health.provider, model: health.model });
        renderProviderBadge(health.provider, health.model);
        renderConnectionBadge('connected');
    } catch {
        renderProviderBadge('unknown', null);
        renderConnectionBadge('disconnected');
    }
    
    // Setup drawer action callbacks
    setDrawerCallbacks({
        onRetry: handleRetryRun,
        onForceReextract: handleForceReextract,
    });
    
    // Setup event handlers
    initEventHandlers();
    initTourGuide();
    renderOnboarding();
    initContextHints();
    
    // Subscribe to state changes
    initStateSubscriptions();
    
    // Connect to SSE for live updates
    connectSSE();
    
    // Initial data load
    await refreshPapers();
    await loadRecentFailures();
    await loadFailureSummary();
    hydratePaperFilters();
    renderFilteredPapers();
}

function initContextHints() {
    const dismiss = document.querySelector('#contextHintDismiss');
    if (dismiss) {
        dismiss.addEventListener('click', () => hideHint());
    }
    updateContextHint();
}

function showHint(message, key) {
    if (!message) return;
    if (hasHintSeen(key)) return;
    const container = document.querySelector('#contextHint');
    const text = document.querySelector('#contextHintText');
    if (!container || !text) return;
    text.textContent = message;
    container.classList.remove('hidden');
    container.dataset.hintKey = key;
}

function hideHint() {
    const container = document.querySelector('#contextHint');
    if (!container) return;
    const key = container.dataset.hintKey;
    if (key) markHintSeen(key);
    container.classList.add('hidden');
    container.dataset.hintKey = '';
}

function hasHintSeen(key) {
    try {
        return localStorage.getItem(`hint_${key}`) === '1';
    } catch {
        return false;
    }
}

function markHintSeen(key) {
    try {
        localStorage.setItem(`hint_${key}`, '1');
    } catch {
        // ignore
    }
}

function updateContextHint() {
    const state = getOnboardingState();
    if (!state.searched) {
        showHint('Tip: Start with a broad search keyword to populate papers.', 'search_hint');
        return;
    }
    if (state.searched && !state.enqueued) {
        showHint('Tip: Select multiple results and click Start Extraction to queue runs.', 'enqueue_hint');
        return;
    }
    if (state.enqueued && !state.opened_paper) {
        showHint('Tip: Click a paper row to open the drawer and inspect runs.', 'open_drawer_hint');
        return;
    }
    hideHint();
}

function getOnboardingState() {
    try {
        return JSON.parse(localStorage.getItem(DASHBOARD_ONBOARDING_KEY) || '{}');
    } catch {
        return {};
    }
}

function initTourGuide() {
    const tour = initTour({
        storageKey: 'tour_dashboard_v1',
        autoStart: true,
        steps: [
            {
                selector: '#queryInput',
                title: 'Search',
                body: 'Start with broad peptide keywords and refine from results.',
            },
            {
                selector: '#providerSelect',
                title: 'Provider',
                body: 'Switch providers to compare extraction behavior.',
            },
            {
                selector: '#searchBtn',
                title: 'Run search',
                body: 'Fetch open-access results from multiple sources.',
            },
            {
                selector: '#startBatchBtn',
                title: 'Batch extraction',
                body: 'Select multiple papers and extract in bulk.',
            },
            {
                selector: '#papersTable',
                title: 'Papers & status',
                body: 'Open the drawer to inspect runs and entities.',
            },
        ],
    });
    const btn = document.querySelector('#startTourBtn');
    if (btn) btn.addEventListener('click', tour.start);
}

function renderOnboarding() {
    renderChecklist({
        containerId: '#onboardingList',
        progressId: '#onboardingProgress',
        items: DASHBOARD_STEPS,
        storageKey: DASHBOARD_ONBOARDING_KEY,
    });
    const resetBtn = document.querySelector('#resetOnboarding');
    if (resetBtn && !resetBtn.dataset.bound) {
        resetBtn.dataset.bound = '1';
        resetBtn.addEventListener('click', () => {
            resetMilestones(DASHBOARD_ONBOARDING_KEY);
            renderOnboarding();
            updateContextHint();
        });
    }
}

function initEventHandlers() {
    // Search
    $('#searchBtn').addEventListener('click', handleSearch);
    $('#queryInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleSearch();
    });
    const refreshFailuresBtn = document.querySelector('#refreshFailures');
    if (refreshFailuresBtn) {
        refreshFailuresBtn.addEventListener('click', loadRecentFailures);
    }
    const refreshFailureSummaryBtn = document.querySelector('#refreshFailureSummary');
    if (refreshFailureSummaryBtn) {
        refreshFailureSummaryBtn.addEventListener('click', loadFailureSummary);
    }
    const failureWindowSelect = document.querySelector('#failureWindow');
    if (failureWindowSelect) {
        failureWindowSelect.addEventListener('change', loadFailureSummary);
    }
    const papersPresetFailed = document.querySelector('#papersPresetFailed');
    if (papersPresetFailed) {
        papersPresetFailed.addEventListener('click', () => {
            applyPaperPreset('failed');
        });
    }
    const papersPresetProcessing = document.querySelector('#papersPresetProcessing');
    if (papersPresetProcessing) {
        papersPresetProcessing.addEventListener('click', () => {
            applyPaperPreset('processing');
        });
    }
    const papersPresetNoRuns = document.querySelector('#papersPresetNoRuns');
    if (papersPresetNoRuns) {
        papersPresetNoRuns.addEventListener('click', () => {
            applyPaperPreset('none');
        });
    }
    const papersFilterInput = document.querySelector('#papersFilterInput');
    if (papersFilterInput) {
        papersFilterInput.addEventListener('input', (e) => {
            paperFilters.query = e.target.value || '';
            renderFilteredPapers();
        });
    }
    const papersFilterStatus = document.querySelector('#papersFilterStatus');
    if (papersFilterStatus) {
        papersFilterStatus.addEventListener('change', (e) => {
            paperFilters.status = e.target.value || '';
            renderFilteredPapers();
        });
    }
    const papersFilterSource = document.querySelector('#papersFilterSource');
    if (papersFilterSource) {
        papersFilterSource.addEventListener('change', (e) => {
            paperFilters.source = e.target.value || '';
            renderFilteredPapers();
        });
    }
    const papersFilterSort = document.querySelector('#papersFilterSort');
    if (papersFilterSort) {
        papersFilterSort.addEventListener('change', (e) => {
            paperFilters.sort = e.target.value || 'recent';
            renderFilteredPapers();
        });
    }
    const papersFilterClear = document.querySelector('#papersFilterClear');
    if (papersFilterClear) {
        papersFilterClear.addEventListener('click', () => {
            paperFilters.query = '';
            paperFilters.status = '';
            paperFilters.source = '';
            paperFilters.sort = 'recent';
            syncPaperFilterInputs();
            renderFilteredPapers();
        });
    }
    const papersFilterNoticeClear = document.querySelector('#papersFilterNoticeClear');
    if (papersFilterNoticeClear) {
        papersFilterNoticeClear.addEventListener('click', () => {
            paperFilters.query = '';
            paperFilters.status = '';
            paperFilters.source = '';
            paperFilters.sort = 'recent';
            syncPaperFilterInputs();
            renderFilteredPapers();
        });
    }
    const papersFilterExport = document.querySelector('#papersFilterExport');
    if (papersFilterExport) {
        papersFilterExport.addEventListener('click', handleExportPapersCsv);
    }
    const selectAllResults = document.querySelector('#selectAllResults');
    if (selectAllResults) {
        selectAllResults.addEventListener('click', handleSelectAllResults);
    }
    const clearResultsSelection = document.querySelector('#clearResultsSelection');
    if (clearResultsSelection) {
        clearResultsSelection.addEventListener('click', handleClearResultsSelection);
    }
    const failureModalClose = document.querySelector('#failureModalClose');
    const failureModalOverlay = document.querySelector('#failureModalOverlay');
    if (failureModalClose) {
        failureModalClose.addEventListener('click', closeFailureModal);
    }
    if (failureModalOverlay) {
        failureModalOverlay.addEventListener('click', closeFailureModal);
    }
    const retryFailureBatch = document.querySelector('#retryFailureBatch');
    if (retryFailureBatch) {
        retryFailureBatch.addEventListener('click', handleRetryFailureBatch);
    }
    const failureExportCsv = document.querySelector('#failureExportCsv');
    if (failureExportCsv) {
        failureExportCsv.addEventListener('click', handleExportFailureCsv);
    }
    document.addEventListener('keydown', handleKeyboardShortcuts);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            connectSSE();
            refreshPapers();
            loadRecentFailures();
            loadFailureSummary();
        }
    });
    window.addEventListener('focus', () => {
        connectSSE();
        refreshPapers();
        loadRecentFailures();
        loadFailureSummary();
    });
    
    // Provider selector
    $('#providerSelect').addEventListener('change', (e) => {
        setSelectedProvider(e.target.value);
    });
    
    // Start batch extraction
    $('#startBatchBtn').addEventListener('click', handleStartBatch);
    
    // Drawer
    $('#closeDrawerBtn').addEventListener('click', () => closeDrawer());
    $('#drawerOverlay').addEventListener('click', () => closeDrawer());
}

function initStateSubscriptions() {
    appStore.subscribe((state, prev) => {
        // Search results changed
        if (
            state.searchResults !== prev.searchResults ||
            state.selectedPapers !== prev.selectedPapers ||
            state.isSearching !== prev.isSearching
        ) {
            renderSearchResults(state.searchResults, state.selectedPapers, handleTogglePaper, state.isSearching);
            renderBatchCount(state.selectedPapers.size);
        }
        
        // Papers table changed
        if (state.papers !== prev.papers) {
            renderFilteredPapers(state.papers);
        }
        
        // Queue stats changed
        if (state.queueStats !== prev.queueStats) {
            renderQueueStats(state.queueStats);
        }
        
        // Drawer state changed
        if (state.drawerOpen !== prev.drawerOpen) {
            setDrawerOpen(state.drawerOpen);
        }
        if (state.drawerPaper !== prev.drawerPaper || state.drawerRuns !== prev.drawerRuns) {
            renderDrawer(state.drawerPaper, state.drawerRuns);
        }
    });
}

function connectSSE() {
    if (sseConnection) {
        sseConnection.close();
    }
    renderConnectionBadge('connecting');
    
    sseConnection = api.createSSEConnection(
        (message) => {
            console.log('SSE message:', message);
            
            if (message.event === 'run_status') {
                const { run_id, paper_id, status, failure_reason } = message.data;
                updatePaperStatus(paper_id, run_id, status, failure_reason);
                syncSearchResultsWithPapers(appStore.get('papers'));
                
                // Update drawer if open for this paper
                if (appStore.get('drawerPaperId') === paper_id) {
                    loadPaperDetails(paper_id);
                }
                loadRecentFailures();
                if (status === 'failed') {
                    loadFailureSummary();
                }
            }
        },
        (error) => {
            console.error('SSE error, reconnecting in 5s...');
            renderConnectionBadge('reconnecting');
            setTimeout(connectSSE, 5000);
        }
    );
    sseConnection.onopen = () => renderConnectionBadge('connected');
}

function setSearchStatus(message, loading = false) {
    const status = document.querySelector('#searchStatus');
    const spinner = document.querySelector('#searchSpinner');
    if (status) status.textContent = message || '';
    if (spinner) {
        spinner.classList.toggle('hidden', !loading);
    }
}

function handleSelectAllResults() {
    const results = appStore.get('searchResults') || [];
    const selected = new Map();
    results.forEach((item) => {
        const key = item.pdf_url || item.url;
        if (item.pdf_url && key) {
            selected.set(key, item);
        }
    });
    setSelectedPapers(selected);
}

function handleClearResultsSelection() {
    clearBatchSelection();
}

function syncSearchResultsWithPapers(papers) {
    const results = appStore.get('searchResults');
    if (!Array.isArray(results) || results.length === 0) return;
    const byDoi = new Map();
    const byUrl = new Map();
    (papers || []).forEach((paper) => {
        if (paper.doi) byDoi.set(paper.doi, paper);
        if (paper.url) byUrl.set(paper.url, paper);
    });

    const updated = results.map((item) => {
        const paper = (item.doi && byDoi.get(item.doi)) || (item.url && byUrl.get(item.url)) || null;
        if (!paper) return item;
        const queueStatus = paper.status || null;
        return {
            ...item,
            seen: true,
            processed: queueStatus === 'stored' ? true : item.processed,
            queue_status: queueStatus,
        };
    });
    setSearchResults(updated);
}

function applyPaperFilters(papers) {
    const query = paperFilters.query.trim().toLowerCase();
    const statusFilter = paperFilters.status;
    const sourceFilter = paperFilters.source;
    const sortFilter = paperFilters.sort || 'recent';

    let filtered = Array.isArray(papers) ? papers : [];
    if (query) {
        filtered = filtered.filter((paper) => {
            const title = (paper.title || '').toLowerCase();
            const doi = (paper.doi || '').toLowerCase();
            return title.includes(query) || doi.includes(query);
        });
    }
    if (statusFilter) {
        if (statusFilter === 'processing') {
            const processing = new Set(['fetching', 'provider', 'validating']);
            filtered = filtered.filter((paper) => processing.has(paper.status));
        } else if (statusFilter === 'none') {
            filtered = filtered.filter((paper) => !paper.status);
        } else {
            filtered = filtered.filter((paper) => paper.status === statusFilter);
        }
    }
    if (sourceFilter) {
        filtered = filtered.filter((paper) => paper.source === sourceFilter);
    }

    const sorted = [...filtered];
    if (sortFilter === 'oldest') {
        sorted.sort((a, b) => {
            const aTime = a.last_run_at ? Date.parse(a.last_run_at) : 0;
            const bTime = b.last_run_at ? Date.parse(b.last_run_at) : 0;
            return aTime - bTime;
        });
    } else if (sortFilter === 'runs') {
        sorted.sort((a, b) => (b.run_count || 0) - (a.run_count || 0));
    } else {
        sorted.sort((a, b) => {
            const aTime = a.last_run_at ? Date.parse(a.last_run_at) : 0;
            const bTime = b.last_run_at ? Date.parse(b.last_run_at) : 0;
            return bTime - aTime;
        });
    }

    return sorted;
}

function applyPaperPreset(status) {
    paperFilters.status = status;
    paperFilters.sort = 'recent';
    syncPaperFilterInputs();
    renderFilteredPapers();
}

function syncPaperFilterInputs() {
    const papersFilterInput = document.querySelector('#papersFilterInput');
    const papersFilterStatus = document.querySelector('#papersFilterStatus');
    const papersFilterSource = document.querySelector('#papersFilterSource');
    const papersFilterSort = document.querySelector('#papersFilterSort');
    if (papersFilterInput) papersFilterInput.value = paperFilters.query;
    if (papersFilterStatus) papersFilterStatus.value = paperFilters.status;
    if (papersFilterSource) papersFilterSource.value = paperFilters.source;
    if (papersFilterSort) papersFilterSort.value = paperFilters.sort || 'recent';
}

function persistPaperFilters() {
    try {
        localStorage.setItem(PAPER_FILTERS_STORAGE_KEY, JSON.stringify(paperFilters));
    } catch {
        // ignore
    }
}

function hydratePaperFilters() {
    try {
        const raw = localStorage.getItem(PAPER_FILTERS_STORAGE_KEY);
        if (!raw) {
            syncPaperFilterInputs();
            return;
        }
        const stored = JSON.parse(raw);
        if (stored && typeof stored === 'object') {
            paperFilters.query = stored.query || '';
            paperFilters.status = stored.status || '';
            paperFilters.source = stored.source || '';
            paperFilters.sort = stored.sort || 'recent';
        }
    } catch {
        // ignore
    }
    if (sanitizePaperFilters()) {
        persistPaperFilters();
    }
    syncPaperFilterInputs();
}

function sanitizePaperFilters() {
    let changed = false;
    if (typeof paperFilters.query !== 'string') {
        paperFilters.query = '';
        changed = true;
    }
    if (!PAPER_FILTERS_ALLOWED_STATUS.has(paperFilters.status)) {
        paperFilters.status = '';
        changed = true;
    }
    if (!PAPER_FILTERS_ALLOWED_SOURCE.has(paperFilters.source)) {
        paperFilters.source = '';
        changed = true;
    }
    if (!PAPER_FILTERS_ALLOWED_SORT.has(paperFilters.sort)) {
        paperFilters.sort = 'recent';
        changed = true;
    }
    return changed;
}

function filtersActive() {
    return Boolean(
        paperFilters.query.trim()
        || paperFilters.status
        || paperFilters.source
    );
}

function updatePaperFilterCount(filteredCount, totalCount) {
    const countEl = document.querySelector('#papersFilterCount');
    const clearBtn = document.querySelector('#papersFilterClear');
    if (countEl) {
        if (!totalCount) {
            countEl.textContent = 'No papers yet';
        } else if (filteredCount === totalCount && !filtersActive()) {
            countEl.textContent = `${totalCount} papers`;
        } else {
            countEl.textContent = `Showing ${filteredCount} of ${totalCount}`;
        }
    }
    if (clearBtn) {
        clearBtn.classList.toggle('hidden', !filtersActive());
    }
}

function updatePaperFilterNotice(filteredCount, totalCount) {
    const notice = document.querySelector('#papersFilterNotice');
    if (!notice) return;
    const shouldShow = totalCount > 0 && filteredCount === 0 && filtersActive();
    notice.classList.toggle('hidden', !shouldShow);
}

function renderFilteredPapers(papers = appStore.get('papers')) {
    const filtered = applyPaperFilters(papers);
    const emptyMessage = filtersActive()
        ? 'No papers match these filters. Click Clear filters to show all papers.'
        : 'No papers yet. Search and extract papers to see them here.';
    renderPapersTable(filtered, handlePaperClick, { emptyMessage });
    updatePaperFilterCount(filtered.length, papers.length || 0);
    updatePaperFilterNotice(filtered.length, papers.length || 0);
    persistPaperFilters();
}

function isTypingTarget(target) {
    if (!target) return false;
    const tag = target.tagName ? target.tagName.toLowerCase() : '';
    if (['input', 'textarea', 'select'].includes(tag)) return true;
    if (target.isContentEditable) return true;
    return false;
}

function handleKeyboardShortcuts(e) {
    if (e.key === 'Escape' && failureModalState) {
        closeFailureModal();
        return;
    }
    if (isTypingTarget(e.target)) {
        return;
    }
    const key = e.key.toLowerCase();
    const hasModifiers = e.ctrlKey || e.metaKey || e.altKey;
    if (key === '/' && !hasModifiers) {
        const input = document.querySelector('#queryInput');
        if (input) {
            e.preventDefault();
            input.focus();
            input.select();
        }
        return;
    }
    if (key === 'f' && !hasModifiers && !e.shiftKey) {
        const input = document.querySelector('#papersFilterInput');
        if (input) {
            e.preventDefault();
            input.focus();
            input.select();
        }
        return;
    }
    if (!e.shiftKey || hasModifiers) return;

    if (key === 'f') {
        applyPaperPreset('failed');
        return;
    }
    if (key === 'p') {
        applyPaperPreset('processing');
        return;
    }
    if (key === 'n') {
        applyPaperPreset('none');
        return;
    }
    if (key === 'c') {
        paperFilters.query = '';
        paperFilters.status = '';
        paperFilters.source = '';
        paperFilters.sort = 'recent';
        syncPaperFilterInputs();
        renderFilteredPapers();
        return;
    }
    if (key === 'e') {
        if (failureModalState) {
            handleExportFailureCsv();
        } else {
            handleExportPapersCsv();
        }
        return;
    }
    if (key === 'r' && failureModalState) {
        handleRetryFailureBatch();
    }
}

function escapeCsv(value) {
    if (value === null || value === undefined) return '';
    const text = String(value);
    if (text.includes('"') || text.includes(',') || text.includes('\n')) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}

function handleExportPapersCsv() {
    const papers = appStore.get('papers');
    const filtered = applyPaperFilters(papers);
    if (!filtered.length) {
        alert('No papers to export for the current filters.');
        return;
    }
    const headers = [
        'title',
        'doi',
        'source',
        'year',
        'status',
        'run_count',
        'latest_run_id',
        'last_run_at',
        'pdf_url',
        'url',
        'failure_reason',
    ];
    const rows = filtered.map((paper) => [
        paper.title,
        paper.doi,
        paper.source,
        paper.year,
        paper.status,
        paper.run_count,
        paper.latest_run_id,
        paper.last_run_at,
        paper.pdf_url,
        paper.url,
        paper.failure_reason,
    ]);
    const csvLines = [
        headers.join(','),
        ...rows.map((row) => row.map(escapeCsv).join(',')),
    ];
    const blob = new Blob([csvLines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const date = new Date();
    const stamp = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    link.href = url;
    link.download = `papers_filtered_${stamp}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function handleSearch() {
    const query = $('#queryInput').value.trim();
    if (!query) return;
    
    setSearchCount('Searching...');
    setSearching(true);
    clearBatchSelection();
    setSearchStatus('Searching sources...', true);
    
    try {
        const data = await api.search(query);
        setSearchResults(data.results);
        markMilestone(DASHBOARD_ONBOARDING_KEY, 'searched');
        renderOnboarding();
        updateContextHint();
        setSearchCount(`${data.results.length} results`);
        setSearchStatus(data.results.length ? `Found ${data.results.length} results.` : 'No results found.');
    } catch (e) {
        setSearchResults([]);
        setSearchCount('Search failed');
        setSearchStatus('Search failed.');
        alert(e.message || 'Search failed');
    } finally {
        setSearchStatus(document.querySelector('#searchStatus')?.textContent || '', false);
    }
}

function handleTogglePaper(paper) {
    togglePaperSelection(paper);
}

async function handleStartBatch() {
    const papers = getSelectedPapers();
    if (papers.length === 0) return;
    
    const provider = getSelectedProvider();
    
    // Prepare papers for enqueue
    const enqueueItems = papers.map(p => ({
        title: p.title,
        doi: p.doi,
        url: p.url,
        pdf_url: p.pdf_url,
        source: p.source,
        year: p.year,
        authors: p.authors || [],
        force: false, // Don't force re-extract by default
    }));
    
    try {
        const result = await api.enqueue(enqueueItems, provider);
        console.log('Enqueue result:', result);
        
        const selectedKeys = new Set(papers.map(p => p.pdf_url || p.url));
        const updatedResults = (appStore.get('searchResults') || []).map((item) => {
            const key = item.pdf_url || item.url;
            if (selectedKeys.has(key)) {
                return { ...item, queued: true, seen: true, queue_status: 'queued' };
            }
            return item;
        });
        setSearchResults(updatedResults);

        // Clear selection
        clearBatchSelection();
        
        // Refresh papers table to show new items
        await refreshPapers();
        markMilestone(DASHBOARD_ONBOARDING_KEY, 'enqueued');
        renderOnboarding();
        updateContextHint();
        
        // Show feedback
        if (result.skipped > 0) {
            alert(`Enqueued ${result.enqueued} papers (${result.skipped} already processed)`);
        }
    } catch (e) {
        alert(e.message || 'Failed to start extraction');
    }
}

async function handlePaperClick(paperId) {
    openDrawer(paperId);
    await loadPaperDetails(paperId);
    markMilestone(DASHBOARD_ONBOARDING_KEY, 'opened_paper');
    renderOnboarding();
    updateContextHint();
}

async function loadPaperDetails(paperId) {
    try {
        const data = await api.getRuns(paperId);
        setDrawerContent(data.paper, data.runs || []);
    } catch (e) {
        console.error('Failed to load paper details:', e);
        setDrawerContent({ title: 'Error loading paper' }, []);
    }
}

async function handleRetryRun(runId) {
    try {
        const result = await api.retryRun(runId);
        console.log('Retry result:', result);
        
        // Refresh the drawer to show updated status
        const paperId = appStore.get('drawerPaperId');
        if (paperId) {
            await loadPaperDetails(paperId);
        }
        
        // Refresh papers table
        await refreshPapers();
        await loadRecentFailures();
    } catch (e) {
        console.error('Failed to retry run:', e);
        alert(e.message || 'Failed to retry run');
    }
}

async function loadRecentFailures() {
    const list = document.querySelector('#recentFailuresList');
    const empty = document.querySelector('#recentFailuresEmpty');
    if (!list || !empty) return;
    try {
        const data = await api.getRecentRuns('failed', 10);
        list.innerHTML = '';
        const runs = data.runs || [];
        if (!runs.length) {
            empty.classList.remove('hidden');
            return;
        }
        empty.classList.add('hidden');
        runs.forEach((run) => {
            const row = document.createElement('div');
            row.className = 'sw-row sw-card sw-card--danger border-l-red-400 p-4 flex items-start justify-between gap-4';
            const info = document.createElement('div');
            info.className = 'text-xs text-slate-600';
            const title = run.paper?.title || `Paper ${run.paper_id || ''}`;
            const meta = [run.paper?.doi, run.paper?.source, run.paper?.year].filter(Boolean).join(' · ');
            info.innerHTML = `
                <div class="text-sm font-medium text-slate-800">${title}</div>
                <div class="text-xs text-slate-500 mt-1">${meta}</div>
                <div class="text-xs text-red-600 mt-2">${run.failure_reason || 'Unknown failure'}</div>
            `;
            const actions = document.createElement('div');
            actions.className = 'flex flex-col gap-2 text-xs';
            const open = document.createElement('a');
            open.className = 'inline-flex items-center justify-center px-3 py-1.5 rounded-md border border-slate-200 text-xs text-indigo-600 hover:bg-indigo-50';
            open.href = `/runs/${run.id}`;
            open.target = '_blank';
            open.textContent = 'Open run';
            const retry = document.createElement('button');
            retry.className = 'inline-flex items-center justify-center px-3 py-1.5 rounded-md border border-red-200 text-xs text-red-700 hover:bg-red-50';
            retry.textContent = 'Retry';
            retry.addEventListener('click', async () => {
                await api.retryRun(run.id);
                await refreshPapers();
                await loadRecentFailures();
            });
            actions.appendChild(open);
            actions.appendChild(retry);
            row.appendChild(info);
            row.appendChild(actions);
            list.appendChild(row);
        });
    } catch (err) {
        empty.classList.remove('hidden');
        empty.textContent = 'Failed to load recent failures.';
    }
}

function renderFailureGroup(title, items, options = {}) {
    const section = document.createElement('div');
    section.className = `space-y-3 ${options.fullWidth ? 'md:col-span-3' : ''}`;
    const heading = document.createElement('div');
    heading.className = 'sw-kicker text-[11px] text-slate-400';
    heading.textContent = title;
    section.appendChild(heading);

    if (!items || items.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'text-xs text-slate-400';
        empty.textContent = 'No data';
        section.appendChild(empty);
        return section;
    }

    const maxCount = Math.max(...items.map(item => item.count || 0), 1);
    items.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'sw-row px-3 py-2 flex items-center justify-between gap-3';

        const label = document.createElement('div');
        label.className = 'flex-1 min-w-0';

        const labelText = document.createElement('div');
        labelText.className = 'text-slate-700 truncate';
        labelText.textContent = item.label || item.key;

        const bar = document.createElement('div');
        bar.className = 'sw-meter h-1 mt-1 rounded-full overflow-hidden';
        const fill = document.createElement('div');
        fill.className = 'sw-meter__fill h-full';
        const ratio = Math.round((item.count / maxCount) * 100);
        fill.style.width = `${Math.max(ratio, 8)}%`;
        bar.appendChild(fill);

        label.appendChild(labelText);
        label.appendChild(bar);

        const meta = document.createElement('div');
        meta.className = 'flex items-center gap-2 text-xs text-slate-500';
        const count = document.createElement('div');
        count.className = 'text-slate-700 font-medium';
        count.textContent = String(item.count);
        meta.appendChild(count);

        if (item.example_run_id) {
            const link = document.createElement('a');
            link.className = 'text-indigo-600 hover:underline';
            link.href = `/runs/${item.example_run_id}`;
            link.target = '_blank';
            link.textContent = 'Open';
            meta.appendChild(link);
        }
        if (options.onSelect) {
            const view = document.createElement('button');
            view.className = 'text-indigo-600 hover:underline';
            view.textContent = 'View';
            view.addEventListener('click', () => options.onSelect(item));
            meta.appendChild(view);
        }

        row.appendChild(label);
        row.appendChild(meta);
        section.appendChild(row);
    });

    return section;
}

function renderFailureSummary(summary) {
    const container = document.querySelector('#failureSummaryBody');
    const empty = document.querySelector('#failureSummaryEmpty');
    if (!container || !empty) return;
    container.innerHTML = '';

    if (!summary || !summary.total_failed) {
        empty.classList.remove('hidden');
        return;
    }

    empty.classList.add('hidden');
    const windowStart = summary.window_start ? new Date(summary.window_start) : null;
    const meta = document.createElement('div');
    meta.className = 'md:col-span-3 text-xs text-slate-500';
    const windowLabel = windowStart ? windowStart.toLocaleDateString() : 'unknown';
    meta.textContent = `Failed runs: ${summary.total_failed}. Last ${summary.window_days} days (since ${windowLabel}).`;
    container.appendChild(meta);

    container.appendChild(renderFailureGroup('By category', summary.buckets, {
        onSelect: (item) => openFailureModal({ bucket: item.key }, `Category: ${item.label || item.key}`),
    }));
    container.appendChild(renderFailureGroup('By provider', summary.providers, {
        onSelect: (item) => openFailureModal({ provider: item.key }, `Provider: ${item.label || item.key}`),
    }));
    container.appendChild(renderFailureGroup('By source', summary.sources, {
        onSelect: (item) => openFailureModal({ source: item.key }, `Source: ${item.label || item.key}`),
    }));
    container.appendChild(renderFailureGroup('Top reasons', (summary.reasons || []).slice(0, 6), {
        fullWidth: true,
        onSelect: (item) => openFailureModal({ reason: item.key }, `Reason: ${item.label || item.key}`),
    }));
}

function openFailureModal(filters, label) {
    const modal = document.querySelector('#failureModal');
    const title = document.querySelector('#failureModalTitle');
    const meta = document.querySelector('#failureModalMeta');
    if (!modal || !title || !meta) return;
    failureModalState = { filters: filters || {}, label: label || 'Failure drilldown' };
    title.textContent = failureModalState.label;
    meta.textContent = 'Loading...';
    updateFailureModalRetryState(0);
    updateFailureModalExportState(0);
    modal.classList.remove('hidden');
    document.body.style.overflow = 'hidden';
    loadFailureModalRuns();
}

function closeFailureModal() {
    const modal = document.querySelector('#failureModal');
    if (!modal) return;
    modal.classList.add('hidden');
    document.body.style.overflow = '';
    failureModalState = null;
    failureModalItems = [];
}

function renderFailureModalList(items, days) {
    const list = document.querySelector('#failureModalList');
    const empty = document.querySelector('#failureModalEmpty');
    const meta = document.querySelector('#failureModalMeta');
    if (!list || !empty || !meta) return;
    list.innerHTML = '';

    if (!items || items.length === 0) {
        empty.classList.remove('hidden');
        meta.textContent = `No failures found in the last ${days} days.`;
        updateFailureModalRetryState(0);
        updateFailureModalExportState(0);
        failureModalItems = [];
        return;
    }

    empty.classList.add('hidden');
    meta.textContent = `Showing ${items.length} runs from the last ${days} days.`;
    updateFailureModalRetryState(items.length);
    updateFailureModalExportState(items.length);
    failureModalItems = items.slice();
    items.forEach((run) => {
        const row = document.createElement('div');
        row.className = 'sw-row sw-card sw-card--danger border-l-red-400 p-4 flex items-start justify-between gap-4';

        const info = document.createElement('div');
        info.className = 'text-xs text-slate-600';
        const title = run.paper_title || `Paper ${run.paper_id || ''}`;
        const metaLine = [run.paper_doi, run.paper_source, run.paper_year, run.model_provider].filter(Boolean).join(' · ');
        const reason = run.normalized_reason || run.failure_reason || 'Unknown failure';
        info.innerHTML = `
            <div class="text-sm font-medium text-slate-800">${title}</div>
            <div class="text-xs text-slate-500 mt-1">${metaLine}</div>
            <div class="sw-kicker text-[11px] text-slate-500 mt-1">${run.bucket || 'unknown'}</div>
            <div class="text-xs text-red-600 mt-2">${reason}</div>
        `;

        const actions = document.createElement('div');
        actions.className = 'flex flex-col gap-2 text-xs';
        const open = document.createElement('a');
        open.className = 'inline-flex items-center justify-center px-3 py-1.5 rounded-md border border-slate-200 text-xs text-indigo-600 hover:bg-indigo-50';
        open.href = `/runs/${run.id}`;
        open.target = '_blank';
        open.textContent = 'Open';
        const retry = document.createElement('button');
        retry.className = 'inline-flex items-center justify-center px-3 py-1.5 rounded-md border border-red-200 text-xs text-red-700 hover:bg-red-50';
        retry.textContent = 'Retry';
        retry.addEventListener('click', async () => {
            await api.retryRun(run.id);
            await refreshPapers();
            await loadRecentFailures();
            await loadFailureSummary();
            await loadFailureModalRuns();
        });
        actions.appendChild(open);
        actions.appendChild(retry);

        row.appendChild(info);
        row.appendChild(actions);
        list.appendChild(row);
    });
}

function updateFailureModalRetryState(count) {
    const button = document.querySelector('#retryFailureBatch');
    const countEl = document.querySelector('#retryFailureBatchCount');
    if (!button || !countEl) return;
    if (!count) {
        button.disabled = true;
        countEl.textContent = '';
        return;
    }
    button.disabled = false;
    countEl.textContent = `(${count})`;
}

async function handleRetryFailureBatch() {
    if (!failureModalState) return;
    const select = document.querySelector('#failureWindow');
    const days = Number.parseInt(select?.value || '30', 10);
    const countEl = document.querySelector('#retryFailureBatchCount');
    const countText = countEl?.textContent?.replace(/[()]/g, '') || '';
    const count = Number.parseInt(countText, 10) || 0;
    if (!count) return;
    if (!confirm(`Retry ${count} failed runs?`)) return;

    try {
        const result = await api.retryFailedRuns({
            ...failureModalState.filters,
            days,
            limit: count,
            maxRuns: 1000,
        });
        await refreshPapers();
        await loadRecentFailures();
        await loadFailureSummary();
        await loadFailureModalRuns();
        alert(`Re-queued ${result.enqueued} runs. Skipped ${result.skipped}.`);
    } catch (err) {
        alert('Failed to retry this failure batch.');
    }
}

function updateFailureModalExportState(count) {
    const button = document.querySelector('#failureExportCsv');
    if (!button) return;
    button.disabled = !count;
}

function handleExportFailureCsv() {
    if (!failureModalItems.length) {
        alert('No failures to export for the current filter.');
        return;
    }
    const headers = [
        'title',
        'doi',
        'source',
        'year',
        'bucket',
        'normalized_reason',
        'model_provider',
        'created_at',
        'run_id',
        'paper_id',
        'paper_url',
        'failure_reason',
    ];
    const rows = failureModalItems.map((run) => [
        run.paper_title,
        run.paper_doi,
        run.paper_source,
        run.paper_year,
        run.bucket,
        run.normalized_reason,
        run.model_provider,
        run.created_at,
        run.id,
        run.paper_id,
        run.paper_url,
        run.failure_reason,
    ]);
    const csvLines = [
        headers.join(','),
        ...rows.map((row) => row.map(escapeCsv).join(',')),
    ];
    const blob = new Blob([csvLines.join('\n')], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    const date = new Date();
    const stamp = `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;
    link.href = url;
    link.download = `failures_filtered_${stamp}.csv`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
}

async function loadFailureModalRuns() {
    if (!failureModalState) return;
    const list = document.querySelector('#failureModalList');
    const empty = document.querySelector('#failureModalEmpty');
    const select = document.querySelector('#failureWindow');
    if (!list || !empty) return;
    const days = Number.parseInt(select?.value || '30', 10);
    list.innerHTML = '<div class="p-4 text-xs text-slate-500">Loading failures...</div>';
    try {
        const data = await api.getFailedRuns({
            ...failureModalState.filters,
            days,
            limit: 50,
            maxRuns: 1000,
        });
        renderFailureModalList(data.items || [], days);
    } catch (err) {
        list.innerHTML = '';
        empty.classList.remove('hidden');
        empty.textContent = 'Failed to load failure drilldown.';
    }
}

async function loadFailureSummary() {
    const container = document.querySelector('#failureSummaryBody');
    const empty = document.querySelector('#failureSummaryEmpty');
    const select = document.querySelector('#failureWindow');
    if (!container || !empty) return;
    const days = Number.parseInt(select?.value || '30', 10);
    container.innerHTML = '<div class="md:col-span-3 text-xs text-slate-500">Loading failure summary...</div>';
    try {
        const summary = await api.getFailureSummary(days, 1000);
        renderFailureSummary(summary);
        if (failureModalState) {
            await loadFailureModalRuns();
        }
    } catch (err) {
        container.innerHTML = '';
        empty.classList.remove('hidden');
        empty.textContent = 'Failed to load failure summary.';
    }
}

async function handleForceReextract(paperId) {
    try {
        const result = await api.forceReextract(paperId);
        console.log('Force re-extract result:', result);
        
        // Refresh the drawer to show new run
        await loadPaperDetails(paperId);
        
        // Refresh papers table
        await refreshPapers();
    } catch (e) {
        console.error('Failed to force re-extract:', e);
        alert(e.message || 'Failed to force re-extract');
    }
}

async function refreshPapers() {
    try {
        const data = await api.getPapers();
        setPapers(data.papers, data.queue_stats);
        syncSearchResultsWithPapers(data.papers || []);
    } catch (e) {
        console.error('Failed to load papers:', e);
    }
}

// Start the app
init();
