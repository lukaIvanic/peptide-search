/**
 * API client module - handles all communication with the backend.
 */

const runtimeConfig = (typeof window !== 'undefined' && window.PEPTIDE_APP_CONFIG) ? window.PEPTIDE_APP_CONFIG : {};
const API_BASE = runtimeConfig.apiBase || '/api';
const STREAM_BASE = runtimeConfig.streamBase || '/api/stream';
const REQUEST_TIMEOUT_MS = Number.isFinite(runtimeConfig.requestTimeoutMs)
    ? runtimeConfig.requestTimeoutMs
    : 30000;

function buildUrl(path) {
    const base = API_BASE.replace(/\/$/, '');
    if (/^https?:\/\//i.test(path)) {
        return path;
    }
    if (path.startsWith('/api/')) {
        if (base.endsWith('/api')) {
            return `${base}${path.slice('/api'.length)}`;
        }
        return `${base}${path}`;
    }
    if (path.startsWith('/')) {
        return `${base}${path}`;
    }
    return `${base}/${path}`;
}

/**
 * Make a fetch request with standard headers and error handling.
 */
async function request(path, opts = {}) {
    const url = buildUrl(path.startsWith('/') ? path : `/${path}`);
    const { timeoutMs, headers, ...fetchOpts } = opts;
    const controller = new AbortController();
    const resolvedTimeout = Number.isFinite(timeoutMs) ? timeoutMs : REQUEST_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), resolvedTimeout);
    try {
        const res = await fetch(url, {
            headers: { 'Content-Type': 'application/json', ...(headers || {}) },
            signal: controller.signal,
            ...fetchOpts,
        });
        if (!res.ok) {
            const err = await res.text();
            throw new Error(err || res.statusText);
        }
        return res.json();
    } catch (err) {
        if (err?.name === 'AbortError') {
            throw new Error(`Request timed out after ${Math.round(resolvedTimeout / 1000)}s`);
        }
        throw err;
    } finally {
        clearTimeout(timer);
    }
}

/**
 * Make a multipart/form-data request (e.g., file upload).
 */
async function requestForm(path, formData, opts = {}) {
    const url = buildUrl(path.startsWith('/') ? path : `/${path}`);
    const { timeoutMs, ...fetchOpts } = opts;
    const controller = new AbortController();
    const resolvedTimeout = Number.isFinite(timeoutMs) ? timeoutMs : REQUEST_TIMEOUT_MS;
    const timer = setTimeout(() => controller.abort(), resolvedTimeout);
    try {
        const res = await fetch(url, {
            signal: controller.signal,
            ...fetchOpts,
            body: formData,
        });
        if (!res.ok) {
            const err = await res.text();
            throw new Error(err || res.statusText);
        }
        return res.json();
    } catch (err) {
        if (err?.name === 'AbortError') {
            throw new Error(`Request timed out after ${Math.round(resolvedTimeout / 1000)}s`);
        }
        throw err;
    } finally {
        clearTimeout(timer);
    }
}

function normalizeFiles(input) {
    if (!input) return [];
    if (Array.isArray(input)) return input;
    if (typeof FileList !== 'undefined' && input instanceof FileList) {
        return Array.from(input);
    }
    return [input];
}

/**
 * Generic GET request.
 */
export async function get(path, opts = {}) {
    return request(path, { method: 'GET', ...opts });
}

/**
 * Generic POST request with JSON body.
 */
export async function post(path, body, opts = {}) {
    return request(path, {
        method: 'POST',
        body: JSON.stringify(body),
        ...opts,
    });
}

/**
 * Generic DELETE request.
 */
export async function del(path, opts = {}) {
    return request(path, { method: 'DELETE', ...opts });
}

/**
 * Get health/status info including current provider.
 */
export async function getHealth() {
    return request('/api/health');
}

/**
 * Danger: delete all extracted runs and papers.
 */
export async function clearExtractionData() {
    return request('/api/admin/clear-extractions', { method: 'POST' });
}

/**
 * Search for papers across all sources.
 * Returns results with seen/processed flags.
 */
export async function search(query, rows = 10) {
    return request(`/api/search?q=${encodeURIComponent(query)}&rows=${rows}`);
}

