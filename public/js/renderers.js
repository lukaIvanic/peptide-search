/**
 * Renderers module - DOM rendering functions.
 */

import { formatFailureReason, getStatusConfig } from './shared/formatting.js';

// DOM helpers
export const $ = (sel) => document.querySelector(sel);
export const $$ = (sel) => Array.from(document.querySelectorAll(sel));

export function fmt(str) {
    return (str ?? '').toString();
}

export function el(tag, cls, text) {
    const e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
}

// Source badge styling
const SOURCE_BADGES = {
    pmc: 'sw-badge sw-badge--source',
    arxiv: 'sw-badge sw-badge--source',
    europepmc: 'sw-badge sw-badge--source',
    semanticscholar: 'sw-badge sw-badge--source',
    upload: 'sw-badge sw-badge--source',
};

const SOURCE_LABELS_SHORT = {
    pmc: 'PMC',
    arxiv: 'ARXIV',
    europepmc: 'EPMC',
    semanticscholar: 'SEM SCH',
    upload: 'UPLOAD',
};

function getSourceLabel(source, { short = false } = {}) {
    if (!source) return 'N/A';
    const key = source.toLowerCase();
    if (short && SOURCE_LABELS_SHORT[key]) {
        return SOURCE_LABELS_SHORT[key];
    }
    return source.toUpperCase();
}

/**
 * Render provider badge in header.
 */
export function renderProviderBadge(provider, model) {
    const badge = $('#providerBadge');
    if (!badge) return;
    
    let displayName;
    if (provider === 'mock') {
        displayName = 'Mock Provider (demo)';
    } else if (provider === 'openai') {
        displayName = `OpenAI ${model || 'GPT-4o'}`;
    } else if (provider === 'deepseek') {
        displayName = `DeepSeek ${model || 'chat'}`;
    } else {
        displayName = provider || 'unknown';
    }
    
    badge.innerHTML = `<span class="text-slate-400">Provider:</span> <span class="font-medium">${displayName}</span>`;
}

export function renderConnectionBadge(status) {
    const badge = $('#connectionBadge');
    if (!badge) return;

    const config = {
        connected: { label: 'Connected', dot: 'sw-dot sw-dot--done' },
        connecting: { label: 'Connecting', dot: 'sw-dot sw-dot--processing' },
        reconnecting: { label: 'Reconnecting', dot: 'sw-dot sw-dot--processing' },
        disconnected: { label: 'Disconnected', dot: 'sw-dot sw-dot--failed' },
    };
    const entry = config[status] || config.connecting;
    badge.innerHTML = `
        <span class="inline-flex items-center gap-2 text-xs">
            <span class="${entry.dot}"></span>
            <span class="sw-kicker text-[10px] text-slate-500">${entry.label}</span>
        </span>
    `;
}

/**
 * Render search results list with selection checkboxes and badges.
 */
