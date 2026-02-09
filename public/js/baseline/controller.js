import * as api from './actions/baseline_actions.js';
import { $, el, fmt } from './views/baseline_views.js';
import {
	MANUAL_PDF_DETAILS,
	MANUAL_PDF_REASON_NO_OA,
	MANUAL_PDF_TAG,
	bucketizeDeltas,
	formatFailureReason,
	formatNumber,
	formatPercent,
	getBatchIdFromUrl,
	getCaseKey,
	getStatusLabel,
	getTopEntries,
	incrementCount,
	isLocalPdfUrl,
	isNoSourceResolvedFailure,
	isProcessingStatus,
	isProviderEmptyFailure,
	mean,
	median,
	normalizeDoiToUrl,
	normalizeDoiVersion,
	normalizeSequence,
} from './domain/formatters.js';

const state = {
	cases: [],
	datasets: [],
	batches: [],
	filterDataset: 'self_assembly', // Default to self_assembly dataset
	filterBatchId: '',
	search: '',
	selectedPaperKey: null, // Changed from selectedId to track paper group
	provider: 'openai-nano',
	pdfStatusFilter: 'all',
	resolvedSource: null,
	stagedFile: null,
	runPayloadCache: new Map(),
	comparisonCache: new Map(),
	manualPdfReasons: new Map(),
	paperComparisonCache: new Map(), // Cache for paper-level comparisons
	localPdfByCaseId: new Map(),
	localPdfFileByCaseId: new Map(),
	singleBatchMode: false, // True when viewing /baseline/{batch_id}
};

let sseConnection = null;
let analysisToken = 0;

function updateStatus(message) {
	const status = $('#baselineStatus');
	if (status) status.textContent = message || '';
}


function ensureButtonLabel(button) {
	if (!button) return null;
	let label = button.querySelector('.sw-btn__label');
	if (!label) {
		label = el('span', 'sw-btn__label', button.textContent.trim());
		button.textContent = '';
		button.appendChild(label);
	}
	return label;
}

function setButtonLoading(button, isLoading, labelText = null) {
	if (!button) return;
	const label = ensureButtonLabel(button);
	if (isLoading) {
		if (!button.dataset.originalLabel) {
			button.dataset.originalLabel = label?.textContent || '';
		}
		button.disabled = true;
		button.classList.add('sw-btn--loading', 'cursor-not-allowed');
		if (!button.querySelector('.sw-spinner')) {
			const spinner = el('span', 'sw-spinner h-3 w-3 rounded-full');
			spinner.setAttribute('aria-hidden', 'true');
			button.prepend(spinner);
		}
		if (labelText !== null && label) {
			label.textContent = labelText;
		}
	} else {
		button.disabled = false;
		button.classList.remove('sw-btn--loading', 'cursor-not-allowed');
		const spinner = button.querySelector('.sw-spinner');
		if (spinner) spinner.remove();
		if (button.dataset.originalLabel && label) {
			label.textContent = button.dataset.originalLabel;
		}
		delete button.dataset.originalLabel;
	}
}

function createExternalLink(url, className = '') {
	const link = el('a', `underline text-cyan-500 hover:text-cyan-400 ${className}`.trim(), url);
	link.href = url;
	link.target = '_blank';
	link.rel = 'noopener';
	return link;
}


function getPreferredPdfUrl(caseItem, runPayload = null) {
	return (
		runPayload?.run?.pdf_url ||
		runPayload?.paper?.pdf_url ||
		runPayload?.paper?.url ||
		caseItem?.pdf_url ||
		caseItem?.paper_url ||
		null
	);
}


function markLocalPdfForGroup(paperGroup, sourceUrl) {
	if (!paperGroup?.cases?.length || !isLocalPdfUrl(sourceUrl)) return;
	paperGroup.cases.forEach((caseItem) => {
		if (caseItem?.id) {
			state.localPdfByCaseId.set(caseItem.id, true);
		}
	});
}

function isLocalPdfAvailable(paperGroup, runPayload = null) {
	if (!paperGroup?.cases?.length) return false;
	const preferred = getPreferredPdfUrl(paperGroup, runPayload);
	if (isLocalPdfUrl(preferred)) return true;
	if (paperGroup.cases.some((caseItem) => state.localPdfFileByCaseId.get(caseItem.id))) return true;
	if (paperGroup.cases.some((caseItem) => state.localPdfByCaseId.get(caseItem.id))) return true;
	const resolved = state.resolvedSource && paperGroup.cases.some((c) => c.id === state.resolvedSource.caseId)
		? state.resolvedSource.url
		: null;
	return isLocalPdfUrl(resolved);
}

function isLocalPdfFileAvailable(paperGroup) {
	if (!paperGroup?.cases?.length) return false;
	return paperGroup.cases.some((caseItem) => state.localPdfFileByCaseId.get(caseItem.id));
}


function getManualPdfStatus(caseItem, runPayload = null) {
	if (!caseItem) return null;
	const run = runPayload?.run || caseItem?.latest_run || null;
	if (run?.status === 'failed' && isProviderEmptyFailure(run.failure_reason)) {
		return {
			tag: MANUAL_PDF_TAG,
			detail: MANUAL_PDF_DETAILS.provider_empty,
			reason: 'provider-empty',
		};
	}
	if (run?.status === 'failed' && isNoSourceResolvedFailure(run.failure_reason)) {
		return {
			tag: MANUAL_PDF_TAG,
			detail: MANUAL_PDF_DETAILS[MANUAL_PDF_REASON_NO_OA],
			reason: MANUAL_PDF_REASON_NO_OA,
		};
	}
	const manualReason = caseItem.id ? state.manualPdfReasons.get(caseItem.id) : null;
	if (manualReason === MANUAL_PDF_REASON_NO_OA) {
		return {
			tag: MANUAL_PDF_TAG,
			detail: MANUAL_PDF_DETAILS[MANUAL_PDF_REASON_NO_OA],
			reason: manualReason,
		};
	}
	return null;
}

function buildRunIndicator(status) {
	const statusKey = status || 'none';
	let dotClass = 'sw-dot sw-dot--neutral';
	if (['queued', 'fetching', 'provider', 'validating'].includes(statusKey)) {
		dotClass = 'sw-dot sw-dot--processing';
	} else if (statusKey === 'stored') {
		dotClass = 'sw-dot sw-dot--done';
	} else if (statusKey === 'failed') {
		dotClass = 'sw-dot sw-dot--failed';
	} else if (statusKey === 'cancelled') {
		dotClass = 'sw-dot sw-dot--neutral';
	}
	const dot = el('span', `mt-1 ${dotClass}`);
	dot.setAttribute('title', statusKey === 'none' ? 'No run yet' : `Status: ${getStatusLabel(statusKey)}`);
	return dot;
}

function getExpectedEntityCount(caseItem) {
	const metadata = caseItem?.metadata || {};
	const candidates = [
		'expected_entities',
		'expected_entity_count',
		'entity_count',
		'entities_count',
		'num_entities',
		'total_entities',
	];
	for (const key of candidates) {
		const value = metadata[key];
		if (value === null || value === undefined || value === '') continue;
		const parsed = Number.parseInt(value, 10);
		if (Number.isFinite(parsed)) {
			return parsed;
		}
	}
	return null;
}

function getSourceFlags(caseItem) {
	const flags = [];
	if (caseItem?.pdf_url) flags.push('PDF URL');
	if (caseItem?.paper_url) flags.push('Paper URL');
	if (caseItem?.doi) flags.push('DOI');
	if (caseItem?.pubmed_id) flags.push('ID');
	return flags;
}

function getSourceHint(caseItem) {
	if (caseItem?.pdf_url) return { label: 'PDF URL', className: 'sw-chip--success' };
	if (caseItem?.paper_url) return { label: 'Paper URL', className: 'sw-chip--success' };
	if (caseItem?.doi) return { label: 'DOI', className: 'sw-chip--success' };
	if (caseItem?.pubmed_id) return { label: 'ID', className: 'sw-chip--success' };
	return { label: 'No source', className: 'sw-chip--warning' };
}

function buildComparison(caseItem, runPayload) {
	if (!caseItem || !runPayload) return null;
	const run = runPayload.run || {};
	if (run.status === 'failed') return null;
	const rawJson = run.raw_json || {};
	const entities = Array.isArray(rawJson.entities) ? rawJson.entities : [];
	const baselineSeq = normalizeSequence(caseItem.sequence);
	let matchIndex = -1;
	if (baselineSeq && entities.length) {
		entities.some((entity, index) => {
			const seq = entity?.peptide?.sequence_one_letter || '';
			if (normalizeSequence(seq) === baselineSeq) {
				matchIndex = index;
				return true;
			}
			return false;
		});
	}
	const baselineLabels = (caseItem.labels || []).map((label) => String(label).toLowerCase());
	const matchedLabels = matchIndex >= 0 ? entities[matchIndex]?.labels || [] : [];
	const matchedLabelSet = new Set(matchedLabels.map((label) => String(label).toLowerCase()));
	const overlapLabels = baselineLabels.filter((label) => matchedLabelSet.has(label));
	const overlapUnique = Array.from(new Set(overlapLabels));
	const baselineExpected = getExpectedEntityCount(caseItem);
	const extractedCount = entities.length;
	const entityDelta = baselineExpected === null ? null : extractedCount - baselineExpected;
	return {
		matchIndex,
		sequenceMatch: matchIndex >= 0,
		labelOverlapCount: overlapUnique.length,
		labelOverlapLabels: overlapUnique,
		baselineExpected,
		extractedCount,
		entityDelta,
	};
}

function buildPaperComparison(paperGroup, runPayload) {
	if (!paperGroup || !runPayload) return null;
	const run = runPayload.run || {};
	if (run.status === 'failed') return null;
	const rawJson = run.raw_json || {};
	const extractedEntities = Array.isArray(rawJson.entities) ? rawJson.entities : [];
	
	// Build set of extracted sequences for matching
	const extractedSeqSet = new Set();
	const extractedSeqToIndex = new Map();
	extractedEntities.forEach((entity, index) => {
		const seq = normalizeSequence(entity?.peptide?.sequence_one_letter || '');
		if (seq) {
			extractedSeqSet.add(seq);
			extractedSeqToIndex.set(seq, index);
		}
	});
	
	// Match each baseline case to extracted entities
	const caseMatches = [];
	let matchedCount = 0;
	
	for (const caseItem of paperGroup.cases) {
		const baselineSeq = normalizeSequence(caseItem.sequence);
		const isMatched = baselineSeq && extractedSeqSet.has(baselineSeq);
		const matchIndex = isMatched ? extractedSeqToIndex.get(baselineSeq) : -1;
		
		if (isMatched) matchedCount++;
		
		// Calculate label overlap for matched entity
		let labelOverlap = [];
		if (matchIndex >= 0) {
			const baselineLabels = (caseItem.labels || []).map(l => String(l).toLowerCase());
			const extractedLabels = (extractedEntities[matchIndex]?.labels || []).map(l => String(l).toLowerCase());
			labelOverlap = baselineLabels.filter(l => extractedLabels.includes(l));
		}
		
		caseMatches.push({
			caseId: caseItem.id,
			sequence: caseItem.sequence,
			labels: caseItem.labels || [],
			isMatched,
			matchIndex,
			labelOverlap,
		});
	}
	
	return {
		totalExpected: paperGroup.cases.length,
		matchedCount,
		extractedCount: extractedEntities.length,
		caseMatches,
	};
}

