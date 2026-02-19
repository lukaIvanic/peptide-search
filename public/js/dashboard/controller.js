/**
 * Main application entry point.
 */

import * as searchActions from './actions/search_actions.js';
import * as runActions from './actions/run_actions.js';
import * as promptActions from './actions/prompt_actions.js';
import * as systemActions from './actions/system_actions.js';
import { initTour } from '../tour.js';
import { markMilestone, renderChecklist, resetMilestones } from '../onboarding.js';
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
    setSelectedModel,
    getSelectedModel,
    setProviderCatalog,
    getProviderCatalog,
    setPrompts,
    setSelectedPrompt,
    getSelectedPrompt,
    setPapers,
    updatePaperStatus,
    addPaperToList,
    openDrawer,
    closeDrawer,
    setDrawerContent,
} from './state_facade.js';
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
    applyPaperFilters,
    escapeCsv,
    filtersActive,
    hydratePaperFilters,
    paperFilters,
    persistPaperFilters,
    syncPaperFilterInputs,
    updatePaperFilterCount,
    updatePaperFilterNotice,
} from './views/dashboard_views.js';

const api = {
    ...searchActions,
    ...runActions,
    ...promptActions,
    ...systemActions,
};

let sseConnection = null;
let failureModalState = null;
let failureModalItems = [];
const DASHBOARD_ONBOARDING_KEY = 'onboarding_dashboard_v1';
const DASHBOARD_STEPS = [
    { key: 'searched', label: 'Run a search' },
    { key: 'enqueued', label: 'Start batch extraction' },
    { key: 'opened_paper', label: 'Open a paper drawer' },
];
const SIDE_DRAWERS = {
    onboarding: {
        drawer: '#onboardingDrawer',
        openBtn: '#openOnboardingDrawer',
        closeBtn: '#closeOnboardingDrawer',
    },
    prompt: {
        drawer: '#promptDrawer',
        openBtn: '#openPromptDrawer',
        closeBtn: '#closePromptDrawer',
    },
    failure: {
        drawer: '#failureDrawer',
        openBtn: '#openFailureDrawer',
        closeBtn: '#closeFailureDrawer',
    },
};
const CREATE_PROMPT_OPTION = '__create__';

const BLOCKING_ERROR_ID = 'blockingError';

function getProviderModels(providerId) {
    const catalog = getProviderCatalog();
    const row = catalog.find((item) => item.provider_id === providerId);
    const seen = new Set();
    const models = [];
    for (const candidate of [row?.default_model, ...(row?.curated_models || [])]) {
        const model = (candidate || '').trim();
        if (!model || seen.has(model)) continue;
        seen.add(model);
        models.push(model);
    }
    return models;
}

function hydrateProviderModelSelect(providerId, preserveSelection = true) {
    const modelSelect = $('#providerModelSelect');
    if (!modelSelect) return;

    const models = getProviderModels(providerId);
    const previous = preserveSelection ? (getSelectedModel() || modelSelect.value || '') : '';

    modelSelect.innerHTML = '';
    if (!models.length) {
        const fallback = document.createElement('option');
        fallback.value = '';
        fallback.textContent = 'Provider default';
        modelSelect.appendChild(fallback);
        modelSelect.value = '';
        setSelectedModel('');
        return;
    }

    for (const model of models) {
        const option = document.createElement('option');
        option.value = model;
        option.textContent = model;
        modelSelect.appendChild(option);
    }

    const next = previous && models.includes(previous) ? previous : models[0];
    modelSelect.value = next;
    setSelectedModel(next);
}

function hydrateProviderSelectors() {
    const select = $('#providerSelect');
    const catalog = getProviderCatalog().filter((item) => item.enabled);
    if (!select || !catalog.length) {
        return;
    }

    const previous = getSelectedProvider() || select.value;

    select.innerHTML = '';
    for (const item of catalog) {
        const option = document.createElement('option');
        option.value = item.provider_id;
        option.textContent = item.label || item.provider_id;
        option.dataset.defaultModel = item.default_model || '';
        select.appendChild(option);
    }

    const selected = catalog.some((item) => item.provider_id === previous)
        ? previous
        : catalog[0].provider_id;
    select.value = selected;
    setSelectedProvider(selected);
    hydrateProviderModelSelect(selected, true);
}