export function renderSearchResults(items, selectedMap, onToggle, isSearching = false) {
    const section = $('#searchResultsSection');
    const list = $('#resultsList');
    const selectAllBtn = $('#selectAllResults');
    const clearBtn = $('#clearResultsSelection');
    
    list.innerHTML = '';
    
    // Always show the section once a search has been initiated, so the user
    // gets feedback even if there are 0 results or the search is still running.
    section.classList.remove('hidden');

    if (isSearching) {
        if (selectAllBtn) selectAllBtn.disabled = true;
        if (clearBtn) clearBtn.disabled = true;
        list.appendChild(el('div', 'sw-empty py-6 text-sm text-slate-500 text-center', 'Searching...'));
        return;
    }

    if (!items || items.length === 0) {
        if (selectAllBtn) selectAllBtn.disabled = true;
        if (clearBtn) clearBtn.disabled = true;
        list.appendChild(el('div', 'sw-empty py-6 text-sm text-slate-500 text-center', 'No results found. Try a different query.'));
        return;
    }

    if (selectAllBtn) selectAllBtn.disabled = false;
    if (clearBtn) clearBtn.disabled = selectedMap.size === 0;

    for (const it of items) {
        const key = it.pdf_url || it.url;
        const isSelected = selectedMap.has(key);
        
        const row = el('div', `sw-row list-row py-4 flex items-start gap-3 ${isSelected ? 'sw-row--selected' : ''}`);
        
        // Checkbox
        const checkbox = el('input', 'mt-1 h-4 w-4');
        checkbox.type = 'checkbox';
        checkbox.checked = isSelected;
        checkbox.disabled = !it.pdf_url;
        checkbox.addEventListener('change', () => onToggle(it));
        row.appendChild(checkbox);
        
        // Content
        const content = el('div', 'flex-1 min-w-0');
        
        // Title + badges row
        const titleRow = el('div', 'flex items-start gap-2');
        titleRow.appendChild(el('div', 'list-title flex-1', it.title));
        
        // Status badges (queued/processing/failed/seen/processed)
        const processingStatuses = new Set(['fetching', 'provider', 'validating']);
        if (it.queue_status && processingStatuses.has(it.queue_status)) {
            titleRow.appendChild(el('span', 'sw-badge sw-badge--processing whitespace-nowrap', 'Processing'));
        } else if (it.queue_status === 'failed') {
            titleRow.appendChild(el('span', 'sw-badge sw-badge--failed whitespace-nowrap', 'Failed'));
        } else if (it.queue_status === 'queued' || it.queued) {
            titleRow.appendChild(el('span', 'sw-badge sw-badge--queued whitespace-nowrap', 'Queued'));
        } else if (it.processed) {
            titleRow.appendChild(el('span', 'sw-badge sw-badge--done whitespace-nowrap', 'Processed'));
        } else if (it.seen) {
            titleRow.appendChild(el('span', 'sw-badge sw-badge--warn whitespace-nowrap', 'Seen'));
        }
        content.appendChild(titleRow);
        
        // Meta row
        const sourceBadge = SOURCE_BADGES[it.source] || 'sw-badge sw-badge--source';
        const meta = el('div', 'text-xs text-slate-500 mt-1 flex items-center gap-2');
        meta.appendChild(el('span', sourceBadge, it.source?.toUpperCase() || 'N/A'));
        meta.appendChild(document.createTextNode([it.year, it.doi].filter(Boolean).join(' · ')));
        content.appendChild(meta);
        
        // Authors
        if (it.authors?.length) {
            content.appendChild(el('div', 'text-xs text-slate-500 mt-1 truncate', it.authors.join(', ')));
        }
        
        // Links
        const links = el('div', 'mt-2 flex gap-3');
        if (it.url) {
            const a = el('a', 'sw-chip sw-chip--info text-[10px]', 'View');
            a.href = it.url;
            a.target = '_blank';
            links.appendChild(a);
        }
        if (it.pdf_url) {
            const a = el('a', 'sw-chip sw-chip--success text-[10px]', 'PDF');
            a.href = it.pdf_url;
            a.target = '_blank';
            links.appendChild(a);
        }
        if (!it.pdf_url) {
            links.appendChild(el('span', 'sw-badge sw-badge--warn', 'No PDF'));
        }
        content.appendChild(links);
        
        row.appendChild(content);
        list.appendChild(row);
    }
}

/**
 * Update batch count display.
 */
export function renderBatchCount(count) {
    const countEl = $('#batchCount');
    const btn = $('#startBatchBtn');
    
    if (count > 0) {
        countEl.textContent = `${count} selected`;
        btn.disabled = false;
    } else {
        countEl.textContent = '';
        btn.disabled = true;
    }
}

/**
 * Render the unified papers table.
 */