function renderSelectedPaperStrip(paperGroup, runPayload) {
	const strip = $('#selectedCaseStrip');
	if (!strip) return;
	if (!paperGroup) {
		strip.classList.add('hidden');
		return;
	}
	strip.classList.remove('hidden');
	const sequence = $('#selectedCaseSequence');
	if (sequence) {
		// Show DOI or identifier instead of sequence
		sequence.textContent = paperGroup.doi || paperGroup.pubmed_id || paperGroup.key;
	}
	const dataset = $('#selectedCaseDataset');
	if (dataset) {
		const datasets = [...new Set(paperGroup.cases.map(c => c.dataset).filter(Boolean))];
		dataset.textContent = datasets.join(', ') || 'Unknown dataset';
	}
	const meta = $('#selectedCaseMeta');
	if (meta) {
		meta.innerHTML = '';
		meta.classList.add('flex', 'flex-wrap', 'gap-2');
		
		// Entity count
		meta.appendChild(el('span', 'sw-chip sw-chip--info text-[10px]', `${paperGroup.cases.length} expected entities`));
		
		const doiUrl = normalizeDoiToUrl(paperGroup.doi);
		const pdfUrl = getPreferredPdfUrl(paperGroup, runPayload);
		const firstCase = paperGroup.cases[0];
		const localAvailable = isLocalPdfAvailable(paperGroup, runPayload);
		const localFileAvailable = isLocalPdfFileAvailable(paperGroup);
		const manualStatus = firstCase ? getManualPdfStatus(firstCase, runPayload) : null;
		let resolveBtn = null;
		let openLocalBtn = null;
		
		if (doiUrl) {
			meta.appendChild(createExternalLink(doiUrl, 'break-all max-w-full'));
		}
		if (pdfUrl && isLocalPdfUrl(pdfUrl)) {
			meta.appendChild(el('span', 'sw-chip sw-chip--success text-[10px]', 'Local PDF'));
		} else if (pdfUrl) {
			meta.appendChild(createExternalLink(pdfUrl, 'break-all max-w-full'));
		} else if (firstCase && !localAvailable) {
			resolveBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
			resolveBtn.appendChild(el('span', 'sw-btn__label', 'Find PDF'));
			meta.appendChild(resolveBtn);
		}
		
		if (localFileAvailable) {
			openLocalBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
			openLocalBtn.appendChild(el('span', 'sw-btn__label', 'Open local PDF'));
			meta.appendChild(openLocalBtn);
		}
		
		if (paperGroup.pubmed_id) {
			meta.appendChild(el('span', 'text-[10px] text-slate-500', `PubMed: ${paperGroup.pubmed_id}`));
		}
		
		if (manualStatus?.detail) {
			meta.appendChild(
				el('span', 'text-[10px] text-amber-600 break-words', manualStatus.detail),
			);
		}
		
		if (resolveBtn && firstCase) {
			resolveBtn.addEventListener('click', async () => {
				setButtonLoading(resolveBtn, true, 'Finding...');
				try {
					updateStatus('Searching for open-access source...');
					const result = await api.resolveBaselineSource(firstCase.id);
					if (!result.found) {
						state.manualPdfReasons.set(firstCase.id, MANUAL_PDF_REASON_NO_OA);
						updateStatus('No open-access source found.');
						renderSelectedPaperStrip(paperGroup, runPayload);
						renderCaseList({ skipAnalysis: true });
						return;
					}
					const resolvedUrl = result.pdf_url || result.url;
					paperGroup.pdf_url = resolvedUrl || paperGroup.pdf_url;
					state.manualPdfReasons.delete(firstCase.id);
					if (isLocalPdfUrl(resolvedUrl)) {
						markLocalPdfForGroup(paperGroup, resolvedUrl);
					}
					state.resolvedSource = {
						caseId: firstCase.id,
						url: resolvedUrl,
						label: result.pdf_url ? 'PDF URL' : 'Source URL',
					};
					if (isLocalPdfUrl(resolvedUrl)) {
						state.resolvedSource.label = 'Local PDF';
					}
					updateStatus(`Found ${state.resolvedSource.label}.`);
					renderSelectedPaperStrip(paperGroup, runPayload);
					renderExtractionDetail(runPayload, paperGroup, null);
					renderCaseList({ skipAnalysis: true });
				} catch (err) {
					updateStatus(err.message || 'Failed to resolve source');
				} finally {
					setButtonLoading(resolveBtn, false);
				}
			});
		}

		if (openLocalBtn && firstCase) {
			openLocalBtn.addEventListener('click', () => {
				if (!firstCase.id) {
					updateStatus('No baseline case selected.');
					return;
				}
				updateStatus('Opening local PDF...');
				const url = api.getBaselineLocalPdfUrl(firstCase.id);
				window.open(url, '_blank', 'noopener');
			});
		}
	}
}

// Legacy alias for compatibility
function renderSelectedCaseStrip(caseItem, runPayload) {
	if (!caseItem) {
		renderSelectedPaperStrip(null, null);
		return;
	}
	// Convert single case to paper group format
	const paperGroup = {
		key: getPaperKey(caseItem),
		doi: caseItem.doi,
		pubmed_id: caseItem.pubmed_id,
		paper_url: caseItem.paper_url,
		pdf_url: caseItem.pdf_url,
		dataset: caseItem.dataset,
		cases: [caseItem],
	};
	renderSelectedPaperStrip(paperGroup, runPayload);
}

function renderSummaryBlock(comparison) {
	const wrapper = el('div', 'sw-card sw-card--note p-3 text-[11px] text-slate-600');
	wrapper.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Summary'));
	const grid = el('div', 'mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2');
	const addMetric = (label, value) => {
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(el('div', 'text-slate-700', value));
		grid.appendChild(row);
	};
	if (!comparison) {
		addMetric('Sequence match', 'n/a');
		addMetric('Label overlap', 'n/a');
		addMetric('Entity delta', 'n/a');
		wrapper.appendChild(grid);
		return wrapper;
	}
	addMetric('Sequence match', comparison.sequenceMatch ? 'Yes' : 'No');
	addMetric('Label overlap', `${comparison.labelOverlapCount}`);
	if (comparison.entityDelta === null) {
		addMetric('Entity delta', 'n/a');
	} else {
		const delta = comparison.entityDelta;
		const deltaText = `${delta > 0 ? '+' : ''}${delta}`;
		addMetric('Entity delta', deltaText);
	}
	wrapper.appendChild(grid);
	if (comparison.labelOverlapLabels?.length) {
		wrapper.appendChild(
			el('div', 'mt-2 text-[10px] text-slate-500', `Overlap: ${comparison.labelOverlapLabels.join(', ')}`),
		);
	}
	return wrapper;
}

function renderDatasetOptions() {
	const select = $('#datasetFilter');
	if (!select) return;
	select.innerHTML = '';
	const all = el('option', '', 'All datasets');
	all.value = '';
	select.appendChild(all);
	state.datasets.forEach((dataset) => {
		const option = el('option', '', `${dataset.label || dataset.id} (${dataset.count || 0})`);
		option.value = dataset.id;
		if (dataset.id === state.filterDataset) option.selected = true;
		select.appendChild(option);
	});
}

function renderCounts(paperCount, entityCount) {
	const total = state.cases.length;
	const baselineCount = $('#baselineCount');
	if (baselineCount) baselineCount.textContent = total ? `${total} entities` : '';
	const caseCount = $('#caseCount');
	if (caseCount) {
		if (paperCount !== undefined) {
			caseCount.textContent = `${paperCount} papers (${entityCount} entities)`;
		} else {
			caseCount.textContent = '';
		}
	}
}

function filterCases() {
	const query = state.search.trim().toLowerCase();
	return state.cases.filter((item) => {
		// Filter by batch if selected
		if (state.filterBatchId) {
			const runBatchId = item.latest_run?.batch_id;
			if (runBatchId !== state.filterBatchId) return false;
		}

		const haystack = [
			item.sequence,
			item.doi,
			item.pubmed_id,
			item.paper_url,
			item.id,
			item.dataset,
		]
			.filter(Boolean)
			.join(' ')
			.toLowerCase();
		if (query && !haystack.includes(query)) return false;
		const pdfFilter = state.pdfStatusFilter;
		if (pdfFilter === 'manual') {
			return Boolean(getManualPdfStatus(item));
		}
		if (pdfFilter === 'available') {
			const hasPdf = Boolean(getPreferredPdfUrl(item));
			return hasPdf && !getManualPdfStatus(item);
		}
		return true;
	});
}

function getPaperKey(caseItem) {
	// Use DOI as primary key, fallback to pubmed_id, paper_url, or case id
	const normalizedDoi = normalizeDoiVersion(caseItem.doi);
	return normalizedDoi || caseItem.pubmed_id || caseItem.paper_url || caseItem.id;
}

function groupCasesByPaper(cases) {
	const groups = new Map();
	for (const caseItem of cases) {
		const key = getPaperKey(caseItem);
		if (!groups.has(key)) {
			groups.set(key, {
				key,
				doi: caseItem.doi,
				pubmed_id: caseItem.pubmed_id,
				paper_url: caseItem.paper_url,
				pdf_url: caseItem.pdf_url,
				dataset: caseItem.dataset,
				cases: [],
			});
		}
		const group = groups.get(key);
		group.cases.push(caseItem);
		// Take the first available pdf_url from any case
		if (!group.pdf_url && caseItem.pdf_url) {
			group.pdf_url = caseItem.pdf_url;
		}
	}
	return Array.from(groups.values());
}

function getPaperRunStatus(paperGroup) {
	// Determine aggregate run status for a paper group
	// Priority: processing > failed > stored > none
	let latestRun = null;
	let latestProcessingRun = null;
	let latestFailedRun = null;
	let hasStored = false;
	
	for (const caseItem of paperGroup.cases) {
		const run = caseItem.latest_run;
		if (!run) continue;
		if (!latestRun || (run.run_id && run.run_id > (latestRun.run_id || 0))) {
			latestRun = run;
		}
		if (isProcessingStatus(run.status)) {
			if (!latestProcessingRun || (run.run_id && run.run_id > (latestProcessingRun.run_id || 0))) {
				latestProcessingRun = run;
			}
		} else if (run.status === 'failed') {
			if (!latestFailedRun || (run.run_id && run.run_id > (latestFailedRun.run_id || 0))) {
				latestFailedRun = run;
			}
		} else if (run.status === 'stored') {
			hasStored = true;
		}
	}
	
	if (latestProcessingRun) return { status: latestProcessingRun.status, run: latestProcessingRun };
	if (latestFailedRun) return { status: 'failed', run: latestFailedRun };
	if (hasStored) return { status: 'stored', run: latestRun };
	return { status: 'none', run: null };
}

function getPaperDisplayLabel(paperGroup) {
	// Get a display label for the paper
	if (paperGroup.doi) {
		// Shorten DOI for display
		const doi = paperGroup.doi;
		if (doi.length > 35) {
			return doi.substring(0, 32) + '...';
		}
		return doi;
	}
	if (paperGroup.pubmed_id) return `PubMed: ${paperGroup.pubmed_id}`;
	if (paperGroup.paper_url) {
		const url = paperGroup.paper_url;
		if (url.length > 35) {
			return url.substring(0, 32) + '...';
		}
		return url;
	}
	return paperGroup.cases[0]?.id || 'Unknown';
}