/**
 * Enqueue papers for batch extraction.
 * @param {object[]} papers - Papers to enqueue (with pdf_url, title, etc.)
 * @param {string} provider - Provider name (openai, mock)
 */
export async function enqueue(papers, provider = 'openai', promptId = null) {
    return request('/api/enqueue', {
        method: 'POST',
        body: JSON.stringify({ papers, provider, prompt_id: promptId }),
    });
}

/**
 * Get list of papers with their latest run status.
 */
export async function getPapers() {
    return request('/api/papers');
}

/**
 * Get detailed extractions for a paper.
 */
export async function getPaperExtractions(paperId) {
    return request(`/api/papers/${paperId}/extractions`);
}

/**
 * Get runs for a paper (with prompts and raw JSON).
 */
export async function getRuns(paperId) {
    return request(`/api/runs?paper_id=${paperId}`);
}

/**
 * Get a single run by ID (with prompts and raw JSON).
 */
export async function getRun(runId) {
    return request(`/api/runs/${runId}`);
}

/**
 * Get history for a run (versions for the same paper).
 */
export async function getRunHistory(runId) {
    return request(`/api/runs/${runId}/history`);
}

/**
 * Retry a failed run.
 * @param {number} runId - The run ID to retry
 */
export async function retryRun(runId) {
    return request(`/api/runs/${runId}/retry`, {
        method: 'POST',
    });
}

/**
 * Resolve a new source URL for a run.
 */
export async function resolveRunSource(runId) {
    return request(`/api/runs/${runId}/resolve-source`, {
        method: 'POST',
    });
}

/**
 * Retry a run with an optional override source URL.
 */