function shouldRefreshProviderCatalog(catalog = []) {
    if (!Array.isArray(catalog) || !catalog.length) return false;
    for (const item of catalog) {
        if (!item?.enabled) continue;
        if (item.provider_id !== 'gemini' && item.provider_id !== 'openrouter') continue;
        const models = item.curated_models || [];
        if (models.length <= 1) return true;
    }
    return false;
}

async function loadProviderCatalog() {
    try {
        const payload = await api.getProviders();
        let providers = payload.providers || [];
        if (shouldRefreshProviderCatalog(providers)) {
            const refreshed = await api.refreshProviders();
            providers = refreshed.providers || providers;
        }
        setProviderCatalog(providers);
        hydrateProviderSelectors();
    } catch (err) {
        console.error('Failed to load providers:', err);
    }
}

function showBlockingError(title, message, detail) {
    let overlay = document.querySelector(`#${BLOCKING_ERROR_ID}`);
    if (!overlay) {
        overlay = document.createElement('div');
        overlay.id = BLOCKING_ERROR_ID;
        overlay.className = 'fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-6';
        overlay.innerHTML = `
            <div class="sw-card w-full max-w-xl p-6 space-y-3">
                <div class="text-lg font-semibold text-slate-100" data-error-title></div>
                <p class="text-sm text-slate-300" data-error-message></p>
                <pre class="text-xs text-slate-400 whitespace-pre-wrap hidden" data-error-detail></pre>
                <div class="flex items-center gap-2 pt-2">
                    <button type="button" class="sw-btn sw-btn--primary" data-error-reload>Reload</button>
                </div>
            </div>
        `;
        document.body.appendChild(overlay);
        const reloadBtn = overlay.querySelector('[data-error-reload]');
        if (reloadBtn) {
            reloadBtn.addEventListener('click', () => window.location.reload());
        }
    }

    const titleEl = overlay.querySelector('[data-error-title]');
    const messageEl = overlay.querySelector('[data-error-message]');
    const detailEl = overlay.querySelector('[data-error-detail]');
    if (titleEl) titleEl.textContent = title || 'Blocking error';
    if (messageEl) messageEl.textContent = message || 'An unrecoverable error occurred.';
    if (detailEl) {
        if (detail) {
            detailEl.textContent = detail;
            detailEl.classList.remove('hidden');
        } else {
            detailEl.textContent = '';
            detailEl.classList.add('hidden');
        }
    }
}

function appendCreatePromptOption(select) {
    const option = document.createElement('option');
    option.value = CREATE_PROMPT_OPTION;
    option.textContent = 'Create new prompt…';
    select.appendChild(option);
}

// Initialize application
export async function initDashboard() {
    await loadProviderCatalog();

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
        onResolveSource: handleResolveRunSource,
        onUpload: handleUploadRunFile,
        onRetryWithSource: handleRetryRunWithResolved,
    });
    
    // Setup event handlers
    initEventHandlers();
    initTourGuide();
    renderOnboarding();
    initContextHints();
    try {
        await loadPrompts();
    } catch (err) {
        console.error('Failed to load prompts:', err);
        return;
    }
    
    // Subscribe to state changes
    initStateSubscriptions();
    
    // Connect to SSE for live updates
    connectSSE();
    
    // Initial data load
    await refreshPapers();
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

function setSideDrawerOpen(key, isOpen) {
    const config = SIDE_DRAWERS[key];
    if (!config) return;
    const drawer = document.querySelector(config.drawer);
    if (!drawer) return;
    drawer.classList.toggle('sw-side-drawer--open', isOpen);
    drawer.setAttribute('aria-hidden', String(!isOpen));
    const trigger = document.querySelector(config.openBtn);
    if (trigger) {
        trigger.classList.toggle('is-active', isOpen);
        trigger.setAttribute('aria-pressed', String(isOpen));
    }
}

function closeAllSideDrawers(exceptKey = null) {
    Object.keys(SIDE_DRAWERS).forEach((key) => {
        if (key === exceptKey) return;
        setSideDrawerOpen(key, false);
    });
}

function openSideDrawer(key, options = {}) {
    closeAllSideDrawers(key);
    setSideDrawerOpen(key, true);
    if (options.focusSelector) {
        const target = document.querySelector(options.focusSelector);
        if (target) {
            setTimeout(() => target.focus(), 150);
        }
    }
}