async function mapWithConcurrency(items, limit, worker) {
	const results = new Array(items.length);
	let nextIndex = 0;
	const runners = Array.from({ length: Math.min(limit, items.length) }, async () => {
		while (true) {
			const index = nextIndex++;
			if (index >= items.length) return;
			results[index] = await worker(items[index], index);
		}
	});
	await Promise.all(runners);
	return results;
}

async function fetchLatestRunPayload(caseItem) {
	if (!caseItem?.id) return null;
	const runId = caseItem.latest_run?.run_id || null;
	const cached = state.runPayloadCache.get(caseItem.id);
	if (cached && cached.runId === runId) {
		return cached.payload;
	}
	try {
		const payload = await api.getBaselineLatestRun(caseItem.id);
		state.runPayloadCache.set(caseItem.id, { runId, payload });
		return payload;
	} catch (err) {
		return null;
	}
}

function getComparisonCache(caseItem) {
	if (!caseItem?.id) return null;
	const runId = caseItem.latest_run?.run_id || null;
	const cached = state.comparisonCache.get(caseItem.id);
	if (!cached || cached.runId !== runId) return null;
	return cached.comparison;
}

function setComparisonCache(caseItem, comparison) {
	if (!caseItem?.id) return;
	const runId = caseItem.latest_run?.run_id || null;
	state.comparisonCache.set(caseItem.id, { runId, comparison });
}

function pruneComparisonCache(cases) {
	const activeIds = new Set(cases.map((item) => item.id));
	for (const key of state.comparisonCache.keys()) {
		if (!activeIds.has(key)) {
			state.comparisonCache.delete(key);
		}
	}
}

function pruneManualPdfReasons(cases) {
	const activeIds = new Set(cases.map((item) => item.id));
	for (const key of state.manualPdfReasons.keys()) {
		if (!activeIds.has(key)) {
			state.manualPdfReasons.delete(key);
		}
	}
}

function computeAggregateMetrics(successCases, runPayloads, comparisons = null) {
	let comparisonsCount = 0;
	let sequenceMatchCount = 0;
	const labelOverlapCounts = [];
	const deltaValues = [];
	const overlapLabelCounts = new Map();
	const tagCounts = {
		labels: new Map(),
		morphology: new Map(),
		methods: new Map(),
	};

	successCases.forEach((caseItem, index) => {
		const runPayload = runPayloads[index];
		if (!runPayload?.run) return;
		const comparison = comparisons ? comparisons[index] : buildComparison(caseItem, runPayload);
		if (!comparison) return;
		comparisonsCount += 1;
		if (comparison.sequenceMatch) sequenceMatchCount += 1;
		labelOverlapCounts.push(comparison.labelOverlapCount || 0);
		(comparison.labelOverlapLabels || []).forEach((label) => incrementCount(overlapLabelCounts, label));
		if (comparison.entityDelta !== null) deltaValues.push(comparison.entityDelta);

		const rawJson = runPayload.run.raw_json || runPayload.run.payload || {};
		const entities = Array.isArray(rawJson.entities) ? rawJson.entities : [];
		entities.forEach((entity) => {
			(entity.labels || []).forEach((label) => incrementCount(tagCounts.labels, label));
			(entity.morphology || []).forEach((label) => incrementCount(tagCounts.morphology, label));
			(entity.validation_methods || []).forEach((label) => incrementCount(tagCounts.methods, label));
		});
	});

	return {
		comparisonsCount,
		sequenceMatchCount,
		labelOverlapAvg: mean(labelOverlapCounts),
		labelOverlapMedian: median(labelOverlapCounts),
		overlapLabels: getTopEntries(overlapLabelCounts),
		entityDeltaAvg: mean(deltaValues),
		entityDeltaMedian: median(deltaValues),
		entityDeltaBuckets: bucketizeDeltas(deltaValues),
		topTags: {
			labels: getTopEntries(tagCounts.labels),
			morphology: getTopEntries(tagCounts.morphology),
			methods: getTopEntries(tagCounts.methods),
		},
	};
}

function renderAggregatePanel({ paperCount, entityCount, paperStatusCounts, entityStatusCounts, metrics }) {
	const container = $('#baselineAnalysis');
	if (!container) return;
	container.innerHTML = '';

	if (!paperCount) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'No papers in this filter.'));
		return;
	}

	// Paper-level summary
	const paperSuccessCount = paperStatusCounts.stored || 0;
	const paperFailedCount = paperStatusCounts.failed || 0;
	const paperPendingCount = (paperStatusCounts.queued || 0) + (paperStatusCounts.fetching || 0) + 
		(paperStatusCounts.provider || 0) + (paperStatusCounts.validating || 0);
	const paperNoneCount = paperStatusCounts.none || 0;

	const summary = el('div', 'grid grid-cols-2 md:grid-cols-4 gap-2 text-[11px]');
	const addSummary = (label, value) => {
		const cell = el('div', 'flex flex-col gap-1');
		cell.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		cell.appendChild(el('div', 'text-slate-700', value));
		summary.appendChild(cell);
	};
	addSummary('Papers', `${paperCount} (${entityCount} entities)`);
	addSummary('Successful', `${paperSuccessCount} (${formatPercent(paperSuccessCount, paperCount)})`);
	addSummary('Failed', paperFailedCount);
	addSummary('Pending/none', paperPendingCount + paperNoneCount);
	container.appendChild(summary);

	if (!metrics || metrics.papersAnalyzed === 0) {
		container.appendChild(el('div', 'mt-2 text-xs text-slate-500', 'No successful runs to analyze yet.'));
		return;
	}

	const metricsGrid = el('div', 'mt-3 grid grid-cols-1 sm:grid-cols-3 gap-2 text-[11px]');
	const addMetric = (label, value) => {
		const cell = el('div', 'flex flex-col gap-1');
		cell.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		cell.appendChild(el('div', 'text-slate-700', value));
		metricsGrid.appendChild(cell);
	};
	
	// Entity match rate across all papers
	addMetric('Entity match rate', `${formatPercent(metrics.totalMatched, metrics.totalExpected)} (${metrics.totalMatched}/${metrics.totalExpected})`);
	addMetric('Avg match rate per paper', `${formatNumber(metrics.avgMatchRate * 100, 0)}%`);
	addMetric('Papers with all matched', `${metrics.perfectMatchCount}/${metrics.papersAnalyzed}`);
	container.appendChild(metricsGrid);

	// Entity delta distribution
	const deltas = el('div', 'mt-3');
	deltas.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Extracted vs expected (per paper)'));
	if (metrics.entityDeltaBuckets.every((bucket) => bucket.count === 0)) {
		deltas.appendChild(el('div', 'mt-1 text-xs text-slate-500', 'n/a'));
	} else {
		const list = el('div', 'mt-1 flex flex-wrap gap-1');
		metrics.entityDeltaBuckets.forEach((bucket) => {
			list.appendChild(el('span', 'sw-chip text-[10px] text-slate-500', `${bucket.label}: ${bucket.count}`));
		});
		deltas.appendChild(list);
	}
	container.appendChild(deltas);

	// Top tags from extracted entities
	const tags = el('div', 'mt-3 grid grid-cols-1 md:grid-cols-3 gap-2 text-[11px]');
	const addTags = (label, items) => {
		const col = el('div', 'flex flex-col gap-1');
		col.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		if (!items.length) {
			col.appendChild(el('div', 'text-slate-500', 'n/a'));
		} else {
			const list = el('div', 'flex flex-wrap gap-1');
			items.forEach((item) => {
				list.appendChild(el('span', 'sw-chip text-[10px] text-slate-500', `${item.label} (${item.count})`));
			});
			col.appendChild(list);
		}
		tags.appendChild(col);
	};
	addTags('Top labels', metrics.topTags.labels);
	addTags('Top morphology', metrics.topTags.morphology);
	addTags('Top methods', metrics.topTags.methods);
	container.appendChild(tags);
}

async function updateAggregateAnalysis(cases = filterCases()) {
	const container = $('#baselineAnalysis');
	if (!container) return;
	
	const paperGroups = groupCasesByPaper(cases);
	const paperCount = paperGroups.length;
	const entityCount = cases.length;
	
	// Compute paper-level status counts
	const paperStatusCounts = {};
	const entityStatusCounts = {};
	
	paperGroups.forEach(paperGroup => {
		const runStatus = getPaperRunStatus(paperGroup);
		paperStatusCounts[runStatus.status] = (paperStatusCounts[runStatus.status] || 0) + 1;
	});
	
	cases.forEach(item => {
		const status = item.latest_run?.status || 'none';
		entityStatusCounts[status] = (entityStatusCounts[status] || 0) + 1;
	});
	
	const successPapers = paperGroups.filter(g => getPaperRunStatus(g).status === 'stored');
	
	pruneComparisonCache(cases);
	cases.forEach((item) => {
		if (item.latest_run?.status !== 'stored') {
			state.comparisonCache.delete(item.id);
		}
	});

	const hint = $('#analysisHint');
	if (hint) {
		const successCount = paperStatusCounts.stored || 0;
		hint.textContent = paperCount ? `${successCount} successful of ${paperCount} papers` : 'No papers';
	}

	container.innerHTML = '';
	if (!paperCount) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'No papers in this filter.'));
		return;
	}
	container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'Computing analysis...'));

	if (!successPapers.length) {
		renderAggregatePanel({ paperCount, entityCount, paperStatusCounts, entityStatusCounts, metrics: null });
		return;
	}

	const token = ++analysisToken;
	
	// Fetch run payloads for successful papers (use first case of each paper)
	const runPayloads = await mapWithConcurrency(successPapers, 6, async (paperGroup) => {
		const firstCase = paperGroup.cases[0];
		return fetchLatestRunPayload(firstCase);
	});
	
	if (token !== analysisToken) return;
	
	// Build paper comparisons and compute metrics
	const paperComparisons = successPapers.map((paperGroup, index) => {
		const runPayload = runPayloads[index];
		if (!runPayload?.run) return null;
		const comparison = buildPaperComparison(paperGroup, runPayload);
		if (comparison) {
			state.paperComparisonCache.set(paperGroup.key, comparison);
		}
		return comparison;
	});
	
	const metrics = computePaperAggregateMetrics(successPapers, runPayloads, paperComparisons);
	renderAggregatePanel({ paperCount, entityCount, paperStatusCounts, entityStatusCounts, metrics });
	renderCaseList({ skipAnalysis: true });
}