export function renderPapersTable(papers, onRowClick, options = {}) {
    const table = $('#papersTable');
    const empty = $('#papersEmpty');
    const emptyMessage = options.emptyMessage || 'No papers yet. Search and extract papers to see them here.';
    table.innerHTML = '';
    
    if (!papers || papers.length === 0) {
        if (empty) {
            empty.textContent = emptyMessage;
        }
        empty.classList.remove('hidden');
        return;
    }
    
    empty.classList.add('hidden');
    
    for (const p of papers) {
        const row = el('div', 'sw-row list-row sw-row--table px-6 py-4 cursor-pointer');
        row.setAttribute('role', 'button');
        row.setAttribute('tabindex', '0');
        row.setAttribute('aria-label', `Open details for ${p.title}`);
        row.addEventListener('click', () => onRowClick(p.id));
        row.addEventListener('keydown', (event) => {
            if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault();
                onRowClick(p.id);
            }
        });
        
        // Status indicator
        const statusConfig = getStatusConfig(p.status || 'queued');
        const statusBadge = el(
            'span',
            `sw-badge ${statusConfig.badge} w-28 text-center flex-shrink-0`,
            statusConfig.label,
        );
        row.appendChild(statusBadge);
        
        // Source badge
        const sourceBadge = SOURCE_BADGES[p.source] || 'sw-badge sw-badge--source';
        row.appendChild(el('span', `${sourceBadge} w-20 text-center flex-shrink-0`, getSourceLabel(p.source, { short: true })));
        
        // Title
        const titleWrap = el('div', 'flex-1 min-w-0');
        titleWrap.appendChild(el('div', 'list-title truncate', p.title));
        if (p.failure_reason) {
            const friendly = formatFailureReason(p.failure_reason);
            const message = friendly?.title || p.failure_reason;
            const reason = el('div', 'text-xs text-red-600 truncate', message);
            reason.title = friendly?.detail || p.failure_reason;
            titleWrap.appendChild(reason);
        }
        row.appendChild(titleWrap);
        
        // DOI/URL
        const doi = p.doi || p.url || '';
        row.appendChild(el('div', 'text-xs text-slate-500 w-32 truncate flex-shrink-0', doi));
        
        // Last run time
        const timeStr = p.last_run_at ? new Date(p.last_run_at).toLocaleString() : '—';
        row.appendChild(el('div', 'text-xs text-slate-400 w-36 text-right flex-shrink-0', timeStr));

        // Actions for failed runs are shown in the details drawer only.
        
        table.appendChild(row);
    }
}

/**
 * Render queue stats.
 */
export function renderQueueStats(stats) {
    const el = $('#queueStats');
    if (!el) return;
    
    if (stats.queued > 0 || stats.processing > 0) {
        el.textContent = `${stats.processing} processing, ${stats.queued} queued`;
        $('#progressBar').classList.remove('hidden');
    } else {
        el.textContent = '';
        $('#progressBar').classList.add('hidden');
    }
}

// Callbacks for drawer actions (set by app.js)
let drawerCallbacks = {
    onRetry: null,
    onForceReextract: null,
    onResolveSource: null,
    onUpload: null,
    onRetryWithSource: null,
};

/**
 * Set callbacks for drawer actions.
 */
export function setDrawerCallbacks(callbacks) {
    drawerCallbacks = { ...drawerCallbacks, ...callbacks };
}

/**
 * Render paper detail drawer.
 */