function closeSideDrawer(key) {
    setSideDrawerOpen(key, false);
}

function closeAnySideDrawer() {
    let closed = false;
    Object.keys(SIDE_DRAWERS).forEach((key) => {
        const drawer = document.querySelector(SIDE_DRAWERS[key].drawer);
        if (drawer && drawer.classList.contains('sw-side-drawer--open')) {
            setSideDrawerOpen(key, false);
            closed = true;
        }
    });
    return closed;
}

function setPromptStatus(message, isError = false) {
    const status = document.querySelector('#promptCreateStatus');
    if (!status) return;
    status.textContent = message || '';
    if (!message) return;
    status.classList.toggle('text-red-600', isError);
    status.classList.toggle('text-slate-500', !isError);
}

function renderPromptSelect(prompts, activePromptId, selectedPromptId) {
    const select = document.querySelector('#promptSelect');
    const manageBtn = document.querySelector('#promptManageBtn');
    if (!select) return;
    select.innerHTML = '';
    if (!prompts || prompts.length === 0) {
        const option = document.createElement('option');
        option.value = '';
        option.textContent = 'No prompts available';
        select.appendChild(option);
        appendCreatePromptOption(select);
        select.disabled = false;
        if (manageBtn) manageBtn.textContent = 'Create prompt';
        return;
    }
    prompts.forEach((prompt) => {
        const option = document.createElement('option');
        option.value = String(prompt.id);
        option.textContent = prompt.is_active ? `${prompt.name} (active)` : prompt.name;
        select.appendChild(option);
    });
    appendCreatePromptOption(select);
    select.disabled = false;
    if (manageBtn) manageBtn.textContent = 'Manage prompts';
    if (selectedPromptId) {
        select.value = String(selectedPromptId);
    } else if (activePromptId) {
        select.value = String(activePromptId);
    } else {
        select.value = String(prompts[0].id);
    }
}