function computePaperAggregateMetrics(successPapers, runPayloads, paperComparisons) {
	let papersAnalyzed = 0;
	let totalExpected = 0;
	let totalMatched = 0;
	let perfectMatchCount = 0;
	const matchRates = [];
	const deltaValues = [];
	const tagCounts = {
		labels: new Map(),
		morphology: new Map(),
		methods: new Map(),
	};
	
	successPapers.forEach((paperGroup, index) => {
		const runPayload = runPayloads[index];
		const comparison = paperComparisons[index];
		if (!runPayload?.run || !comparison) return;
		
		papersAnalyzed++;
		totalExpected += comparison.totalExpected;
		totalMatched += comparison.matchedCount;
		
		const matchRate = comparison.totalExpected > 0 
			? comparison.matchedCount / comparison.totalExpected 
			: 0;
		matchRates.push(matchRate);
		
		if (comparison.matchedCount === comparison.totalExpected) {
			perfectMatchCount++;
		}
		
		const delta = comparison.extractedCount - comparison.totalExpected;
		deltaValues.push(delta);
		
		// Collect tags from extracted entities
		const rawJson = runPayload.run.raw_json || runPayload.run.payload || {};
		const entities = Array.isArray(rawJson.entities) ? rawJson.entities : [];
		entities.forEach((entity) => {
			(entity.labels || []).forEach((label) => incrementCount(tagCounts.labels, label));
			(entity.morphology || []).forEach((label) => incrementCount(tagCounts.morphology, label));
			(entity.validation_methods || []).forEach((label) => incrementCount(tagCounts.methods, label));
		});
	});
	
	return {
		papersAnalyzed,
		totalExpected,
		totalMatched,
		perfectMatchCount,
		avgMatchRate: mean(matchRates) || 0,
		entityDeltaBuckets: bucketizeDeltas(deltaValues),
		topTags: {
			labels: getTopEntries(tagCounts.labels),
			morphology: getTopEntries(tagCounts.morphology),
			methods: getTopEntries(tagCounts.methods),
		},
	};
}

function renderCaseList({ skipAnalysis = false } = {}) {
	const container = $('#baselineList');
	container.innerHTML = '';
	const cases = filterCases();
	if (!cases.length) {
		container.appendChild(el('div', 'sw-empty py-6 text-sm text-slate-500 text-center', 'No papers found.'));
		return;
	}

	const paperGroups = groupCasesByPaper(cases);

	paperGroups.forEach((paperGroup) => {
		const isSelected = state.selectedPaperKey === paperGroup.key;
		const row = el('div', `py-3 px-3 flex items-start gap-3 sw-row ${isSelected ? 'sw-row--selected' : ''}`);
		row.setAttribute('role', 'button');
		row.setAttribute('tabindex', '0');

		const content = el('div', 'flex-1 min-w-0');
		const titleRow = el('div', 'flex items-start gap-2');
		
		const runStatus = getPaperRunStatus(paperGroup);
		titleRow.appendChild(buildRunIndicator(runStatus.status));
		titleRow.appendChild(el('div', 'text-xs font-medium text-slate-900 flex-1 break-words', getPaperDisplayLabel(paperGroup)));

		content.appendChild(titleRow);

		const metaRow = el('div', 'mt-1 flex flex-wrap items-center gap-2');
		
		// Entity count badge
		const entityCount = paperGroup.cases.length;
		metaRow.appendChild(el('span', 'sw-chip sw-chip--info text-[9px]', `${entityCount} ${entityCount === 1 ? 'entity' : 'entities'}`));
		
		// Dataset chips (unique datasets in this paper)
		const datasets = [...new Set(paperGroup.cases.map(c => c.dataset).filter(Boolean))];
		datasets.forEach(dataset => {
			metaRow.appendChild(el('span', 'sw-chip text-[9px] text-slate-500', dataset));
		});
		
		// Source hint
		const sourceHint = getSourceHint(paperGroup);
		if (sourceHint) {
			metaRow.appendChild(el('span', `sw-chip ${sourceHint.className} text-[9px]`, sourceHint.label));
		}

		// Local PDF badge
		const hasLocalPdf = isLocalPdfAvailable(paperGroup);
		if (hasLocalPdf) {
			metaRow.appendChild(el('span', 'sw-chip sw-chip--success text-[9px]', 'Local PDF'));
		}
		
		// Check if any case needs manual PDF
		const needsManualPdf = paperGroup.cases.some(c => getManualPdfStatus(c));
		if (needsManualPdf) {
			metaRow.appendChild(el('span', 'sw-chip sw-chip--warning text-[9px]', MANUAL_PDF_TAG));
		}
		
		if (metaRow.childNodes.length) {
			content.appendChild(metaRow);
		}

		// Show comparison stats if run is stored
		if (runStatus.status === 'stored') {
			const tagRow = el('div', 'mt-1 flex flex-wrap items-center gap-2');
			const paperComparison = state.paperComparisonCache.get(paperGroup.key);
			if (!paperComparison) {
				tagRow.appendChild(el('span', 'sw-chip sw-chip--info text-[9px]', 'Analyzing...'));
			} else {
				const matchedCount = paperComparison.matchedCount || 0;
				const totalExpected = paperComparison.totalExpected || paperGroup.cases.length;
				const matchLabel = `${matchedCount}/${totalExpected} matched`;
				const matchClass = matchedCount === totalExpected ? 'sw-chip--success' : 
					matchedCount > 0 ? 'sw-chip--info' : 'sw-chip--warning';
				tagRow.appendChild(el('span', `sw-chip ${matchClass} text-[9px]`, matchLabel));
				
				if (paperComparison.extractedCount !== undefined) {
					const extracted = paperComparison.extractedCount;
					const deltaText = extracted > totalExpected ? `+${extracted - totalExpected} extra` : 
						extracted < totalExpected ? `${totalExpected - extracted} missing` : '';
					if (deltaText) {
						tagRow.appendChild(el('span', 'sw-chip text-[9px]', deltaText));
					}
				}
			}
			content.appendChild(tagRow);
		}

		// Show failure reason if failed
		if (runStatus.status === 'failed' && runStatus.run?.failure_reason) {
			const friendly = formatFailureReason(runStatus.run.failure_reason);
			const message = friendly?.title || runStatus.run.failure_reason;
			content.appendChild(el('div', 'mt-1 text-[10px] text-red-500 break-words', message));
		}

		row.appendChild(content);
		row.addEventListener('click', () => selectPaper(paperGroup.key));
		row.addEventListener('keydown', (event) => {
			if (event.key === 'Enter' || event.key === ' ') {
				event.preventDefault();
				selectPaper(paperGroup.key);
			}
		});
		container.appendChild(row);
	});

	renderCounts(paperGroups.length, cases.length);
	if (!skipAnalysis) {
		updateAggregateAnalysis(cases);
	}
}

function renderBaselineDetail(paperGroupOrCase, comparison, runPayload = null) {
	const container = $('#baselineDetail');
	container.innerHTML = '';
	
	if (!paperGroupOrCase) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'Select a paper from the list to compare against the latest run.'));
		return;
	}

	// Handle both paper group and single case formats
	const isPaperGroup = Array.isArray(paperGroupOrCase.cases);
	const paperGroup = isPaperGroup ? paperGroupOrCase : {
		key: getPaperKey(paperGroupOrCase),
		doi: paperGroupOrCase.doi,
		pubmed_id: paperGroupOrCase.pubmed_id,
		paper_url: paperGroupOrCase.paper_url,
		pdf_url: paperGroupOrCase.pdf_url,
		dataset: paperGroupOrCase.dataset,
		cases: [paperGroupOrCase],
	};

	// Paper header
	const headerRow = el('div', 'flex flex-wrap items-center gap-2');
	const headerLabel = paperGroup.doi || paperGroup.pubmed_id || paperGroup.key;
	headerRow.appendChild(el('div', 'text-sm font-medium text-slate-900 break-words', headerLabel));
	
	// Match summary
	if (comparison && comparison.matchedCount !== undefined) {
		const matchLabel = `${comparison.matchedCount}/${comparison.totalExpected} matched`;
		const matchClass = comparison.matchedCount === comparison.totalExpected ? 'sw-chip--success' : 
			comparison.matchedCount > 0 ? 'sw-chip--info' : 'sw-chip--warning';
		headerRow.appendChild(el('span', `sw-chip ${matchClass} text-[10px]`, matchLabel));
	} else if (comparison) {
		// Legacy single-case comparison
		const matchLabel = comparison.sequenceMatch ? 'Match' : 'No match';
		const matchClass = comparison.sequenceMatch ? 'sw-chip--success' : 'sw-chip--warning';
		headerRow.appendChild(el('span', `sw-chip ${matchClass} text-[10px]`, matchLabel));
	} else {
		headerRow.appendChild(el('span', 'sw-chip sw-chip--info text-[10px]', 'Not compared'));
	}
	container.appendChild(headerRow);

	// Paper metadata
	const meta = el('div', 'grid grid-cols-1 gap-2 text-[11px] mt-2');
	const addRow = (label, value, allowEmpty = false) => {
		if (!allowEmpty && (value === null || value === undefined || value === '')) return;
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(el('div', 'text-slate-700 break-words', value || 'Not provided'));
		meta.appendChild(row);
	};
	const addLinkRow = (label, url) => {
		if (!url) return;
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(createExternalLink(url, 'break-all max-w-full'));
		meta.appendChild(row);
	};

	addRow('DOI', paperGroup.doi);
	addRow('PubMed/Patent', paperGroup.pubmed_id);
	const preferredPdfUrl = getPreferredPdfUrl(paperGroup, runPayload);
	if (preferredPdfUrl) {
		if (isLocalPdfUrl(preferredPdfUrl)) {
			addRow('PDF source', 'Local PDF', true);
		} else {
			addLinkRow('PDF link', preferredPdfUrl);
		}
	}
	if (paperGroup.paper_url && paperGroup.paper_url !== preferredPdfUrl) {
		addLinkRow('Paper link', paperGroup.paper_url);
	}
	const sourceFlags = getSourceFlags(paperGroup);
	addRow('Source fields', sourceFlags.length ? sourceFlags.join(', ') : 'None', true);
	container.appendChild(meta);

	// Expected entities section
	const entitiesSection = el('div', 'mt-4');
	entitiesSection.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400 mb-2', `Expected entities (${paperGroup.cases.length})`));
	
	const entitiesList = el('div', 'space-y-2');
	paperGroup.cases.forEach((caseItem, index) => {
		// Check if this case was matched
		let isMatched = false;
		let labelOverlap = [];
		if (comparison && comparison.caseMatches) {
			const match = comparison.caseMatches.find(m => m.caseId === caseItem.id);
			if (match) {
				isMatched = match.isMatched;
				labelOverlap = match.labelOverlap || [];
			}
		}
		
		const cardClass = isMatched ? 'sw-card sw-card--success p-2' : 'sw-card p-2';
		const card = el('div', cardClass);
		
		// Entity header with sequence
		const entityHeader = el('div', 'flex flex-wrap items-center gap-2');
		entityHeader.appendChild(el('span', 'text-[10px] text-slate-400', `#${index + 1}`));
		entityHeader.appendChild(el('div', 'text-xs font-medium text-slate-900 break-words', caseItem.sequence || '(No sequence)'));
		if (isMatched) {
			entityHeader.appendChild(el('span', 'sw-chip sw-chip--success text-[9px]', 'Matched'));
		}
		card.appendChild(entityHeader);
		
		// Labels
		if (caseItem.labels && caseItem.labels.length) {
			const labelsRow = el('div', 'mt-1 flex flex-wrap gap-1');
			caseItem.labels.forEach(label => {
				const isOverlap = labelOverlap.includes(label.toLowerCase());
				const labelClass = isOverlap ? 'sw-chip sw-chip--success text-[9px]' : 'sw-chip text-[9px]';
				labelsRow.appendChild(el('span', labelClass, label));
			});
			card.appendChild(labelsRow);
		}
		
		// Additional metadata (collapsed by default for brevity)
		const metaItems = [];
		if (caseItem.n_terminal) metaItems.push(`N: ${caseItem.n_terminal}`);
		if (caseItem.c_terminal) metaItems.push(`C: ${caseItem.c_terminal}`);
		if (caseItem.dataset) metaItems.push(caseItem.dataset);
		if (caseItem.metadata?.validation_methods_raw) {
			metaItems.push(`Validation: ${caseItem.metadata.validation_methods_raw}`);
		}
		
		if (metaItems.length) {
			card.appendChild(el('div', 'mt-1 text-[10px] text-slate-500 break-words', metaItems.join(' · ')));
		}
		
		entitiesList.appendChild(card);
	});
	
	entitiesSection.appendChild(entitiesList);
	container.appendChild(entitiesSection);
}