export function renderDrawer(paper, runs, options = {}) {
    const content = $('#drawerContent');
    content.innerHTML = '';
    const resolvedSources = options.resolvedSources || {};
    
    if (!paper) return;
    
    // Paper header
    const header = el('div', 'mb-6');
    header.appendChild(el('h4', 'list-title leading-snug', paper.title));
    
    const meta = el('div', 'text-xs text-slate-500 mt-2 space-y-1');
    if (paper.authors?.length) {
        meta.appendChild(el('div', '', paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' et al.' : '')));
    }
    const metaLine = [paper.source?.toUpperCase(), paper.year, paper.doi].filter(Boolean).join(' · ');
    if (metaLine) meta.appendChild(el('div', '', metaLine));
    if (paper.url) {
        const link = el('a', 'sw-chip sw-chip--info text-[10px]', 'View Article');
        link.href = paper.url;
        link.target = '_blank';
        meta.appendChild(link);
    }
    header.appendChild(meta);
    
    // Force Re-extract button (show if paper has stored status)
    if (paper.status === 'stored' && paper.id && drawerCallbacks.onForceReextract) {
        const actionsRow = el('div', 'mt-4 flex flex-wrap items-center gap-2');

        const catalog = options.providerCatalog || [];
        const defaultProvider = options.selectedProvider || '';
        const defaultModel = options.selectedModel || '';

        // Provider select
        const providerSel = el('select', 'sw-select sw-select--sm text-[11px]');
        for (const p of catalog) {
            const opt = document.createElement('option');
            opt.value = p.provider_id;
            opt.textContent = p.label || p.provider_id;
            if (p.provider_id === defaultProvider) opt.selected = true;
            providerSel.appendChild(opt);
        }

        // Model select
        const modelSel = el('select', 'sw-select sw-select--sm text-[11px] min-w-[8rem]');
        const populateModels = (providerId) => {
            modelSel.innerHTML = '';
            const row = catalog.find(p => p.provider_id === providerId);
            const models = row ? [...new Set([row.default_model, ...(row.curated_models || [])].filter(Boolean))] : [];
            if (!models.length) {
                const opt = document.createElement('option');
                opt.value = '';
                opt.textContent = 'Default';
                modelSel.appendChild(opt);
            } else {
                for (const m of models) {
                    const opt = document.createElement('option');
                    opt.value = m;
                    opt.textContent = m;
                    if (m === defaultModel) opt.selected = true;
                    modelSel.appendChild(opt);
                }
                if (!modelSel.value && models[0]) modelSel.value = models[0];
            }
        };
        populateModels(providerSel.value);
        providerSel.addEventListener('change', () => populateModels(providerSel.value));

        const forceBtn = el('button', 'sw-btn sw-btn--sm sw-btn--primary', 'Force Re-extract');
        forceBtn.addEventListener('click', () => {
            const p = providerSel.value || null;
            const m = modelSel.value || null;
            drawerCallbacks.onForceReextract(paper.id, p, m);
        });

        actionsRow.appendChild(providerSel);
        actionsRow.appendChild(modelSel);
        actionsRow.appendChild(forceBtn);
        header.appendChild(actionsRow);
    }
    
    content.appendChild(header);
    
    // Runs section
    content.appendChild(el('div', 'sw-kicker text-xs text-slate-500 mb-3', `Extraction Runs (${runs.length})`));
    
    if (runs.length === 0) {
        content.appendChild(el('div', 'sw-empty text-sm text-slate-500 p-3', 'No extraction runs yet.'));
        return;
    }
    
    const runsList = el('div', 'space-y-4');
    for (const run of runs) {
        const statusConfig = getStatusConfig(run.status || 'queued');
        
        const card = el('div', `sw-card ${run.status === 'failed' ? 'sw-card--error' : ''} p-4`);
        
        // Run header
        const runHeader = el('div', 'flex items-center justify-between mb-2');
        const statusBadge = el('span', `sw-badge ${statusConfig.badge}`, statusConfig.label);
        runHeader.appendChild(statusBadge);
        const time = el('span', 'text-xs text-slate-400', run.created_at ? new Date(run.created_at).toLocaleString() : '');
        runHeader.appendChild(time);
        card.appendChild(runHeader);
        
        const runBody = el('div', '');

        // View run details button
        if (run.id) {
            const detailRow = el('div', 'mb-2');
            const link = el('a', 'sw-btn sw-btn--sm sw-btn--primary', 'Details / Follow-up Chat');
            link.href = `/runs/${run.id}`;
            link.target = '_blank';
            detailRow.appendChild(link);
            runBody.appendChild(detailRow);
        }
        
        // Model info
        if (run.model_provider || run.model_name) {
            runBody.appendChild(el('div', 'text-xs text-slate-500 mb-2', `${run.model_provider || ''} ${run.model_name || ''}`.trim()));
        }

        // Failure reason with fix actions
        if (run.failure_reason) {
            const errorBox = el('div', 'mt-2 p-2 sw-card sw-card--error text-xs');
            const friendly = formatFailureReason(run.failure_reason);
            if (friendly) {
                errorBox.appendChild(el('div', 'text-slate-700 font-medium', friendly.title));
                if (friendly.detail) {
                    errorBox.appendChild(el('div', 'mt-1 text-[11px] text-slate-500', friendly.detail));
                }
            } else {
                errorBox.textContent = run.failure_reason;
            }
            runBody.appendChild(errorBox);
        }
        
        if (run.status === 'failed' && run.id) {
            const actionRow = el('div', 'mt-2 flex flex-wrap items-center gap-2');
            if (drawerCallbacks.onRetry) {
                const catalog = options.providerCatalog || [];
                const defaultProvider = run.model_provider || options.selectedProvider || '';
                const defaultModel = run.model_name || options.selectedModel || '';

                // Provider select
                const providerSel = el('select', 'sw-select sw-select--sm text-[11px]');
                for (const p of catalog) {
                    const opt = document.createElement('option');
                    opt.value = p.provider_id;
                    opt.textContent = p.label || p.provider_id;
                    if (p.provider_id === defaultProvider) opt.selected = true;
                    providerSel.appendChild(opt);
                }

                // Model select
                const modelSel = el('select', 'sw-select sw-select--sm text-[11px] min-w-[8rem]');
                const populateModels = (providerId) => {
                    modelSel.innerHTML = '';
                    const row = catalog.find(p => p.provider_id === providerId);
                    const models = row ? [...new Set([row.default_model, ...(row.curated_models || [])].filter(Boolean))] : [];
                    if (!models.length) {
                        const opt = document.createElement('option');
                        opt.value = '';
                        opt.textContent = 'Default';
                        modelSel.appendChild(opt);
                    } else {
                        for (const m of models) {
                            const opt = document.createElement('option');
                            opt.value = m;
                            opt.textContent = m;
                            if (m === defaultModel) opt.selected = true;
                            modelSel.appendChild(opt);
                        }
                        if (!modelSel.value && models[0]) modelSel.value = models[0];
                    }
                };
                populateModels(providerSel.value);
                providerSel.addEventListener('change', () => populateModels(providerSel.value));

                // Retry button — works for all runs. For upload runs the file
                // survives (read_upload, 24h TTL), so Retry will work unless
                // the file has expired, in which case Upload & Retry is the fallback.
                const retryBtn = el('button', 'sw-btn sw-btn--sm sw-btn--danger', 'Retry');
                retryBtn.addEventListener('click', () => {
                    const p = providerSel.value || null;
                    const m = modelSel.value || null;
                    drawerCallbacks.onRetry(run.id, p, m);
                });
                actionRow.appendChild(providerSel);
                actionRow.appendChild(modelSel);
                actionRow.appendChild(retryBtn);

                // Upload & Retry — secondary option for upload runs (if file expired)
                const isUploadRun = run.pdf_url && run.pdf_url.startsWith('upload://');
                if (isUploadRun && drawerCallbacks.onUpload) {
                    const uploadRetryBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost', 'Upload & Retry');
                    const fileInput2 = el('input', ''); fileInput2.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden;';
                    fileInput2.type = 'file';
                    fileInput2.accept = '.pdf';
                    fileInput2.multiple = true;
                    uploadRetryBtn.addEventListener('click', () => fileInput2.click());
                    fileInput2.addEventListener('change', () => {
                        const files = fileInput2.files;
                        if (!files || files.length === 0) return;
                        // Give immediate visual feedback in the drawer
                        uploadRetryBtn.disabled = true;
                        uploadRetryBtn.textContent = 'Uploading…';
                        retryBtn.disabled = true;
                        const p = providerSel.value || null;
                        const m = modelSel.value || null;
                        drawerCallbacks.onUpload(run.id, files, p, m);
                    });
                    actionRow.appendChild(uploadRetryBtn);
                    actionRow.appendChild(fileInput2);
                }
            }
            if (drawerCallbacks.onResolveSource) {
                const resolveBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost', 'Find OA PDF');
                resolveBtn.addEventListener('click', () => drawerCallbacks.onResolveSource(run.id));
                actionRow.appendChild(resolveBtn);
            }
            if (drawerCallbacks.onUpload) {
                const uploadBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost', 'Upload PDF');
                const fileInput = el('input', ''); fileInput.style.cssText = 'position:absolute;left:-9999px;width:1px;height:1px;opacity:0;overflow:hidden;';
                fileInput.type = 'file';
                fileInput.accept = '.pdf';
                fileInput.multiple = true;
                uploadBtn.addEventListener('click', () => fileInput.click());
                fileInput.addEventListener('change', () => {
                    const files = fileInput.files;
                    if (!files || files.length === 0) return;
                    uploadBtn.disabled = true;
                    uploadBtn.textContent = 'Uploading…';
                    drawerCallbacks.onUpload(run.id, files);
                });
                actionRow.appendChild(uploadBtn);
                actionRow.appendChild(fileInput);
            }
            if (resolvedSources[run.id] && drawerCallbacks.onRetryWithSource) {
                const resolved = resolvedSources[run.id];
                const resolvedLabel = el('div', 'text-[10px] text-slate-500', `Resolved ${resolved.label}: ${resolved.url}`);
                actionRow.appendChild(resolvedLabel);
                const runNowBtn = el('button', 'sw-btn sw-btn--sm sw-btn--primary', 'Run now');
                runNowBtn.addEventListener('click', () => drawerCallbacks.onRetryWithSource(run.id, resolved.url));
                actionRow.appendChild(runNowBtn);
            }
            if (actionRow.childNodes.length) {
                runBody.appendChild(actionRow);
            }
        }
        
        // Extracted entities summary
        if (run.entity_count !== undefined && run.entity_count > 0) {
            runBody.appendChild(el('div', 'mt-2 text-xs text-emerald-700', `${run.entity_count} entities extracted`));
        }
        
        // Comment
        if (run.comment) {
            const commentBox = el('div', 'mt-2 p-2 sw-card sw-card--note text-xs');
            commentBox.textContent = run.comment;
            runBody.appendChild(commentBox);
        }

        // Entities summary (from raw_json/payload)
        const entities = getRunEntities(run);
        if (entities.length > 0) {
            runBody.appendChild(renderEntitiesSummary(entities));
        }
        
        // Collapsible section container
        const collapsibles = el('div', 'mt-3 space-y-2');
        
        // Collapsible Prompts
        if (run.prompts) {
            const promptsSection = createCollapsibleSection('Prompts', run.prompts);
            collapsibles.appendChild(promptsSection);
        }
        
        // Collapsible JSON
        if (run.raw_json || run.payload) {
            const jsonData = getRunPayload(run);
            if (jsonData) {
                const jsonSection = createCollapsibleSection('Response JSON', jsonData);
                collapsibles.appendChild(jsonSection);
            }
        }
        
        if (collapsibles.children.length > 0) {
            runBody.appendChild(collapsibles);
        }

        const runDetails = createElementCollapsible('Run details', runBody, {
            defaultOpen: true,
            toggleClass: 'mt-2',
            contentClass: 'mt-2'
        });
        card.appendChild(runDetails);
        
        runsList.appendChild(card);
    }
    content.appendChild(runsList);
}