function renderPromptList(prompts, activePromptId) {
    const container = document.querySelector('#promptList');
    if (!container) return;
    container.innerHTML = '';
    if (!prompts || prompts.length === 0) {
        const empty = document.createElement('div');
        empty.className = 'sw-empty p-3 text-xs text-slate-500';
        empty.textContent = 'No prompts available yet.';
        container.appendChild(empty);
        return;
    }

    prompts.forEach((prompt) => {
        const card = document.createElement('div');
        card.className = 'sw-card p-3 space-y-2';

        const header = document.createElement('div');
        header.className = 'flex items-start justify-between gap-3';

        const meta = document.createElement('div');
        const name = document.createElement('div');
        name.className = 'list-title';
        name.textContent = prompt.name;
        meta.appendChild(name);
        if (prompt.description) {
            const desc = document.createElement('div');
            desc.className = 'text-xs text-slate-500 mt-1';
            desc.textContent = prompt.description;
            meta.appendChild(desc);
        }
        const versionCount = document.createElement('div');
        versionCount.className = 'text-[10px] text-slate-400 mt-2';
        versionCount.textContent = `${prompt.versions.length} version${prompt.versions.length === 1 ? '' : 's'}`;
        meta.appendChild(versionCount);

        header.appendChild(meta);

        const actions = document.createElement('div');
        actions.className = 'flex flex-col gap-2 text-xs';
        if (prompt.is_active) {
            const badge = document.createElement('span');
            badge.className = 'sw-chip sw-chip--success text-[10px]';
            badge.textContent = 'Active';
            actions.appendChild(badge);
        } else {
            const activateBtn = document.createElement('button');
            activateBtn.className = 'sw-btn sw-btn--sm sw-btn--ghost';
            activateBtn.textContent = 'Activate';
            activateBtn.addEventListener('click', async () => {
                await handleActivatePrompt(prompt.id);
            });
            actions.appendChild(activateBtn);
        }

        const versionToggle = document.createElement('button');
        versionToggle.className = 'sw-btn sw-btn--sm sw-btn--ghost';
        versionToggle.textContent = 'New version';
        actions.appendChild(versionToggle);

        header.appendChild(actions);
        card.appendChild(header);

        const latest = prompt.latest_version || prompt.versions[0];
        if (latest) {
            const latestMeta = document.createElement('div');
            latestMeta.className = 'text-[10px] text-slate-400';
            const updatedLabel = latest.created_at ? `Updated ${new Date(latest.created_at).toLocaleString()}` : 'Latest version';
            latestMeta.textContent = latest.notes ? `${updatedLabel} · ${latest.notes}` : updatedLabel;
            card.appendChild(latestMeta);
        }

        const form = document.createElement('div');
        form.className = 'hidden mt-2 space-y-2';
        const contentLabel = document.createElement('div');
        contentLabel.className = 'sw-kicker text-[10px] text-slate-500';
        contentLabel.textContent = 'New version content';
        const contentArea = document.createElement('textarea');
        contentArea.rows = 4;
        contentArea.className = 'sw-textarea w-full sw-textarea--sm';
        contentArea.value = latest?.content || '';
        const notesInput = document.createElement('input');
        notesInput.type = 'text';
        notesInput.placeholder = 'Version notes (optional)';
        notesInput.className = 'sw-input w-full sw-input--sm';
        const formActions = document.createElement('div');
        formActions.className = 'flex items-center gap-2';
        const saveBtn = document.createElement('button');
        saveBtn.className = 'sw-btn sw-btn--sm sw-btn--primary';
        saveBtn.textContent = 'Save version';
        saveBtn.addEventListener('click', async () => {
            await handleCreatePromptVersion(prompt.id, contentArea.value, notesInput.value);
        });
        const cancelBtn = document.createElement('button');
        cancelBtn.className = 'sw-btn sw-btn--sm sw-btn--ghost';
        cancelBtn.textContent = 'Cancel';
        cancelBtn.addEventListener('click', () => {
            form.classList.add('hidden');
        });
        formActions.appendChild(saveBtn);
        formActions.appendChild(cancelBtn);
        form.appendChild(contentLabel);
        form.appendChild(contentArea);
        form.appendChild(notesInput);
        form.appendChild(formActions);
        card.appendChild(form);

        versionToggle.addEventListener('click', () => {
            form.classList.toggle('hidden');
        });

        const history = document.createElement('details');
        history.className = 'text-xs text-slate-500';
        const summary = document.createElement('summary');
        summary.className = 'cursor-pointer';
        summary.textContent = 'Version history';
        history.appendChild(summary);
        const historyList = document.createElement('div');
        historyList.className = 'mt-2 space-y-1';
        prompt.versions.forEach((version) => {
            const row = document.createElement('div');
            row.className = 'text-[10px] text-slate-400';
            const stamp = version.created_at ? new Date(version.created_at).toLocaleString() : `v${version.version_index}`;
            row.textContent = version.notes ? `v${version.version_index} · ${stamp} · ${version.notes}` : `v${version.version_index} · ${stamp}`;
            historyList.appendChild(row);
        });
        history.appendChild(historyList);
        card.appendChild(history);

        container.appendChild(card);
    });
}

async function loadPrompts({ keepSelection = false } = {}) {
    try {
        const data = await api.getPrompts();
        let prompts = data.prompts || [];
        let activePromptId = data.active_prompt_id || null;
        if (!prompts.length) {
            throw new Error('No prompts are configured. Create one before using the dashboard.');
        }
        if (!activePromptId || !prompts.some((prompt) => prompt.id === activePromptId)) {
            activePromptId = prompts[0].id;
        }
        setPrompts(prompts, activePromptId);
        const selectedPromptId = keepSelection ? getSelectedPrompt() : null;
        const resolved = selectedPromptId || activePromptId || (prompts[0] ? prompts[0].id : null);
        if (resolved !== null && resolved !== undefined) {
            setSelectedPrompt(resolved);
        }
        renderPromptSelect(prompts, activePromptId, resolved);
        renderPromptList(prompts, activePromptId);
    } catch (err) {
        const detail = err?.message || String(err || '');
        showBlockingError(
            'Prompts unavailable',
            'Failed to load prompts from the API. Fix the server and reload to continue.',
            detail
        );
        throw err;
    }
}