function renderEntityDetails(entity) {
	const rows = [];
	const addRow = (label, value) => {
		if (value === undefined || value === null || value === '') return;
		if (Array.isArray(value) && value.length === 0) return;
		rows.push({ label, value });
	};

	if (entity.type === 'peptide' && entity.peptide) {
		addRow('Sequence (1-letter)', entity.peptide.sequence_one_letter);
		addRow('Sequence (3-letter)', entity.peptide.sequence_three_letter);
		addRow('N-terminal mod', entity.peptide.n_terminal_mod);
		addRow('C-terminal mod', entity.peptide.c_terminal_mod);
		if (entity.peptide.is_hydrogel !== undefined && entity.peptide.is_hydrogel !== null) {
			addRow('Hydrogel', entity.peptide.is_hydrogel ? 'Yes' : 'No');
		}
	}

	if (entity.type === 'molecule' && entity.molecule) {
		addRow('Chemical formula', entity.molecule.chemical_formula);
		addRow('SMILES', entity.molecule.smiles);
		addRow('InChI', entity.molecule.inchi);
	}

	addRow('Labels', entity.labels);
	addRow('Morphology', entity.morphology);
	addRow('Validation methods', entity.validation_methods);
	addRow('Reported characteristics', entity.reported_characteristics);
	addRow('Process protocol', entity.process_protocol);

	if (entity.conditions) {
		const conditions = [];
		if (entity.conditions.ph !== null && entity.conditions.ph !== undefined) {
			conditions.push(`pH ${entity.conditions.ph}`);
		}
		if (entity.conditions.concentration !== null && entity.conditions.concentration !== undefined) {
			const unit = entity.conditions.concentration_units ? ` ${entity.conditions.concentration_units}` : '';
			conditions.push(`Concentration ${entity.conditions.concentration}${unit}`);
		}
		if (entity.conditions.temperature_c !== null && entity.conditions.temperature_c !== undefined) {
			conditions.push(`Temperature ${entity.conditions.temperature_c} °C`);
		}
		if (conditions.length) addRow('Conditions', conditions);
	}

	if (entity.thresholds) {
		const thresholds = [];
		if (entity.thresholds.cac !== null && entity.thresholds.cac !== undefined) thresholds.push(`CAC ${entity.thresholds.cac}`);
		if (entity.thresholds.cgc !== null && entity.thresholds.cgc !== undefined) thresholds.push(`CGC ${entity.thresholds.cgc}`);
		if (entity.thresholds.mgc !== null && entity.thresholds.mgc !== undefined) thresholds.push(`MGC ${entity.thresholds.mgc}`);
		if (thresholds.length) addRow('Thresholds', thresholds);
	}

	if (!rows.length) {
		return el('div', 'mt-2 text-xs text-slate-400', 'No structured fields reported.');
	}

	const wrapper = el('div', 'mt-3 grid grid-cols-1 md:grid-cols-2 gap-2 text-xs');
	rows.forEach(({ label, value }) => {
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		const text = Array.isArray(value) ? value.join(', ') : String(value);
		row.appendChild(el('div', 'text-slate-700 break-words', text));
		wrapper.appendChild(row);
	});
	return wrapper;
}

function renderEntities(rawJson, matchIndex) {
	const container = el('div', 'space-y-3');
	if (!rawJson?.entities?.length) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500 p-3', 'No entities found.'));
		return container;
	}
	rawJson.entities.forEach((entity, index) => {
		const isMatch = index === matchIndex;
		const card = el('div', `sw-card p-3 ${isMatch ? 'sw-card--success' : ''}`);
		card.appendChild(el('div', 'sw-kicker text-[10px] text-slate-500', `Entity ${index + 1}`));
		card.appendChild(el('div', 'text-sm font-medium text-slate-900 mt-1', entity.type || 'entity'));
		if (isMatch) {
			card.appendChild(el('div', 'text-[10px] text-emerald-600 mt-1', 'Matched sequence'));
		}
		if (entity.type === 'peptide' && entity.peptide) {
			const peptide = entity.peptide;
			const seq = peptide.sequence_one_letter || peptide.sequence_three_letter;
			if (seq) card.appendChild(el('div', 'text-sm text-slate-900 mt-1', seq));
		}
		if (entity.type === 'molecule' && entity.molecule) {
			const molecule = entity.molecule;
			const id = molecule.chemical_formula || molecule.smiles || molecule.inchi;
			if (id) card.appendChild(el('div', 'text-sm text-slate-900 mt-1', id));
		}
		const details = renderEntityDetails(entity);
		if (details) card.appendChild(details);
		container.appendChild(card);
	});
	return container;
}

function renderExtractionDetail(runPayload, paperGroupOrCase, comparison) {
	const container = $('#extractionDetail');
	container.innerHTML = '';
	
	if (!paperGroupOrCase) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'Select a paper from the list to compare against the latest run.'));
		return;
	}
	
	// Handle both paper group and single case formats
	const isPaperGroup = Array.isArray(paperGroupOrCase.cases);
	const paperGroup = isPaperGroup ? paperGroupOrCase : {
		key: getPaperKey(paperGroupOrCase),
		doi: paperGroupOrCase.doi,
		pubmed_id: paperGroupOrCase.pubmed_id,
		paper_url: paperGroupOrCase.paper_url,
		pdf_url: paperGroupOrCase.pdf_url,
		dataset: paperGroupOrCase.dataset,
		cases: [paperGroupOrCase],
	};
	const firstCase = paperGroup.cases[0];
	const localAvailable = isLocalPdfAvailable(paperGroup, runPayload);

	const localAction = renderLocalPdfAction(paperGroup);
	
	if (!runPayload) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500', 'No extraction run yet.'));
		if (localAction) {
			container.appendChild(localAction);
		}
		if (firstCase) {
			if (!localAvailable) {
				container.appendChild(renderBaselineFixPanel(firstCase, null, localAvailable));
			}
		}
		return;
	}

	const run = runPayload.run || {};
	const paper = runPayload.paper || {};
	const header = el('div', 'space-y-1 text-xs text-slate-500');
	header.appendChild(el('div', '', `Run status: ${getStatusLabel(run.status || 'none')}`));
	if (run.created_at) {
		header.appendChild(el('div', '', new Date(run.created_at).toLocaleString()));
	}
	if (run.model_provider || run.model_name) {
		header.appendChild(el('div', '', `${fmt(run.model_provider)} ${fmt(run.model_name)}`.trim()));
	}
	if (paper?.doi) {
		header.appendChild(el('div', '', `DOI: ${paper.doi}`));
	}
	const headerPdfUrl = getPreferredPdfUrl(paperGroup, runPayload);
	if (headerPdfUrl) {
		if (isLocalPdfUrl(headerPdfUrl)) {
			const localRow = el('div', 'flex items-center gap-2');
			localRow.appendChild(el('span', '', 'PDF source: '));
			localRow.appendChild(el('span', 'sw-chip sw-chip--success text-[9px]', 'Local PDF'));
			header.appendChild(localRow);
		} else {
			const linkRow = el('div', 'break-all max-w-full');
			linkRow.appendChild(el('span', '', 'PDF link: '));
			linkRow.appendChild(createExternalLink(headerPdfUrl));
			header.appendChild(linkRow);
		}
	}
	container.appendChild(header);

	// PDF view buttons row
	if (firstCase) {
		const pdfButtonsRow = el('div', 'mt-2 flex flex-wrap gap-2');
		let hasButtons = false;

		// Main PDF button - check if local PDF is available
		if (isLocalPdfAvailable(paperGroup, runPayload)) {
			const mainPdfBtn = el('button', 'sw-btn sw-btn--sm sw-btn--secondary');
			mainPdfBtn.appendChild(el('span', 'sw-btn__label', '📄 View Main PDF'));
			mainPdfBtn.addEventListener('click', () => {
				window.open(api.getBaselineLocalPdfUrl(firstCase.id), '_blank');
			});
			pdfButtonsRow.appendChild(mainPdfBtn);
			hasButtons = true;
		}

		// SI PDF button(s) - load asynchronously
		api.getBaselineLocalPdfSiInfo(firstCase.id).then((siInfo) => {
			if (siInfo?.found && siInfo.count > 0) {
				if (siInfo.count === 1) {
					// Single SI PDF
					const siPdfBtn = el('button', 'sw-btn sw-btn--sm sw-btn--secondary');
					siPdfBtn.appendChild(el('span', 'sw-btn__label', '📎 View SI PDF'));
					siPdfBtn.addEventListener('click', () => {
						window.open(api.getBaselineLocalPdfSiUrl(firstCase.id, 0), '_blank');
					});
					pdfButtonsRow.appendChild(siPdfBtn);
				} else {
					// Multiple SI PDFs - add buttons for each
					for (let i = 0; i < siInfo.count; i++) {
						const siPdfBtn = el('button', 'sw-btn sw-btn--sm sw-btn--secondary');
						const filename = siInfo.filenames[i] || `SI ${i + 1}`;
						const shortName = filename.length > 20 ? filename.substring(0, 17) + '...' : filename;
						siPdfBtn.appendChild(el('span', 'sw-btn__label', `📎 ${shortName}`));
						siPdfBtn.title = filename;
						siPdfBtn.addEventListener('click', () => {
							window.open(api.getBaselineLocalPdfSiUrl(firstCase.id, i), '_blank');
						});
						pdfButtonsRow.appendChild(siPdfBtn);
					}
				}
				// Ensure row is visible if we added SI buttons but no main button was added initially
				if (!hasButtons && pdfButtonsRow.parentElement === null) {
					container.insertBefore(pdfButtonsRow, container.children[1] || null);
				}
			}
		}).catch(() => {
			// Silently ignore errors fetching SI info
		});

		if (hasButtons) {
			container.appendChild(pdfButtonsRow);
		}
	}

	if (localAction) {
		container.appendChild(localAction);
	}

	const paperId = paper?.id || run.paper_id;
	if (paperId && run.status === 'stored' && firstCase) {
		const actionsRow = el('div', 'mt-2 flex flex-wrap items-center gap-2');
		const forceBtn = el('button', 'sw-btn sw-btn--sm sw-btn--primary');
		forceBtn.appendChild(el('span', 'sw-btn__label', 'Force Re-extract'));
		forceBtn.addEventListener('click', async () => {
			setButtonLoading(forceBtn, true, 'Re-extracting...');
			try {
				updateStatus('Forcing re-extract...');
				await api.forceReextract(paperId, state.provider);
				await loadPaperDetails(paperGroup.key);
				await loadCases();
				updateStatus('Re-extract queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to force re-extract');
			} finally {
				setButtonLoading(forceBtn, false);
			}
		});
		actionsRow.appendChild(forceBtn);
		const uploadBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
		uploadBtn.appendChild(el('span', 'sw-btn__label', 'Upload PDF'));
		const fileInput = el('input', 'hidden');
		fileInput.type = 'file';
		fileInput.accept = '.pdf';
		uploadBtn.addEventListener('click', () => fileInput.click());
		fileInput.addEventListener('change', async () => {
			const file = fileInput.files && fileInput.files[0];
			if (!file) return;
			setButtonLoading(uploadBtn, true, 'Uploading...');
			try {
				updateStatus('Uploading PDF and queuing extraction...');
				await api.uploadBaselinePdf(firstCase.id, file, state.provider);
				await loadPaperDetails(paperGroup.key);
				await loadCases();
				updateStatus('PDF uploaded. Extraction queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to upload PDF');
			} finally {
				setButtonLoading(uploadBtn, false);
				fileInput.value = '';
			}
		});
		actionsRow.appendChild(uploadBtn);
		actionsRow.appendChild(fileInput);
		container.appendChild(actionsRow);
	}

	if (isProcessingStatus(run.status)) {
		const processing = el('div', 'sw-card sw-card--note p-3 text-xs text-slate-600 flex items-center gap-2');
		processing.appendChild(el('span', 'sw-spinner h-3 w-3 rounded-full'));
		processing.appendChild(el('div', '', `Processing: ${getStatusLabel(run.status)}`));
		container.appendChild(processing);
	}

	if (run.status === 'failed') {
		const errorBox = el('div', 'sw-card sw-card--error p-3 text-xs text-slate-600');
		const friendly = formatFailureReason(run.failure_reason);
		if (friendly) {
			errorBox.appendChild(el('div', 'text-slate-700 font-medium', friendly.title));
			if (friendly.detail) {
				errorBox.appendChild(el('div', 'mt-1 text-[11px] text-slate-500', friendly.detail));
			}
		} else {
			errorBox.textContent = run.failure_reason || 'Unknown failure';
		}
		container.appendChild(errorBox);
		if (firstCase) {
			if (!localAvailable) {
				container.appendChild(renderBaselineFixPanel(firstCase, runPayload, localAvailable));
			}
		}
		return;
	}

	// Summary block for paper-level comparison
	const paperComparison = comparison || buildPaperComparison(paperGroup, runPayload);
	container.appendChild(renderPaperSummaryBlock(paperComparison, paperGroup));

	// Extracted entities with match highlighting
	const rawJson = run.raw_json || {};
	container.appendChild(renderExtractedEntities(rawJson, paperComparison));
}