export async function retryRunWithSource(runId, payload = {}) {
    return request(`/api/runs/${runId}/retry-with-source`, {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/**
 * Upload PDFs for a run (creates a new run).
 */
export async function uploadRunPdf(runId, files, provider, promptId) {
    const formData = new FormData();
    const list = normalizeFiles(files);
    list.forEach((item) => formData.append('files', item));
    if (provider) formData.append('provider', provider);
    if (promptId !== undefined && promptId !== null) formData.append('prompt_id', String(promptId));
    return requestForm(`/api/runs/${runId}/upload`, formData, {
        method: 'POST',
    });
}

/**
 * Get recent runs (optionally filtered by status).
 * @param {string} [status]
 * @param {number} [limit]
 */
export async function getRecentRuns(status, limit = 10) {
    const params = new URLSearchParams();
    if (status) params.set('status', status);
    if (limit) params.set('limit', String(limit));
    return request(`/api/runs/recent?${params.toString()}`);
}

/**
 * Get failure summary buckets for recent failed runs.
 * @param {number} [days]
 * @param {number} [maxRuns]
 */
export async function getFailureSummary(days = 30, maxRuns = 1000) {
    const params = new URLSearchParams();
    if (days) params.set('days', String(days));
    if (maxRuns) params.set('max_runs', String(maxRuns));
    return request(`/api/runs/failure-summary?${params.toString()}`);
}

/**
 * List failed runs with optional filters.
 * @param {object} filters
 */
export async function getFailedRuns(filters = {}) {
    const params = new URLSearchParams();
    if (filters.days) params.set('days', String(filters.days));
    if (filters.limit) params.set('limit', String(filters.limit));
    if (filters.maxRuns) params.set('max_runs', String(filters.maxRuns));
    if (filters.bucket) params.set('bucket', filters.bucket);
    if (filters.provider) params.set('provider', filters.provider);
    if (filters.source) params.set('source', filters.source);
    if (filters.reason) params.set('reason', filters.reason);
    return request(`/api/runs/failures?${params.toString()}`);
}

/**
 * List baseline cases (optionally filter by dataset).
 */
export async function getBaselineCases(dataset) {
    const params = new URLSearchParams();
    if (dataset) params.set('dataset', dataset);
    const query = params.toString();
    return request(query ? `/api/baseline/cases?${query}` : '/api/baseline/cases');
}

/**
 * Get a baseline case by ID.
 */
export async function getBaselineCase(caseId) {
    return request(`/api/baseline/cases/${encodeURIComponent(caseId)}`);
}

/**
 * Resolve a fresh source URL for a baseline case.
 */
export async function resolveBaselineSource(caseId, options = {}) {
    const params = new URLSearchParams();
    if (options.localOnly) {
        params.set('local_only', 'true');
    }
    const suffix = params.toString() ? `?${params.toString()}` : '';
    return request(`/api/baseline/cases/${encodeURIComponent(caseId)}/resolve-source${suffix}`, {
        method: 'POST',
    });
}

/**
 * Get local PDF availability for a baseline case.
 */
export async function getBaselineLocalPdfInfo(caseId) {
	return request(`/api/baseline/cases/${encodeURIComponent(caseId)}/local-pdf-info`);
}

/**
 * Build a direct URL to open the local PDF in a new tab.
 */
export function getBaselineLocalPdfUrl(caseId) {
	return buildUrl(`/api/baseline/cases/${encodeURIComponent(caseId)}/local-pdf`);
}

/**
 * Get SI (supplementary) PDF availability for a baseline case.
 */
export async function getBaselineLocalPdfSiInfo(caseId) {
	return request(`/api/baseline/cases/${encodeURIComponent(caseId)}/local-pdf-si-info`);
}

/**
 * Build a direct URL to open an SI PDF in a new tab.
 */
export function getBaselineLocalPdfSiUrl(caseId, index = 0) {
	return buildUrl(`/api/baseline/cases/${encodeURIComponent(caseId)}/local-pdf-si?index=${index}`);
}

/**
 * Get the latest run for a baseline case.
 */
export async function getBaselineLatestRun(caseId) {
    return request(`/api/baseline/cases/${encodeURIComponent(caseId)}/latest-run`);
}

/**
 * Enqueue baseline cases (optionally dataset-filtered).
 */
export async function enqueueBaselineAll(provider = 'openai', promptId = null, dataset = null, force = false) {
    return request('/api/baseline/enqueue', {
        method: 'POST',
        body: JSON.stringify({
            provider,
            prompt_id: promptId,
            dataset,
            force,
        }),
    });
}

/**
 * Retry a baseline case (optionally with an override source URL).
 */
export async function retryBaselineCase(caseId, payload = {}) {
    return request(`/api/baseline/cases/${encodeURIComponent(caseId)}/retry`, {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/**
 * Upload a PDF for a baseline case (always linked to the case).
 */
export async function uploadBaselinePdf(caseId, file, provider, promptId) {
    const formData = new FormData();
    formData.append('file', file);
    if (provider) formData.append('provider', provider);
    if (promptId !== undefined && promptId !== null) formData.append('prompt_id', String(promptId));
    return requestForm(`/api/baseline/cases/${encodeURIComponent(caseId)}/upload`, formData, {
        method: 'POST',
    });
}

/**
 * Seed shadow baseline runs (development only).
 */
export async function seedBaselineShadow(dataset = null, limit = null, force = false) {
    return request('/api/baseline/shadow-seed', {
        method: 'POST',
        body: JSON.stringify({
            dataset,
            limit,
            force,
        }),
    });
}

/**
 * Retry failed runs using the same filters as getFailedRuns.
 * @param {object} filters
 */
export async function retryFailedRuns(filters = {}) {
    return request('/api/runs/failures/retry', {
        method: 'POST',
        body: JSON.stringify(filters),
    });
}

/**
 * Follow up on an existing run with a new instruction.
 * @param {number} runId - Parent run ID
 * @param {string} instruction - Follow-up instruction
 * @param {string} [provider] - Optional provider override
 */
export async function followupRun(runId, instruction, provider) {
    return request(`/api/runs/${runId}/followup`, {
        method: 'POST',
        body: JSON.stringify({ instruction, provider }),
    });
}

/**
 * Save manual edits as a new run version.
 * @param {number} runId
 * @param {object} payload
 * @param {string} [reason]
 */
export async function editRun(runId, payload, reason) {
    return request(`/api/runs/${runId}/edit`, {
        method: 'POST',
        body: JSON.stringify({ payload, reason }),
    });
}

/**
 * Get all entities (optionally grouped).
 * @param {string} [groupBy]
 * @param {boolean} [showMissingKey]
 */
export async function getEntities(groupBy, showMissingKey = false, filters = {}) {
    const params = new URLSearchParams();
    if (groupBy) params.set('group_by', groupBy);
    if (showMissingKey) params.set('show_missing_key', 'true');
    if (filters.latestOnly) params.set('latest_only', 'true');
    if (filters.recentMinutes) params.set('recent_minutes', String(filters.recentMinutes));
    const query = params.toString();
    const path = query ? `/api/entities?${query}` : '/api/entities';
    return request(path);
}

/**
 * Get a single entity by ID.
 * @param {number} entityId
 */
export async function getEntity(entityId) {
    return request(`/api/entities/${entityId}`);
}

/**
 * Get KPI summary for entities.
 */
export async function getEntityKpis(filters = {}) {
    const params = new URLSearchParams();
    if (filters.latestOnly) params.set('latest_only', 'true');
    if (filters.recentMinutes) params.set('recent_minutes', String(filters.recentMinutes));
    const query = params.toString();
    return request(query ? `/api/entities/kpis?${query}` : '/api/entities/kpis');
}

/**
 * Fetch quality rules configuration.
 */
export async function getQualityRules() {
    return request('/api/quality-rules');
}

/**
 * Update quality rules configuration.
 * @param {object} rules
 */
export async function updateQualityRules(rules) {
    return request('/api/quality-rules', {
        method: 'POST',
        body: JSON.stringify({ rules }),
    });
}

/**
 * Get all base prompts and versions.
 */
export async function getPrompts() {
    return request('/api/prompts');
}

/**
 * Create a new base prompt with an initial version.
 * @param {object} payload
 */
export async function createPrompt(payload) {
    return request('/api/prompts', {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/**
 * Create a new version for an existing prompt.
 * @param {number} promptId
 * @param {object} payload
 */
export async function createPromptVersion(promptId, payload) {
    return request(`/api/prompts/${promptId}/versions`, {
        method: 'POST',
        body: JSON.stringify(payload),
    });
}

/**
 * Activate a prompt for default selection.
 * @param {number} promptId
 */
export async function activatePrompt(promptId) {
    return request(`/api/prompts/${promptId}/activate`, {
        method: 'POST',
    });
}

/**
 * Force re-extract a paper (creates a new run).
 * @param {number} paperId - The paper ID
 * @param {string} [provider] - Optional provider override
 */
export async function forceReextract(paperId, provider) {
    const url = provider 
        ? `/api/papers/${paperId}/force-reextract?provider=${encodeURIComponent(provider)}`
        : `/api/papers/${paperId}/force-reextract`;
    return request(url, {
        method: 'POST',
    });
}

// Alias for backward compatibility
export const getPaperRuns = getRuns;

/**
 * Create SSE connection for live updates.
 * @param {function} onMessage - Callback for messages
 * @param {function} onError - Callback for errors
 * @returns {EventSource}
 */
export function createSSEConnection(onMessage, onError) {
    const eventSource = new EventSource(STREAM_BASE);
    
    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            onMessage(data);
        } catch (e) {
            console.error('SSE parse error:', e);
        }
    };
    
    eventSource.onerror = (event) => {
        console.error('SSE error:', event);
        if (onError) onError(event);
    };
    
    return eventSource;
}

// Legacy API calls for backward compatibility

/**
 * Extract data from a URL or text (single item, not batch).
 */
export async function extract(body) {
    return request('/api/extract', {
        method: 'POST',
        body: JSON.stringify(body),
    });
}

/**
 * Upload PDF files for extraction.
 */
export async function extractFile(files, promptId, title) {
    const formData = new FormData();
    const list = normalizeFiles(files);
    list.forEach((item) => formData.append('files', item));
    if (title) formData.append('title', title);
    if (promptId) formData.append('prompt_id', String(promptId));

    return requestForm('/api/extract-file', formData, { method: 'POST' });
}

/**
 * Get a single extraction by ID.
 */
export async function getExtraction(extractionId) {
    return request(`/api/extractions/${extractionId}`);
}
