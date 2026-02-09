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

export const paperFilters = {
    query: '',
    status: '',
    source: '',
    sort: 'recent',
};

export function applyPaperFilters(papers, filters = paperFilters) {
    const query = filters.query.trim().toLowerCase();
    const statusFilter = filters.status;
    const sourceFilter = filters.source;
    const sortFilter = filters.sort || 'recent';

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

export function syncPaperFilterInputs(filters = paperFilters) {
    const papersFilterInput = document.querySelector('#papersFilterInput');
    const papersFilterStatus = document.querySelector('#papersFilterStatus');
    const papersFilterSource = document.querySelector('#papersFilterSource');
    const papersFilterSort = document.querySelector('#papersFilterSort');
    if (papersFilterInput) papersFilterInput.value = filters.query;
    if (papersFilterStatus) papersFilterStatus.value = filters.status;
    if (papersFilterSource) papersFilterSource.value = filters.source;
    if (papersFilterSort) papersFilterSort.value = filters.sort || 'recent';
}

export function persistPaperFilters(filters = paperFilters) {
    try {
        localStorage.setItem(PAPER_FILTERS_STORAGE_KEY, JSON.stringify(filters));
    } catch {
        // ignore
    }
}

export function sanitizePaperFilters(filters = paperFilters) {
    let changed = false;
    if (typeof filters.query !== 'string') {
        filters.query = '';
        changed = true;
    }
    if (!PAPER_FILTERS_ALLOWED_STATUS.has(filters.status)) {
        filters.status = '';
        changed = true;
    }
    if (!PAPER_FILTERS_ALLOWED_SOURCE.has(filters.source)) {
        filters.source = '';
        changed = true;
    }
    if (!PAPER_FILTERS_ALLOWED_SORT.has(filters.sort)) {
        filters.sort = 'recent';
        changed = true;
    }
    return changed;
}

export function hydratePaperFilters(filters = paperFilters) {
    try {
        const raw = localStorage.getItem(PAPER_FILTERS_STORAGE_KEY);
        if (!raw) {
            syncPaperFilterInputs(filters);
            return;
        }
        const stored = JSON.parse(raw);
        if (stored && typeof stored === 'object') {
            filters.query = stored.query || '';
            filters.status = stored.status || '';
            filters.source = stored.source || '';
            filters.sort = stored.sort || 'recent';
        }
    } catch {
        // ignore
    }
    if (sanitizePaperFilters(filters)) {
        persistPaperFilters(filters);
    }
    syncPaperFilterInputs(filters);
}

export function filtersActive(filters = paperFilters) {
    return Boolean(
        filters.query.trim()
        || filters.status
        || filters.source
    );
}

export function updatePaperFilterCount(filteredCount, totalCount, filters = paperFilters) {
    const countEl = document.querySelector('#papersFilterCount');
    const clearBtn = document.querySelector('#papersFilterClear');
    if (countEl) {
        if (!totalCount) {
            countEl.textContent = 'No papers yet';
        } else if (filteredCount === totalCount && !filtersActive(filters)) {
            countEl.textContent = `${totalCount} papers`;
        } else {
            countEl.textContent = `Showing ${filteredCount} of ${totalCount}`;
        }
    }
    if (clearBtn) {
        clearBtn.classList.toggle('hidden', !filtersActive(filters));
    }
}

export function updatePaperFilterNotice(filteredCount, totalCount, filters = paperFilters) {
    const notice = document.querySelector('#papersFilterNotice');
    if (!notice) return;
    const shouldShow = totalCount > 0 && filteredCount === 0 && filtersActive(filters);
    notice.classList.toggle('hidden', !shouldShow);
}

export function escapeCsv(value) {
    if (value === null || value === undefined) return '';
    const text = String(value);
    if (text.includes('"') || text.includes(',') || text.includes('\n')) {
        return `"${text.replace(/"/g, '""')}"`;
    }
    return text;
}