function renderPaperSummaryBlock(comparison, paperGroup) {
	const wrapper = el('div', 'sw-card sw-card--note p-3 text-[11px] text-slate-600');
	wrapper.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Summary'));
	const grid = el('div', 'mt-2 grid grid-cols-1 sm:grid-cols-3 gap-2');
	const addMetric = (label, value) => {
		const row = el('div', 'flex flex-col gap-1');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
		row.appendChild(el('div', 'text-slate-700', value));
		grid.appendChild(row);
	};
	
	if (!comparison) {
		addMetric('Expected', paperGroup ? `${paperGroup.cases.length} entities` : 'n/a');
		addMetric('Extracted', 'n/a');
		addMetric('Matched', 'n/a');
		wrapper.appendChild(grid);
		return wrapper;
	}
	
	addMetric('Expected', `${comparison.totalExpected} entities`);
	addMetric('Extracted', `${comparison.extractedCount} entities`);
	
	const matchRate = comparison.totalExpected > 0 
		? `${comparison.matchedCount}/${comparison.totalExpected} (${Math.round(comparison.matchedCount / comparison.totalExpected * 100)}%)`
		: 'n/a';
	addMetric('Matched', matchRate);
	
	wrapper.appendChild(grid);
	
	// Delta info
	if (comparison.extractedCount !== comparison.totalExpected) {
		const delta = comparison.extractedCount - comparison.totalExpected;
		const deltaText = delta > 0 
			? `${delta} extra entities extracted` 
			: `${Math.abs(delta)} entities missing`;
		wrapper.appendChild(el('div', 'mt-2 text-[10px] text-slate-500', deltaText));
	}
	
	return wrapper;
}

function renderExtractedEntities(rawJson, paperComparison) {
	const container = el('div', 'mt-4');
	container.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400 mb-2', 
		`Extracted entities (${rawJson?.entities?.length || 0})`));
	
	if (!rawJson?.entities?.length) {
		container.appendChild(el('div', 'sw-empty text-xs text-slate-500 p-3', 'No entities found.'));
		return container;
	}
	
	// Build set of matched indices
	const matchedIndices = new Set();
	if (paperComparison?.caseMatches) {
		paperComparison.caseMatches.forEach(match => {
			if (match.isMatched && match.matchIndex >= 0) {
				matchedIndices.add(match.matchIndex);
			}
		});
	}
	
	const entitiesList = el('div', 'space-y-2');
	rawJson.entities.forEach((entity, index) => {
		const isMatched = matchedIndices.has(index);
		const card = el('div', `sw-card p-2 ${isMatched ? 'sw-card--success' : ''}`);
		
		// Entity header
		const entityHeader = el('div', 'flex flex-wrap items-center gap-2');
		entityHeader.appendChild(el('span', 'sw-kicker text-[10px] text-slate-500', `#${index + 1}`));
		entityHeader.appendChild(el('div', 'text-xs font-medium text-slate-900', entity.type || 'entity'));
		if (isMatched) {
			entityHeader.appendChild(el('span', 'sw-chip sw-chip--success text-[9px]', 'Matched baseline'));
		}
		card.appendChild(entityHeader);
		
		// Sequence or identifier
		if (entity.type === 'peptide' && entity.peptide) {
			const peptide = entity.peptide;
			const seq = peptide.sequence_one_letter || peptide.sequence_three_letter;
			if (seq) {
				card.appendChild(el('div', 'text-xs text-slate-900 mt-1 font-mono break-words', seq));
			}
		}
		if (entity.type === 'molecule' && entity.molecule) {
			const molecule = entity.molecule;
			const id = molecule.chemical_formula || molecule.smiles || molecule.inchi;
			if (id) {
				card.appendChild(el('div', 'text-xs text-slate-900 mt-1 font-mono break-words', id));
			}
		}
		
		// Labels
		if (entity.labels && entity.labels.length) {
			const labelsRow = el('div', 'mt-1 flex flex-wrap gap-1');
			entity.labels.forEach(label => {
				labelsRow.appendChild(el('span', 'sw-chip text-[9px]', label));
			});
			card.appendChild(labelsRow);
		}
		
		// Compact details
		const details = renderEntityDetails(entity);
		if (details) card.appendChild(details);
		
		entitiesList.appendChild(card);
	});
	
	container.appendChild(entitiesList);
	return container;
}

function renderLocalPdfAction(paperGroup) {
	if (!paperGroup?.cases?.length) return null;
	const firstCase = paperGroup.cases[0];
	const wrapper = el('div', 'mt-2');
	const button = el('button', 'sw-btn sw-btn--primary sw-btn--sm');
	button.appendChild(el('span', 'sw-btn__label', 'Run with local PDF'));
	button.addEventListener('click', async () => {
		setButtonLoading(button, true, 'Running...');
		try {
			updateStatus('Resolving local PDF...');
			const result = await api.resolveBaselineSource(firstCase.id, { localOnly: true });
			if (!result?.found) {
				updateStatus('No local PDF found for this paper.');
				return;
			}
			const sourceUrl = result.pdf_url || result.url;
			if (!isLocalPdfUrl(sourceUrl)) {
				updateStatus('No local PDF found for this paper.');
				return;
			}
			state.resolvedSource = { caseId: firstCase.id, url: sourceUrl, label: 'Local PDF' };
			state.stagedFile = null;
			markLocalPdfForGroup(paperGroup, sourceUrl);
			updateStatus('Starting extraction with local PDF...');
			await api.retryBaselineCase(firstCase.id, { provider: state.provider, source_url: sourceUrl });
			await loadCaseDetails(firstCase.id);
			await loadCases();
			updateStatus('Local PDF extraction queued.');
		} catch (err) {
			updateStatus(err.message || 'Failed to start local PDF extraction');
		} finally {
			setButtonLoading(button, false);
		}
	});
	wrapper.appendChild(button);
	return wrapper;
}

function renderBaselineFixPanel(caseItem, runPayload, localAvailable = false) {
	const panel = el('div', 'sw-card sw-card--note p-3 text-[11px] text-slate-600');
	panel.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Fix this failure'));

	const resolvedSource =
		state.resolvedSource && state.resolvedSource.caseId === caseItem.id ? state.resolvedSource : null;
	const hasHeaderPdf = Boolean(getPreferredPdfUrl(caseItem, runPayload));
	const stagedFile = state.stagedFile && state.stagedFile.caseId === caseItem.id ? state.stagedFile : null;

	const actions = el('div', 'mt-2 flex flex-wrap items-center gap-2');
	const retryBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
	retryBtn.appendChild(el('span', 'sw-btn__label', 'Retry same source'));
	const resolveBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
	resolveBtn.appendChild(el('span', 'sw-btn__label', 'Find open-access PDF'));

	const fileInput = el('input', 'hidden');
	fileInput.type = 'file';
	fileInput.accept = '.pdf';
	const uploadBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost');
	uploadBtn.appendChild(el('span', 'sw-btn__label', 'Upload PDF'));

	let runNowBtn = null;
	const actionButtons = [];
	const setButtonsDisabled = (disabled) => {
		actionButtons.forEach((btn) => {
			if (!btn) return;
			if (disabled) {
				btn.disabled = true;
				if (!btn.classList.contains('sw-btn--primary')) {
					btn.classList.add('opacity-60');
				}
				btn.classList.add('cursor-not-allowed');
			} else if (!btn.classList.contains('sw-btn--loading')) {
				btn.disabled = false;
				btn.classList.remove('opacity-60', 'cursor-not-allowed');
			}
		});
	};

	if (!localAvailable) {
		actionButtons.push(retryBtn, resolveBtn, uploadBtn);
		retryBtn.addEventListener('click', async () => {
			setButtonsDisabled(true);
			setButtonLoading(retryBtn, true, 'Retrying...');
			try {
				updateStatus('Re-queueing baseline case...');
				await api.retryBaselineCase(caseItem.id, { provider: state.provider });
				state.resolvedSource = null;
				state.stagedFile = null;
				await loadCaseDetails(caseItem.id);
				await loadCases();
				updateStatus('Baseline case re-queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to retry baseline case');
			} finally {
				setButtonLoading(retryBtn, false);
				setButtonsDisabled(false);
			}
		});
		actions.appendChild(retryBtn);
	}

	if (!localAvailable) {
		resolveBtn.addEventListener('click', async () => {
			setButtonsDisabled(true);
			setButtonLoading(resolveBtn, true, 'Searching...');
			try {
				updateStatus('Searching for open-access source...');
				const result = await api.resolveBaselineSource(caseItem.id);
				if (!result.found) {
					state.resolvedSource = null;
					state.stagedFile = null;
					state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
					updateStatus('No open-access source found.');
					renderCaseList({ skipAnalysis: true });
					return;
				}
				const resolvedUrl = result.pdf_url || result.url;
				state.resolvedSource = {
					caseId: caseItem.id,
					url: resolvedUrl,
					label: result.pdf_url ? 'PDF URL' : 'Source URL',
				};
				if (isLocalPdfUrl(resolvedUrl)) {
					state.resolvedSource.label = 'Local PDF';
				}
				state.manualPdfReasons.delete(caseItem.id);
				state.stagedFile = null;
				updateStatus(`Found ${state.resolvedSource.label}. Review and run.`);
				renderExtractionDetail(runPayload, caseItem, null);
				renderCaseList({ skipAnalysis: true });
			} catch (err) {
				updateStatus(err.message || 'Failed to resolve source');
			} finally {
				setButtonLoading(resolveBtn, false);
				setButtonsDisabled(false);
			}
		});
		if (!hasHeaderPdf) {
			actions.appendChild(resolveBtn);
		}

		uploadBtn.addEventListener('click', () => fileInput.click());
		fileInput.addEventListener('change', () => {
			const file = fileInput.files && fileInput.files[0];
			if (!file) return;
			state.stagedFile = { caseId: caseItem.id, file, name: file.name };
			state.resolvedSource = null;
			state.manualPdfReasons.delete(caseItem.id);
			fileInput.value = '';
			updateStatus(`Selected PDF: ${file.name}. Click Run now.`);
			renderExtractionDetail(runPayload, caseItem, null);
			renderCaseList({ skipAnalysis: true });
		});
		panel.appendChild(fileInput);
		actions.appendChild(uploadBtn);
	}

	panel.appendChild(actions);

	if (resolvedSource?.url) {
		const resolvedRow = el('div', 'mt-2 text-[10px] text-slate-500 break-all max-w-full');
		resolvedRow.appendChild(el('span', '', `Resolved ${resolvedSource.label}: `));
		resolvedRow.appendChild(createExternalLink(resolvedSource.url));
		panel.appendChild(resolvedRow);
	}

	if (stagedFile?.name) {
		const fileRow = el('div', 'mt-2 text-[10px] text-slate-500');
		fileRow.textContent = `Selected PDF: ${stagedFile.name}`;
		panel.appendChild(fileRow);
	}

	if (!localAvailable && ((resolvedSource && resolvedSource.url) || stagedFile)) {
		runNowBtn = el('button', 'sw-btn sw-btn--sm sw-btn--primary mt-2');
		runNowBtn.appendChild(el('span', 'sw-btn__label', 'Run now'));
		actionButtons.push(runNowBtn);
		runNowBtn.addEventListener('click', async () => {
			const sourceUrl = resolvedSource?.url;
			const staged = state.stagedFile && state.stagedFile.caseId === caseItem.id ? state.stagedFile : null;
			if (!sourceUrl && !staged) {
				updateStatus('No PDF or source URL selected.');
				return;
			}
			setButtonsDisabled(true);
			setButtonLoading(runNowBtn, true, 'Extracting...');
			try {
				if (staged) {
					updateStatus('Uploading PDF and starting extraction...');
					await api.uploadBaselinePdf(caseItem.id, staged.file, state.provider);
					state.manualPdfReasons.delete(caseItem.id);
				} else {
					updateStatus('Starting extraction with resolved source...');
					await api.retryBaselineCase(caseItem.id, { provider: state.provider, source_url: sourceUrl });
				}
				state.resolvedSource = null;
				state.stagedFile = null;
				await loadCaseDetails(caseItem.id);
				await loadCases();
				updateStatus(staged ? 'PDF uploaded and extraction started.' : 'Baseline case re-queued.');
			} catch (err) {
				updateStatus(err.message || 'Failed to start extraction');
			} finally {
				setButtonLoading(runNowBtn, false);
				setButtonsDisabled(false);
			}
		});
		panel.appendChild(runNowBtn);
	}

	return panel;
}

