/**
 * Renderers module - DOM rendering functions.
 */

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

// Status display config (no emojis, subtle colors)
const STATUS_CONFIG = {
    queued: { label: 'Queued', badge: 'sw-badge--queued', dot: 'sw-dot sw-dot--queued' },
    fetching: { label: 'Fetching', badge: 'sw-badge--processing', dot: 'sw-dot sw-dot--processing' },
    provider: { label: 'Processing', badge: 'sw-badge--processing', dot: 'sw-dot sw-dot--processing' },
    validating: { label: 'Validating', badge: 'sw-badge--processing', dot: 'sw-dot sw-dot--processing' },
    stored: { label: 'Done', badge: 'sw-badge--done', dot: 'sw-dot sw-dot--done' },
    failed: { label: 'Failed', badge: 'sw-badge--failed', dot: 'sw-dot sw-dot--failed' },
    cancelled: { label: 'Cancelled', badge: 'sw-badge--warn', dot: 'sw-dot sw-dot--muted' },
};

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
        connected: { label: 'Connected', text: 'text-emerald-700', dot: 'bg-emerald-500' },
        connecting: { label: 'Connecting', text: 'text-amber-700', dot: 'bg-amber-500' },
        reconnecting: { label: 'Reconnecting', text: 'text-amber-700', dot: 'bg-amber-500' },
        disconnected: { label: 'Disconnected', text: 'text-red-700', dot: 'bg-red-500' },
    };
    const entry = config[status] || config.connecting;
    badge.innerHTML = `
        <span class="inline-flex items-center gap-1 text-xs ${entry.text}">
            <span class="w-2 h-2 rounded-full ${entry.dot}"></span>
            ${entry.label}
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
        
        const row = el('div', `py-4 flex items-start gap-3 sw-row ${isSelected ? 'sw-row--selected' : ''}`);
        
        // Checkbox
        const checkbox = el('input', 'mt-1 h-4 w-4 rounded border-slate-300 text-indigo-600 focus:ring-indigo-500');
        checkbox.type = 'checkbox';
        checkbox.checked = isSelected;
        checkbox.disabled = !it.pdf_url;
        checkbox.addEventListener('change', () => onToggle(it));
        row.appendChild(checkbox);
        
        // Content
        const content = el('div', 'flex-1 min-w-0');
        
        // Title + badges row
        const titleRow = el('div', 'flex items-start gap-2');
        titleRow.appendChild(el('div', 'text-sm font-medium text-slate-900 flex-1', it.title));
        
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
            const a = el('a', 'sw-chip text-[10px] text-indigo-600 hover:bg-indigo-50', 'View');
            a.href = it.url;
            a.target = '_blank';
            links.appendChild(a);
        }
        if (it.pdf_url) {
            const a = el('a', 'sw-chip text-[10px] text-emerald-600 hover:bg-emerald-50', 'PDF');
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
        const row = el('div', 'sw-row px-6 py-4 hover:bg-slate-50 cursor-pointer transition-colors flex items-center gap-4');
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
        const statusConfig = STATUS_CONFIG[p.status] || STATUS_CONFIG.queued;
        const statusBadge = el('div', 'flex items-center gap-2 w-28 flex-shrink-0');
        const dot = el('span', `w-2 h-2 rounded-full ${statusConfig.dot}`);
        statusBadge.appendChild(dot);
        statusBadge.appendChild(el('span', 'sw-status', statusConfig.label));
        row.appendChild(statusBadge);
        
        // Source badge
        const sourceBadge = SOURCE_BADGES[p.source] || 'sw-badge sw-badge--source';
        row.appendChild(el('span', `${sourceBadge} w-20 text-center flex-shrink-0`, p.source?.toUpperCase() || 'N/A'));
        
        // Title
        const titleWrap = el('div', 'flex-1 min-w-0');
        titleWrap.appendChild(el('div', 'text-sm font-medium text-slate-900 truncate', p.title));
        if (p.failure_reason) {
            titleWrap.appendChild(el('div', 'text-xs text-red-600 truncate', p.failure_reason));
        }
        row.appendChild(titleWrap);
        
        // DOI/URL
        const doi = p.doi || p.url || '';
        row.appendChild(el('div', 'text-xs text-slate-500 w-32 truncate flex-shrink-0', doi));
        
        // Last run time
        const timeStr = p.last_run_at ? new Date(p.last_run_at).toLocaleString() : '—';
        row.appendChild(el('div', 'text-xs text-slate-400 w-36 text-right flex-shrink-0', timeStr));
        
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
export function renderDrawer(paper, runs) {
    const content = $('#drawerContent');
    content.innerHTML = '';
    
    if (!paper) return;
    
    // Paper header
    const header = el('div', 'mb-6');
    header.appendChild(el('h4', 'text-lg font-semibold text-slate-900 leading-snug', paper.title));
    
    const meta = el('div', 'text-xs text-slate-500 mt-2 space-y-1');
    if (paper.authors?.length) {
        meta.appendChild(el('div', '', paper.authors.slice(0, 3).join(', ') + (paper.authors.length > 3 ? ' et al.' : '')));
    }
    const metaLine = [paper.source?.toUpperCase(), paper.year, paper.doi].filter(Boolean).join(' · ');
    if (metaLine) meta.appendChild(el('div', '', metaLine));
    if (paper.url) {
        const link = el('a', 'sw-chip text-indigo-600 hover:bg-indigo-50', 'View Article');
        link.href = paper.url;
        link.target = '_blank';
        meta.appendChild(link);
    }
    header.appendChild(meta);
    
    // Force Re-extract button (show if paper has stored status)
    if (paper.status === 'stored' && paper.id && drawerCallbacks.onForceReextract) {
        const actionsRow = el('div', 'mt-4 flex gap-2');
        const forceBtn = el('button', 'px-3 py-1.5 rounded-lg text-xs font-medium bg-indigo-100 text-indigo-700 hover:bg-indigo-200 transition-colors', 'Force Re-extract');
        forceBtn.addEventListener('click', () => drawerCallbacks.onForceReextract(paper.id));
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
        const statusConfig = STATUS_CONFIG[run.status] || STATUS_CONFIG.queued;
        
        const card = el('div', `sw-card ${run.status === 'failed' ? 'sw-card--error' : ''} p-4`);
        
        // Run header
        const runHeader = el('div', 'flex items-center justify-between mb-2');
        const statusBadge = el('span', `sw-badge ${statusConfig.badge}`, statusConfig.label);
        runHeader.appendChild(statusBadge);
        const time = el('span', 'text-xs text-slate-400', run.created_at ? new Date(run.created_at).toLocaleString() : '');
        runHeader.appendChild(time);
        card.appendChild(runHeader);
        
        // View run details button
        if (run.id) {
            const detailRow = el('div', 'mb-2');
            const link = el('a', 'inline-flex items-center px-3 py-1.5 rounded-md bg-indigo-600 text-white text-xs font-medium hover:bg-indigo-700 transition-colors', 'Details / Follow-up Chat');
            link.href = `/runs/${run.id}`;
            link.target = '_blank';
            detailRow.appendChild(link);
            card.appendChild(detailRow);
        }

        // Model info
        if (run.model_provider || run.model_name) {
            card.appendChild(el('div', 'text-xs text-slate-500 mb-2', `${run.model_provider || ''} ${run.model_name || ''}`.trim()));
        }
        
        // Failure reason with Retry button
        if (run.failure_reason) {
            const errorBox = el('div', 'mt-2 p-2 sw-card sw-card--error text-xs');
            errorBox.textContent = run.failure_reason;
            card.appendChild(errorBox);
        }
        
        // Retry button for failed runs
        if (run.status === 'failed' && run.id && drawerCallbacks.onRetry) {
            const retryBtn = el('button', 'mt-2 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-600 text-white hover:bg-red-700 transition-colors', 'Retry');
            retryBtn.addEventListener('click', () => drawerCallbacks.onRetry(run.id));
            card.appendChild(retryBtn);
        }
        
        // Extracted entities summary
        if (run.entity_count !== undefined && run.entity_count > 0) {
            card.appendChild(el('div', 'mt-2 text-xs text-emerald-700', `${run.entity_count} entities extracted`));
        }
        
        // Comment
        if (run.comment) {
            const commentBox = el('div', 'mt-2 p-2 sw-card sw-card--note text-xs');
            commentBox.textContent = run.comment;
            card.appendChild(commentBox);
        }

        // Entities summary (from raw_json/payload)
        const entities = getRunEntities(run);
        if (entities.length > 0) {
            card.appendChild(renderEntitiesSummary(entities));
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
            card.appendChild(collapsibles);
        }
        
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

function renderEntitiesSummary(entities) {
    const section = el('div', 'mt-3');
    section.appendChild(el('div', 'sw-kicker text-xs text-slate-500 mb-2', `Entities (${entities.length})`));

    const list = el('div', 'space-y-2');
    entities.forEach((entity, idx) => {
        const card = el('div', 'sw-card p-3');
        const typeLabel = (entity?.type || 'entity').toUpperCase();
        card.appendChild(el('div', 'text-xs font-medium text-slate-700', `#${idx + 1} ${typeLabel}`));

        if (entity?.type === 'peptide' && entity.peptide) {
            const peptide = entity.peptide;
            const seq = peptide.sequence_one_letter || peptide.sequence_three_letter;
            if (seq) {
                card.appendChild(el('div', 'text-sm text-slate-900 mt-1', seq));
            }
            const mods = [peptide.n_terminal_mod, peptide.c_terminal_mod].filter(Boolean).join(' ');
            if (mods) {
                card.appendChild(el('div', 'text-xs text-slate-500 mt-1', mods));
            }
            if (peptide.is_hydrogel !== undefined && peptide.is_hydrogel !== null) {
                card.appendChild(el('div', 'text-xs text-slate-500 mt-1', peptide.is_hydrogel ? 'Hydrogel: yes' : 'Hydrogel: no'));
            }
        }

        if (entity?.type === 'molecule' && entity.molecule) {
            const molecule = entity.molecule;
            const identifiers = [molecule.chemical_formula, molecule.smiles, molecule.inchi].filter(Boolean);
            if (identifiers.length > 0) {
                card.appendChild(el('div', 'text-sm text-slate-900 mt-1', identifiers[0]));
                if (identifiers.length > 1) {
                    card.appendChild(el('div', 'text-xs text-slate-500 mt-1', identifiers.slice(1).join(' | ')));
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
            card.appendChild(el('div', 'text-xs text-slate-500 mt-2', conditionParts.join(' · ')));
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
            card.appendChild(el('div', 'text-xs text-slate-500 mt-2', listParts.join(' | ')));
        }

        if (entity?.process_protocol) {
            card.appendChild(el('div', 'text-xs text-slate-500 mt-2', `Protocol: ${entity.process_protocol}`));
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
    
    const toggle = el('button', 'text-xs text-indigo-600 hover:underline flex items-center gap-1');
    const arrow = el('span', 'transition-transform', '▶');
    toggle.appendChild(arrow);
    toggle.appendChild(document.createTextNode(` ${label}`));
    
    const content = el('pre', 'mt-2 p-3 bg-slate-900 text-slate-100 rounded text-[10px] leading-relaxed max-h-64 overflow-auto hidden');
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