function getRunPayload(run) {
    const raw = run.raw_json ?? run.payload;
    if (!raw) return null;
    if (typeof raw === 'string') {
        try {
            return JSON.parse(raw);
        } catch {
            return null;
        }
    }
    return raw;
}

function getRunEntities(run) {
    const payload = getRunPayload(run);
    const entities = payload && Array.isArray(payload.entities) ? payload.entities : [];
    return entities;
}

function createElementCollapsible(label, contentEl, { defaultOpen = true, toggleClass = '', contentClass = '' } = {}) {
    const container = el('div', '');
    const toggle = el('button', ['sw-toggle', 'text-xs', 'flex', 'items-center', 'gap-1', toggleClass].filter(Boolean).join(' '));
    toggle.type = 'button';
    const arrow = el('span', 'sw-toggle__arrow transition-transform', '▶');
    if (defaultOpen) {
        arrow.style.transform = 'rotate(90deg)';
    }
    toggle.appendChild(arrow);
    toggle.appendChild(document.createTextNode(` ${label}`));

    const contentWrap = el('div', [defaultOpen ? '' : 'hidden', contentClass].filter(Boolean).join(' '));
    if (!defaultOpen) contentWrap.classList.add('hidden');
    contentWrap.appendChild(contentEl);

    toggle.addEventListener('click', () => {
        contentWrap.classList.toggle('hidden');
        arrow.style.transform = contentWrap.classList.contains('hidden') ? '' : 'rotate(90deg)';
    });

    container.appendChild(toggle);
    container.appendChild(contentWrap);
    return container;
}