function getSelectedPaperGroup() {
	if (!state.selectedPaperKey) return null;
	const cases = filterCases();
	const paperGroups = groupCasesByPaper(cases);
	return paperGroups.find(g => g.key === state.selectedPaperKey) || null;
}

async function loadPaperDetails(paperKey) {
	const paperGroup = getSelectedPaperGroup();
	if (!paperGroup) {
		renderBaselineDetail(null, null, null);
		renderExtractionDetail(null, null, null);
		renderSelectedPaperStrip(null, null);
		$('#comparisonHint').textContent = 'Select a paper, then run with local PDF';
		return;
	}
	
	try {
		// Load run payload from the first case (they share the same run via DOI)
		const firstCase = paperGroup.cases[0];
		const runPayloadPromise = firstCase?.latest_run
			? api.getBaselineLatestRun(firstCase.id)
			: Promise.resolve(null);
		const localInfoPromise = firstCase?.id
			? api.getBaselineLocalPdfInfo(firstCase.id).catch(() => null)
			: Promise.resolve(null);
		const [runPayload, localInfo] = await Promise.all([runPayloadPromise, localInfoPromise]);
		
		if (localInfo && firstCase?.id) {
			if (localInfo.found) {
				state.localPdfFileByCaseId.set(firstCase.id, true);
				state.localPdfByCaseId.set(firstCase.id, true);
			} else {
				state.localPdfFileByCaseId.delete(firstCase.id);
			}
		}

		const runPdfUrl = runPayload?.run?.pdf_url;
		if (isLocalPdfUrl(runPdfUrl)) {
			markLocalPdfForGroup(paperGroup, runPdfUrl);
		}
		
		// Build paper-level comparison
		const paperComparison = buildPaperComparison(paperGroup, runPayload);
		if (paperComparison) {
			state.paperComparisonCache.set(paperKey, paperComparison);
		}
		
		renderBaselineDetail(paperGroup, paperComparison, runPayload);
		renderExtractionDetail(runPayload, paperGroup, paperComparison);
		renderSelectedPaperStrip(paperGroup, runPayload);
		
		const label = paperGroup.doi || paperGroup.pubmed_id || paperGroup.key;
		$('#comparisonHint').textContent = `Paper: ${label.length > 30 ? label.substring(0, 27) + '...' : label}`;
	} catch (err) {
		renderBaselineDetail(null, null, null);
		renderExtractionDetail(null, null, null);
		renderSelectedPaperStrip(null, null);
		$('#comparisonHint').textContent = 'Select a paper, then run with local PDF';
		updateStatus(err.message || 'Failed to load paper details');
	}
}

async function selectPaper(paperKey) {
	state.selectedPaperKey = paperKey;
	state.resolvedSource = null;
	state.stagedFile = null;
	renderCaseList({ skipAnalysis: true });
	await loadPaperDetails(paperKey);
}

// Legacy function for compatibility
async function loadCaseDetails(caseId) {
	// Find the paper key for this case
	const caseItem = state.cases.find(c => c.id === caseId);
	if (caseItem) {
		const paperKey = getPaperKey(caseItem);
		state.selectedPaperKey = paperKey;
		await loadPaperDetails(paperKey);
	}
}

// Legacy function for compatibility
async function selectCase(caseId) {
	const caseItem = state.cases.find(c => c.id === caseId);
	if (caseItem) {
		const paperKey = getPaperKey(caseItem);
		await selectPaper(paperKey);
	}
}

async function loadCases() {
	try {
		updateStatus('Loading baseline cases...');
		const data = await api.getBaselineCases(state.filterDataset);
		state.cases = data.cases || [];
		state.datasets = data.datasets || [];
		const caseIdSet = new Set(state.cases.map((item) => item.id));
		for (const caseId of state.localPdfByCaseId.keys()) {
			if (!caseIdSet.has(caseId)) {
				state.localPdfByCaseId.delete(caseId);
			}
		}
		for (const caseId of state.localPdfFileByCaseId.keys()) {
			if (!caseIdSet.has(caseId)) {
				state.localPdfFileByCaseId.delete(caseId);
			}
		}
		state.cases.forEach((item) => {
			if (item?.id && item?.pdf_url) {
				state.manualPdfReasons.delete(item.id);
			}
			if (item?.id) {
				if (isLocalPdfUrl(item.pdf_url)) {
					state.localPdfByCaseId.set(item.id, true);
				}
			}
		});
		pruneManualPdfReasons(state.cases);
		renderDatasetOptions();
		renderCaseList();
		if (state.selectedPaperKey) {
			// Check if the selected paper still exists
			const paperGroups = groupCasesByPaper(state.cases);
			const stillExists = paperGroups.some((g) => g.key === state.selectedPaperKey);
			if (!stillExists) {
				state.selectedPaperKey = null;
				state.resolvedSource = null;
				state.stagedFile = null;
				renderBaselineDetail(null, null);
				renderExtractionDetail(null, null, null);
				renderSelectedPaperStrip(null, null);
				$('#comparisonHint').textContent = 'Select a paper, then run with local PDF';
			}
		}
		updateStatus('');
	} catch (err) {
		updateStatus(err.message || 'Failed to load baseline cases');
	}
}

// --- Batch functions ---

async function loadBatches() {
	try {
		const data = await api.get(`/api/baseline/batches${state.filterDataset ? `?dataset=${encodeURIComponent(state.filterDataset)}` : ''}`);
		state.batches = data.batches || [];
		renderBatchOptions();
		updateBatchSummary();
	} catch (err) {
		console.error('Failed to load batches:', err);
	}
}

function renderBatchOptions() {
	const select = $('#batchFilter');
	if (!select) return;

	const currentValue = select.value;
	select.innerHTML = '<option value="">All runs</option>';

	for (const batch of state.batches) {
		const opt = el('option', '', batch.label || batch.batch_id);
		opt.value = batch.batch_id;
		if (batch.status === 'running') {
			opt.textContent += ' (running)';
		}
		select.appendChild(opt);
	}

	// Restore selection if still valid
	if (currentValue && state.batches.some(b => b.batch_id === currentValue)) {
		select.value = currentValue;
	}
}

function updateBatchSummary() {
	const summaryEl = $('#batchSummary');
	if (!summaryEl) return;

	if (!state.filterBatchId) {
		summaryEl.classList.add('hidden');
		$('#retryAllFailedBtn')?.classList.add('hidden');
		return;
	}

	const batch = state.batches.find(b => b.batch_id === state.filterBatchId);
	if (!batch) {
		summaryEl.classList.add('hidden');
		$('#retryAllFailedBtn')?.classList.add('hidden');
		return;
	}

	summaryEl.classList.remove('hidden');

	// Update page title in single-batch mode
	if (state.singleBatchMode) {
		const titleEl = $('#pageTitle');
		const subtitleEl = $('#pageSubtitle');
		if (titleEl) titleEl.textContent = batch.label || 'Batch Details';
		if (subtitleEl) {
			const matchInfo = batch.match_rate !== null && batch.match_rate !== undefined
				? ` | Match rate: ${(batch.match_rate * 100).toFixed(0)}%`
				: '';
			subtitleEl.textContent = `${batch.model_name || batch.model_provider} | ${batch.status}${matchInfo}`;
		}
	}

	$('#batchLabel').textContent = batch.label || batch.batch_id;
	$('#batchModel').textContent = batch.model_name || batch.model_provider;
	$('#batchProgress').textContent = `${batch.completed}/${batch.total_papers} complete` +
		(batch.failed > 0 ? `, ${batch.failed} failed` : '');
	$('#batchProgress').className = 'sw-chip' + (batch.failed > 0 ? ' sw-chip--warning' : '');

	// Format tokens
	const totalTokens = (batch.total_input_tokens || 0) + (batch.total_output_tokens || 0);
	$('#batchTokens').textContent = totalTokens > 0 ? `${totalTokens.toLocaleString()} tokens` : 'N/A';

	// Format time
	const timeMs = batch.total_time_ms || 0;
	if (timeMs > 0) {
		const seconds = (timeMs / 1000).toFixed(1);
		$('#batchTime').textContent = `${seconds}s`;
	} else {
		$('#batchTime').textContent = 'N/A';
	}

	// Format match rate
	const matchRateEl = $('#batchMatchRate');
	if (matchRateEl) {
		if (batch.match_rate !== null && batch.match_rate !== undefined) {
			const pct = (batch.match_rate * 100).toFixed(0);
			matchRateEl.textContent = `${pct}%`;
			matchRateEl.className = 'sw-chip' + (batch.match_rate >= 0.7 ? ' sw-chip--success' : batch.match_rate >= 0.4 ? ' sw-chip--info' : ' sw-chip--warning');
		} else if (batch.total_expected_entities > 0) {
			const pct = (batch.matched_entities / batch.total_expected_entities * 100).toFixed(0);
			matchRateEl.textContent = `${pct}%`;
		} else {
			matchRateEl.textContent = 'N/A';
		}
	}

	// Format cost
	const costEl = $('#batchCost');
	if (costEl) {
		if (batch.estimated_cost_usd !== null && batch.estimated_cost_usd !== undefined) {
			costEl.textContent = batch.estimated_cost_usd < 0.01 ? '<$0.01' : `$${batch.estimated_cost_usd.toFixed(2)}`;
		} else {
			costEl.textContent = 'N/A';
		}
	}

	// Show retry button if there are failed runs
	const retryBtn = $('#retryAllFailedBtn');
	if (retryBtn) {
		if (batch.failed > 0) {
			retryBtn.classList.remove('hidden');
			retryBtn.textContent = `Retry ${batch.failed} Failed`;
		} else {
			retryBtn.classList.add('hidden');
		}
	}
}