function initEventHandlers() {
    // Search
    $('#searchBtn').addEventListener('click', handleSearch);
    $('#queryInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') handleSearch();
    });
    const uploadPdfBtn = document.querySelector('#uploadPdfBtn');
    const uploadPdfInput = document.querySelector('#uploadPdfInput');
    if (uploadPdfBtn && uploadPdfInput) {
        uploadPdfBtn.addEventListener('click', () => uploadPdfInput.click());
        uploadPdfInput.addEventListener('change', async (event) => {
            const files = event.target.files;
            if (!files || files.length === 0) return;
            await handleDashboardUpload(files);
            uploadPdfInput.value = '';
        });
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
    const promptSelect = document.querySelector('#promptSelect');
    if (promptSelect) {
        promptSelect.addEventListener('change', (e) => {
            const rawValue = e.target.value;
            if (rawValue === CREATE_PROMPT_OPTION) {
                openSideDrawer('prompt', { focusSelector: '#promptName' });
                const fallback = getSelectedPrompt() ?? appStore.get('activePromptId');
                e.target.value = fallback !== null && fallback !== undefined ? String(fallback) : '';
                return;
            }
            const value = parseInt(rawValue, 10);
            setSelectedPrompt(Number.isNaN(value) ? null : value);
        });
    }
    const promptManageBtn = document.querySelector('#promptManageBtn');
    if (promptManageBtn) {
        promptManageBtn.addEventListener('click', () => {
            openSideDrawer('prompt', { focusSelector: '#promptName' });
        });
    }
    const promptCreateBtn = document.querySelector('#promptCreateBtn');
    if (promptCreateBtn) {
        promptCreateBtn.addEventListener('click', handleCreatePrompt);
    }
    const searchExamples = document.querySelector('#searchExamples');
    if (searchExamples) {
        searchExamples.addEventListener('click', (e) => {
            const target = e.target.closest('button[data-search-example]');
            if (!target) return;
            const input = document.querySelector('#queryInput');
            if (!input) return;
            input.value = target.dataset.searchExample || '';
            input.focus();
            input.select();
        });
    }
    Object.keys(SIDE_DRAWERS).forEach((key) => {
        const config = SIDE_DRAWERS[key];
        const openBtn = document.querySelector(config.openBtn);
        if (openBtn) {
            openBtn.addEventListener('click', () => {
                openSideDrawer(key);
            });
        }
        const closeBtn = document.querySelector(config.closeBtn);
        if (closeBtn) {
            closeBtn.addEventListener('click', () => {
                closeSideDrawer(key);
            });
        }
        const drawer = document.querySelector(config.drawer);
        const overlay = drawer?.querySelector('.sw-side-drawer__overlay');
        if (overlay) {
            overlay.addEventListener('click', () => {
                closeSideDrawer(key);
            });
        }
    });
    document.addEventListener('keydown', handleKeyboardShortcuts);
    document.addEventListener('visibilitychange', () => {
        if (document.visibilityState === 'visible') {
            connectSSE();
            refreshPapers();
            loadFailureSummary();
        }
    });
    window.addEventListener('focus', () => {
        connectSSE();
        refreshPapers();
        loadFailureSummary();
    });
    
    // Provider selector
    $('#providerSelect').addEventListener('change', (e) => {
        const nextProvider = e.target.value;
        setSelectedProvider(nextProvider);
        hydrateProviderModelSelect(nextProvider, false);
    });
    $('#providerModelSelect')?.addEventListener('change', (e) => {
        setSelectedModel((e.target.value || '').trim());
    });
    const providerSelect = $('#providerSelect');
    if (providerSelect?.value) {
        setSelectedProvider(providerSelect.value);
        hydrateProviderModelSelect(providerSelect.value, true);
    }
    const modelSelect = $('#providerModelSelect');
    if (modelSelect) {
        setSelectedModel((modelSelect.value || '').trim());
    }
    
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
        if (state.drawerPaper !== prev.drawerPaper || state.drawerRuns !== prev.drawerRuns || state.resolvedRunSources !== prev.resolvedRunSources) {
            renderDrawer(state.drawerPaper, state.drawerRuns, {
                resolvedSources: state.resolvedRunSources || {},
                providerCatalog: getProviderCatalog().filter(p => p.enabled),
                selectedProvider: getSelectedProvider(),
                selectedModel: getSelectedModel(),
            });
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

function applyPaperPreset(status) {
    paperFilters.status = status;
    paperFilters.sort = 'recent';
    syncPaperFilterInputs();
    renderFilteredPapers();
}

function renderFilteredPapers(papers = appStore.get('papers')) {
    const filtered = applyPaperFilters(papers);
    const emptyMessage = filtersActive()
        ? 'No papers match these filters. Click Clear filters to show all papers.'
        : 'No papers yet. Search and extract papers to see them here.';
    renderPapersTable(filtered, handlePaperClick, {
        emptyMessage,
        resolvedSources: appStore.get('resolvedRunSources') || {},
        onRetryRun: handleRetryRun,
        onResolveRun: handleResolveRunSource,
        onUploadRun: handleUploadRunFile,
        onRunWithSource: handleRetryRunWithResolved,
    });
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
    if (e.key === 'Escape') {
        if (failureModalState) {
            closeFailureModal();
            return;
        }
        if (closeAnySideDrawer()) {
            return;
        }
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
    const model = (getSelectedModel() || '').trim() || null;
    const promptId = getSelectedPrompt();
    const resolvedPromptId = promptId ? promptId : null;
    
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
        const result = await api.enqueue(enqueueItems, provider, resolvedPromptId, model);
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

async function handleCreatePrompt() {
    const nameInput = document.querySelector('#promptName');
    const descriptionInput = document.querySelector('#promptDescription');
    const contentInput = document.querySelector('#promptContent');
    const notesInput = document.querySelector('#promptNotes');
    const activateInput = document.querySelector('#promptActivate');
    if (!nameInput || !contentInput) return;
    const name = nameInput.value.trim();
    const description = descriptionInput?.value.trim() || null;
    const content = contentInput.value.trim();
    const notes = notesInput?.value.trim() || null;
    const activate = activateInput?.checked ?? false;

    if (!name || !content) {
        setPromptStatus('Name and content are required.', true);
        return;
    }
    setPromptStatus('Creating prompt...');
    try {
        await api.createPrompt({
            name,
            description,
            content,
            notes,
            activate,
            created_by: 'dashboard',
        });
        nameInput.value = '';
        if (descriptionInput) descriptionInput.value = '';
        contentInput.value = '';
        if (notesInput) notesInput.value = '';
        if (activateInput) activateInput.checked = true;
        setPromptStatus('Prompt created.');
        await loadPrompts();
    } catch (err) {
        setPromptStatus(err.message || 'Failed to create prompt.', true);
    }
}

async function handleCreatePromptVersion(promptId, content, notes) {
    if (!promptId) return;
    if (!content || !content.trim()) {
        setPromptStatus('Prompt content is required.', true);
        return;
    }
    setPromptStatus('Saving version...');
    try {
        await api.createPromptVersion(promptId, {
            content: content.trim(),
            notes: notes?.trim() || null,
            created_by: 'dashboard',
        });
        setPromptStatus('Version saved.');
        await loadPrompts({ keepSelection: true });
    } catch (err) {
        setPromptStatus(err.message || 'Failed to save version.', true);
    }
}

async function handleActivatePrompt(promptId) {
    if (!promptId) return;
    setPromptStatus('Updating active prompt...');
    try {
        await api.activatePrompt(promptId);
        setSelectedPrompt(promptId);
        setPromptStatus('Active prompt updated.');
        await loadPrompts({ keepSelection: true });
    } catch (err) {
        setPromptStatus(err.message || 'Failed to update active prompt.', true);
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

async function handleRetryRun(runId, provider, model) {
    try {
        let result;
        if (provider) {
            // Retry with a specific provider/model override
            result = await api.retryRunWithSource(runId, {
                source_url: null,
                provider,
                model: model || null,
            });
        } else {
            result = await api.retryRun(runId);
        }
        console.log('Retry result:', result);

        // Refresh the drawer to show updated status
        const paperId = appStore.get('drawerPaperId');
        if (paperId) {
            await loadPaperDetails(paperId);
        }

        // Refresh papers table
        await refreshPapers();
    } catch (e) {
        console.error('Failed to retry run:', e);
        alert(e.message || 'Failed to retry run');
    }
}

async function handleResolveRunSource(runId) {
    try {
        const result = await api.resolveRunSource(runId);
        if (!result.found) {
            alert('No open-access source found for this run.');
            return;
        }
        const resolved = {
            url: result.pdf_url || result.url,
            label: result.pdf_url ? 'PDF URL' : 'Source URL',
        };
        if (!resolved.url) {
            alert('Resolved source did not include a usable URL.');
            return;
        }
        const current = appStore.get('resolvedRunSources') || {};
        appStore.set({
            resolvedRunSources: { ...current, [runId]: resolved },
        });
    } catch (e) {
        console.error('Failed to resolve source:', e);
        alert(e.message || 'Failed to resolve source');
    }
}

async function handleRetryRunWithResolved(runId, sourceUrl) {
    try {
        const provider = getSelectedProvider();
        const model = (getSelectedModel() || '').trim() || null;
        const result = await api.retryRunWithSource(runId, {
            source_url: sourceUrl,
            provider,
            model,
        });
        console.log('Retry with source result:', result);
        const current = { ...(appStore.get('resolvedRunSources') || {}) };
        delete current[runId];
        appStore.set({ resolvedRunSources: current });
        const paperId = appStore.get('drawerPaperId');
        if (paperId) {
            await loadPaperDetails(paperId);
        }
        await refreshPapers();
    } catch (e) {
        console.error('Failed to retry with source:', e);
        alert(e.message || 'Failed to retry with resolved source');
    }
}

async function handleUploadRunFile(runId, files, provider, model) {
    const list = Array.from(files || []);
    const label = list.length === 1 ? 'Uploading PDF...' : `Uploading ${list.length} PDFs...`;
    setSearchStatus(label, true);
    try {
        const resolvedProvider = provider || getSelectedProvider();
        const resolvedModel = (model || getSelectedModel() || '').trim() || null;
        await api.uploadRunPdf(runId, files, resolvedProvider, null, resolvedModel);
        setSearchStatus('PDF uploaded. Extraction queued.');
        const paperId = appStore.get('drawerPaperId');
        if (paperId) {
            await loadPaperDetails(paperId);
        }
        await refreshPapers();
    } catch (e) {
        console.error('Failed to upload PDF:', e);
        setSearchStatus('Upload failed.');
        alert(e.message || 'Failed to upload PDF');
    } finally {
        setSearchStatus(document.querySelector('#searchStatus')?.textContent || '', false);
    }
}

async function handleDashboardUpload(files) {
    const list = Array.from(files || []);
    if (list.length === 0) return;
    const invalid = list.find((item) => !item.name || !item.name.toLowerCase().endsWith('.pdf'));
    if (invalid) {
        alert('Please choose PDF files only.');
        return;
    }
    const promptId = getSelectedPrompt();
    const provider = getSelectedProvider();
    const model = (getSelectedModel() || '').trim() || null;
    const title = list.length === 1 ? list[0].name.replace(/\.pdf$/i, '') : null;
    const label = list.length === 1 ? 'Uploading PDF...' : `Uploading ${list.length} PDFs...`;
    setSearchStatus(label, true);
    
    try {
        await api.extractFile(list, promptId, title, provider, model);
        await refreshPapers();
        const doneLabel = list.length === 1
            ? 'PDF uploaded. Extraction queued.'
            : `${list.length} PDFs uploaded. Extraction queued.`;
        setSearchStatus(doneLabel);
    } catch (e) {
        console.error('Failed to upload PDF:', e);
        setSearchStatus('Upload failed.');
        await refreshPapers();
        alert(e.message || 'Failed to upload PDF');
    } finally {
        setSearchStatus(document.querySelector('#searchStatus')?.textContent || '', false);
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
        empty.className = 'sw-empty text-xs text-slate-400 p-3';
        empty.textContent = 'No data';
        section.appendChild(empty);
        return section;
    }

    const maxCount = Math.max(...items.map(item => item.count || 0), 1);
    items.forEach((item) => {
        const row = document.createElement('div');
        row.className = 'sw-row list-row px-3 py-2 flex items-center justify-between gap-3';

        const label = document.createElement('div');
        label.className = 'flex-1 min-w-0';

        const labelText = document.createElement('div');
        labelText.className = 'text-slate-700 truncate';
        labelText.textContent = item.label || item.key;

        const bar = document.createElement('div');
        bar.className = 'sw-progress h-1 mt-1';
        const fill = document.createElement('div');
        fill.className = 'sw-progress__fill h-full';
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
            link.className = 'sw-chip sw-chip--info text-[10px]';
            link.href = `/runs/${item.example_run_id}`;
            link.target = '_blank';
            link.textContent = 'Open';
            meta.appendChild(link);
        }
        if (options.onSelect) {
            const view = document.createElement('button');
            view.className = 'sw-btn sw-btn--sm sw-btn--ghost';
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

function getTopFailureItem(items = []) {
    if (!Array.isArray(items) || items.length === 0) return null;
    return items.reduce((best, item) => {
        if (!best || (item.count || 0) > (best.count || 0)) {
            return item;
        }
        return best;
    }, null);
}

function renderFailureSummary(summary) {
    const container = document.querySelector('#failureSummaryBody');
    const empty = document.querySelector('#failureSummaryEmpty');
    const compact = document.querySelector('#failureSummaryCompact');
    if (!container || !empty) return;
    container.innerHTML = '';

    if (!summary || !summary.total_failed) {
        empty.classList.remove('hidden');
        if (compact) {
            compact.textContent = 'No failed runs in this window.';
        }
        return;
    }

    empty.classList.add('hidden');
    const windowStart = summary.window_start ? new Date(summary.window_start) : null;
    const meta = document.createElement('div');
    meta.className = 'md:col-span-3 text-xs text-slate-500';
    const windowLabel = windowStart ? windowStart.toLocaleDateString() : 'unknown';
    meta.textContent = `Failed runs: ${summary.total_failed}. Last ${summary.window_days} days (since ${windowLabel}).`;
    container.appendChild(meta);

    if (compact) {
        const topBucket = getTopFailureItem(summary.buckets || []);
        const topReason = getTopFailureItem(summary.reasons || []);
        const parts = [`Failed runs: ${summary.total_failed} in last ${summary.window_days} days`];
        if (topBucket) {
            parts.push(`Top category: ${topBucket.label || topBucket.key}`);
        }
        if (topReason) {
            parts.push(`Top reason: ${topReason.label || topReason.key}`);
        }
        compact.textContent = parts.join(' · ');
    }

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
        row.className = 'sw-row list-row sw-card sw-card--error p-4 flex items-start justify-between gap-4';

        const info = document.createElement('div');
        info.className = 'text-xs text-slate-600';
        const title = run.paper_title || `Paper ${run.paper_id || ''}`;
        const metaLine = [run.paper_doi, run.paper_source, run.paper_year, run.model_provider].filter(Boolean).join(' · ');
        const reason = run.normalized_reason || run.failure_reason || 'Unknown failure';
        info.innerHTML = `
            <div class="list-title">${title}</div>
            <div class="text-xs text-slate-500 mt-1">${metaLine}</div>
            <div class="sw-kicker text-[11px] text-slate-500 mt-1">${run.bucket || 'unknown'}</div>
            <div class="text-xs text-red-500 mt-2">${reason}</div>
        `;

        const actions = document.createElement('div');
        actions.className = 'flex flex-col gap-2 text-xs';
        const open = document.createElement('a');
        open.className = 'sw-btn sw-btn--sm sw-btn--ghost';
        open.href = `/runs/${run.id}`;
        open.target = '_blank';
        open.textContent = 'Open';
        const retry = document.createElement('button');
        retry.className = 'sw-btn sw-btn--sm sw-btn--danger';
        retry.textContent = 'Retry';
        retry.addEventListener('click', async () => {
            await api.retryRun(run.id);
            await refreshPapers();
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
    list.innerHTML = '<div class="sw-empty p-4 text-xs text-slate-500">Loading failures...</div>';
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
    const compact = document.querySelector('#failureSummaryCompact');
    if (!container || !empty) return;
    const days = Number.parseInt(select?.value || '30', 10);
    container.innerHTML = '<div class="sw-empty md:col-span-3 text-xs text-slate-500 p-4">Loading failure summary...</div>';
    if (compact) {
        compact.textContent = 'Loading failure summary...';
    }
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
        if (compact) {
            compact.textContent = 'Failed to load failure summary.';
        }
    }
}

async function handleForceReextract(paperId, provider, model) {
    try {
        const resolvedProvider = provider || getSelectedProvider();
        const resolvedModel = (model || getSelectedModel() || '').trim() || null;
        const result = await api.forceReextract(paperId, resolvedProvider, resolvedModel);
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