function renderEntitiesSummary(entities) {
    const section = el('div', 'mt-3');
    section.appendChild(el('div', 'sw-kicker text-xs text-slate-500 mb-2', `Entities (${entities.length})`));

    const list = el('div', 'space-y-2');
    entities.forEach((entity, idx) => {
        const card = el('div', 'sw-card p-3');
        const typeLabel = (entity?.type || 'entity').toUpperCase();
        card.appendChild(el('div', 'text-xs font-medium text-slate-700', `#${idx + 1} ${typeLabel}`));

        const detailBody = el('div', '');
        if (entity?.type === 'peptide' && entity.peptide) {
            const peptide = entity.peptide;
            const seq = peptide.sequence_one_letter || peptide.sequence_three_letter;
            if (seq) {
                card.appendChild(el('div', 'text-sm text-slate-900 mt-1 sw-entity-seq', seq));
            }
            const mods = [peptide.n_terminal_mod, peptide.c_terminal_mod].filter(Boolean).join(' ');
            if (mods) {
                detailBody.appendChild(el('div', 'text-xs text-slate-500 mt-1', mods));
            }
            if (peptide.is_hydrogel !== undefined && peptide.is_hydrogel !== null) {
                detailBody.appendChild(el('div', 'text-xs text-slate-500 mt-1', peptide.is_hydrogel ? 'Hydrogel: yes' : 'Hydrogel: no'));
            }
        }

        if (entity?.type === 'molecule' && entity.molecule) {
            const molecule = entity.molecule;
            const identifiers = [molecule.chemical_formula, molecule.smiles, molecule.inchi].filter(Boolean);
            if (identifiers.length > 0) {
                card.appendChild(el('div', 'text-sm text-slate-900 mt-1 sw-entity-seq', identifiers[0]));
                if (identifiers.length > 1) {
                    detailBody.appendChild(el('div', 'text-xs text-slate-500 mt-1', identifiers.slice(1).join(' | ')));
                }
            }
        }

        const conditions = entity?.conditions || {};
        const conditionParts = [];
        if (conditions.ph !== undefined && conditions.ph !== null) {
            conditionParts.push(`pH ${conditions.ph}`);
        }
        if (conditions.concentration !== undefined && conditions.concentration !== null) {
            const units = conditions.concentration_units ? ` ${conditions.concentration_units}` : '';
            conditionParts.push(`${conditions.concentration}${units}`);
        }
        if (conditions.temperature_c !== undefined && conditions.temperature_c !== null) {
            conditionParts.push(`${conditions.temperature_c} C`);
        }
        if (conditionParts.length > 0) {
            detailBody.appendChild(el('div', 'text-xs text-slate-500 mt-2', conditionParts.join(' · ')));
        }

        const labels = Array.isArray(entity?.labels) ? entity.labels : [];
        const morphology = Array.isArray(entity?.morphology) ? entity.morphology : [];
        const methods = Array.isArray(entity?.validation_methods) ? entity.validation_methods : [];
        const traits = Array.isArray(entity?.reported_characteristics) ? entity.reported_characteristics : [];
        const listParts = [];
        if (labels.length > 0) listParts.push(`Labels: ${labels.join(', ')}`);
        if (morphology.length > 0) listParts.push(`Morphology: ${morphology.join(', ')}`);
        if (methods.length > 0) listParts.push(`Methods: ${methods.join(', ')}`);
        if (traits.length > 0) listParts.push(`Traits: ${traits.join(', ')}`);
        if (listParts.length > 0) {
            detailBody.appendChild(el('div', 'text-xs text-slate-500 mt-2', listParts.join(' | ')));
        }

        if (entity?.process_protocol) {
            detailBody.appendChild(el('div', 'text-xs text-slate-500 mt-2', `Protocol: ${entity.process_protocol}`));
        }

        if (detailBody.childNodes.length > 0) {
            const details = createElementCollapsible('Details', detailBody, {
                defaultOpen: true,
                toggleClass: 'mt-2',
                contentClass: 'mt-2'
            });
            card.appendChild(details);
        }

        list.appendChild(card);
    });

    section.appendChild(list);
    return section;
}