async function runAllBatch() {
	const runAllBtn = $('#runAllBtn');
	if (!runAllBtn) return;

	const dataset = state.filterDataset;
	if (!dataset) {
		updateStatus('Please select a dataset first');
		return;
	}

	// Prompt for optional batch label
	const label = prompt('Enter a label for this batch (optional):', '');

	setButtonLoading(runAllBtn, true, 'Starting...');

	try {
		const resp = await api.post('/api/baseline/batch-enqueue', {
			dataset: dataset,
			label: label || undefined,
			provider: state.provider,
			force: false,
		});

		updateStatus(`Batch ${resp.batch_id} created: ${resp.enqueued} papers enqueued`);

		// Reload batches and select the new one
		await loadBatches();
		state.filterBatchId = resp.batch_id;
		const batchSelect = $('#batchFilter');
		if (batchSelect) batchSelect.value = resp.batch_id;
		updateBatchSummary();

	} catch (err) {
		updateStatus(err.message || 'Failed to create batch');
	} finally {
		setButtonLoading(runAllBtn, false);
	}
}

async function retryAllFailed() {
	const retryBtn = $('#retryAllFailedBtn');
	if (!retryBtn || !state.filterBatchId) return;

	setButtonLoading(retryBtn, true, 'Retrying...');

	try {
		const resp = await api.post('/api/baseline/batch-retry', {
			batch_id: state.filterBatchId,
			provider: state.provider,
		});

		updateStatus(`Retrying ${resp.retried} failed runs`);
		await loadBatches();
		updateBatchSummary();

	} catch (err) {
		updateStatus(err.message || 'Failed to retry batch');
	} finally {
		setButtonLoading(retryBtn, false);
	}
}

async function enqueueBaselineRuns() {
	const runButton = $('#runBaselineBtn');
	if (runButton) {
		runButton.disabled = true;
		runButton.classList.add('opacity-60', 'cursor-not-allowed');
	}
	try {
		const dataset = state.filterDataset || null;
		const provider = state.provider || 'openai';
		updateStatus(dataset ? `Enqueuing ${dataset} (${provider})...` : `Enqueuing baseline (${provider})...`);
		const response = await api.enqueueBaselineAll(provider, null, dataset, false);
		const enqueued = response?.enqueued ?? 0;
		const skipped = response?.skipped ?? 0;
		const total = response?.total ?? (enqueued + skipped);
		const summary = `Enqueued ${enqueued} of ${total} cases${skipped ? ` (${skipped} skipped)` : ''}.`;
		updateStatus(summary);
		await loadCases();
	} catch (err) {
		updateStatus(err.message || 'Failed to enqueue baseline benchmark');
	} finally {
		if (runButton) {
			runButton.disabled = false;
			runButton.classList.remove('opacity-60', 'cursor-not-allowed');
		}
	}
}

async function resolveBaselineSourcesBulk() {
	const resolveButton = $('#resolveBaselineBtn');
	const cases = filterCases();
	if (!cases.length) {
		updateStatus('No baseline cases in the current filter.');
		return;
	}
	const targets = cases.filter((item) => !item?.pdf_url);
	const skipped = cases.length - targets.length;
	if (!targets.length) {
		updateStatus('All filtered cases already have PDF links.');
		return;
	}
	if (resolveButton) {
		setButtonLoading(resolveButton, true, 'Finding PDFs...');
	}
	let completed = 0;
	let found = 0;
	let notFound = 0;
	let errors = 0;
	const total = targets.length;
	const reportProgress = () => {
		updateStatus(`Resolving PDFs: ${completed}/${total}...`);
	};
	reportProgress();
	try {
		await mapWithConcurrency(targets, 6, async (caseItem) => {
			try {
				const result = await api.resolveBaselineSource(caseItem.id);
				if (result?.found) {
					const resolvedUrl = result.pdf_url || result.url;
					if (resolvedUrl) {
						caseItem.pdf_url = resolvedUrl;
					}
					state.manualPdfReasons.delete(caseItem.id);
					found += 1;
				} else {
					state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
					notFound += 1;
				}
			} catch (err) {
				state.manualPdfReasons.set(caseItem.id, MANUAL_PDF_REASON_NO_OA);
				errors += 1;
			} finally {
				completed += 1;
				reportProgress();
			}
		});
		const failures = notFound + errors;
		const summaryParts = [`Resolved ${found} of ${total}`];
		if (failures) summaryParts.push(`${failures} need manual PDF`);
		if (skipped) summaryParts.push(`${skipped} skipped`);
		updateStatus(`${summaryParts.join('. ')}.`);
		renderCaseList({ skipAnalysis: true });
		if (state.selectedPaperKey) {
			await loadPaperDetails(state.selectedPaperKey);
		}
	} finally {
		if (resolveButton) {
			setButtonLoading(resolveButton, false);
		}
	}
}

function connectSSE() {
	if (sseConnection) {
		sseConnection.close();
	}
	sseConnection = api.createSSEConnection((message) => {
		if (message.event !== 'run_status') return;
		const data = message.data || {};
		const caseIds = Array.isArray(data.baseline_case_ids) && data.baseline_case_ids.length
			? data.baseline_case_ids
			: (data.baseline_case_id ? [data.baseline_case_id] : []);
		if (!caseIds.length) return;
		let updated = false;
		let selectedPaperUpdated = false;
		const updatedPaperKeys = new Set();
		
		caseIds.forEach((caseId) => {
			const caseItem = state.cases.find((item) => item.id === caseId);
			if (!caseItem) return;
			updated = true;
			state.runPayloadCache.delete(caseId);
			state.comparisonCache.delete(caseId);
			caseItem.latest_run = {
				run_id: data.run_id,
				status: data.status,
				failure_reason: data.failure_reason || null,
			};
			
			// Track which paper groups are affected
			const paperKey = getPaperKey(caseItem);
			updatedPaperKeys.add(paperKey);
			state.paperComparisonCache.delete(paperKey);
			
			if (state.selectedPaperKey === paperKey) {
				selectedPaperUpdated = true;
			}
		});
		
		if (!updated) return;
		renderCaseList();
		
		if (selectedPaperUpdated) {
			if (isProcessingStatus(data.status)) {
				updateStatus(`Extraction ${getStatusLabel(data.status).toLowerCase()}...`);
			} else if (data.status === 'stored') {
				updateStatus('Extraction complete.');
			} else if (data.status === 'failed') {
				updateStatus('Extraction failed.');
			} else if (data.status === 'cancelled') {
				updateStatus('Extraction cancelled.');
			}
			loadPaperDetails(state.selectedPaperKey);
		}
	});
}

function initEventHandlers() {
	const datasetFilter = $('#datasetFilter');
	if (datasetFilter) {
		datasetFilter.addEventListener('change', async (event) => {
			state.filterDataset = event.target.value;
			await loadCases();
		});
	}

	const caseSearch = $('#caseSearch');
	if (caseSearch) {
		caseSearch.addEventListener('input', (event) => {
			state.search = event.target.value || '';
			renderCaseList();
		});
	}

	const searchBtn = $('#searchBtn');
	if (searchBtn) {
		searchBtn.addEventListener('click', () => {
			state.search = caseSearch ? caseSearch.value || '' : '';
			renderCaseList();
		});
	}

	const providerSelect = $('#baselineProvider');
	if (providerSelect) {
		state.provider = providerSelect.value || 'openai';
		providerSelect.addEventListener('change', (event) => {
			state.provider = event.target.value || 'openai';
		});
	}

	const pdfStatusFilter = $('#pdfStatusFilter');
	if (pdfStatusFilter) {
		state.pdfStatusFilter = pdfStatusFilter.value || 'all';
		pdfStatusFilter.addEventListener('change', (event) => {
			state.pdfStatusFilter = event.target.value || 'all';
			renderCaseList();
		});
	}

	const runButton = $('#runBaselineBtn');
	if (runButton) {
		runButton.addEventListener('click', () => {
			enqueueBaselineRuns();
		});
	}

	const resolveButton = $('#resolveBaselineBtn');
	if (resolveButton) {
		resolveButton.addEventListener('click', () => {
			resolveBaselineSourcesBulk();
		});
	}

	// Batch controls
	const batchFilter = $('#batchFilter');
	if (batchFilter) {
		batchFilter.addEventListener('change', (event) => {
			state.filterBatchId = event.target.value || '';
			updateBatchSummary();
			renderCaseList();  // Re-render with batch filter
		});
	}

	const runAllBtn = $('#runAllBtn');
	if (runAllBtn) {
		runAllBtn.addEventListener('click', () => {
			runAllBatch();
		});
	}

	const retryBtn = $('#retryAllFailedBtn');
	if (retryBtn) {
		retryBtn.addEventListener('click', () => {
			retryAllFailed();
		});
	}
}

export async function initBaseline() {
	// Check if we're in single-batch mode (URL has batch_id)
	const urlBatchId = getBatchIdFromUrl();
	if (urlBatchId) {
		state.singleBatchMode = true;
		state.filterBatchId = urlBatchId;

		// Update page title
		const titleEl = $('#pageTitle');
		const subtitleEl = $('#pageSubtitle');
		if (titleEl) titleEl.textContent = 'Batch Details';
		if (subtitleEl) subtitleEl.textContent = `Viewing batch: ${urlBatchId}`;
	} else {
		// Legacy mode - show all batches (should redirect to overview)
		// Keep dropdowns visible for backward compatibility
		$('#datasetFilterLabel')?.classList.remove('hidden');
		$('#batchFilterLabel')?.classList.remove('hidden');
		$('#runAllBtn')?.classList.remove('hidden');
	}

	initEventHandlers();
	await Promise.all([loadCases(), loadBatches()]);

	// In single-batch mode, show batch summary immediately
	if (state.singleBatchMode) {
		updateBatchSummary();
	}

	connectSSE();
}