/**
 * Create a collapsible section with JSON content.
 */
function createCollapsibleSection(label, data) {
    const container = el('div', '');
    
    const toggle = el('button', 'sw-toggle flex items-center gap-1');
    const arrow = el('span', 'sw-toggle__arrow transition-transform', '▶');
    toggle.appendChild(arrow);
    toggle.appendChild(document.createTextNode(` ${label}`));
    
    const content = el('pre', 'sw-terminal mt-2 p-3 text-[10px] leading-relaxed max-h-64 overflow-auto hidden');
    try {
        content.textContent = JSON.stringify(data, null, 2);
    } catch {
        content.textContent = String(data);
    }
    
    toggle.addEventListener('click', () => {
        content.classList.toggle('hidden');
        arrow.style.transform = content.classList.contains('hidden') ? '' : 'rotate(90deg)';
    });
    
    container.appendChild(toggle);
    container.appendChild(content);
    return container;
}

/**
 * Open/close the drawer.
 */
export function setDrawerOpen(open) {
    const drawer = $('#paperDrawer');
    const overlay = $('#drawerOverlay');
    
    if (open) {
        drawer.classList.remove('translate-x-full');
        overlay.classList.remove('hidden');
    } else {
        drawer.classList.add('translate-x-full');
        overlay.classList.add('hidden');
    }
}

/**
 * Set search count display.
 */
export function setSearchCount(text) {
    $('#searchCount').textContent = text;
}
