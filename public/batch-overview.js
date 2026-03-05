/**
 * Evaluation overview page - displays run cards and handles run creation.
 */
import * as api from './js/api.js';
import { $, el } from './js/renderers.js';
import {
	validateGroupDraft,
	validatePaperDraft,
	buildGroupPayload,
	buildPaperPayload,
	submitCreateGroupMock,
	submitSavePaperMock,
	submitDeleteGroupMock,
	submitDeletePaperMock,
} from './js/baseline/actions/eval_builder_mock_actions.js';

const STATUS_COLORS = {
	running: 'border-cyan-400',
	completed: 'border-emerald-400',
	partial: 'border-amber-400',
	failed: 'border-rose-400',
};

const STATUS_LABELS = {
	running: 'Running',
	completed: 'Completed',
	partial: 'Partial',
	failed: 'Failed',
};

const RANKABLE_BATCH_STATUSES = new Set(['running', 'completed', 'partial', 'failed']);
const BASELINE_ACCURACY_TARGET = 368;
const BASELINE_PAPERS_TARGET = 69;
const ENABLE_PARETO_POINT_HOVER_TOOLTIP = true;
const DEFAULT_PROVIDER_METRIC = 'accuracy';
const PROVIDER_METRIC_STORAGE_KEY = 'peptide.evaluation.chart.metric';
const PROVIDER_COMPLETE_ONLY_STORAGE_KEY = 'peptide.evaluation.chart.complete_only';
const DATASET_FILTER_STORAGE_KEY = 'peptide.evaluation.dataset';
const SVG_NS = 'http://www.w3.org/2000/svg';
const COMPACT_FORMAT = new Intl.NumberFormat('en-US', {
	notation: 'compact',
	maximumFractionDigits: 1,
});
const NUMBER_FORMAT = new Intl.NumberFormat('en-US');
const EVAL_BUILDER_PRIMARY_DATASET_ID = 'self_assembly';
const EVAL_BUILDER_PRIMARY_PAPER_COUNT = 69;

const PROVIDER_METRICS = {
	accuracy: {
		id: 'accuracy',
		label: 'Accuracy',
		axisMode: 'percent',
	},
	papers_all_matched: {
		id: 'papers_all_matched',
		label: 'Papers Fully Matched',
		axisMode: 'number',
	},
	total_cost: {
		id: 'total_cost',
		label: 'Total Cost',
		axisMode: 'number',
	},
	total_time: {
		id: 'total_time',
		label: 'Total Time',
		axisMode: 'number',
	},
	pareto_frontier: {
		id: 'pareto_frontier',
		label: 'Pareto Frontier',
		axisMode: 'pareto',
	},
	pareto_frontier_accuracy: {
		id: 'pareto_frontier_accuracy',
		label: 'Pareto Frontier (Accuracy)',
		axisMode: 'pareto',
	},
};

const state = {
	batches: [],
	prompts: [],
	providers: [],
	datasetOptions: [],
	selectedDataset: 'self_assembly',
	cases: [],
	datasets: [],
	activePromptId: null,
	sseConnection: null,
	providerChartState: 'loading',
	providerChartError: '',
	providerChartHasAnimated: false,
	providerChartMetric: DEFAULT_PROVIDER_METRIC,
	providerChartCompleteOnly: false,
	evalBuilder: {
		open: false,
		selectedDatasetId: null,
		selectedPaperKey: null,
		mode: 'edit_group',
		draftGroup: { id: '', label: '', description: '' },
		draftPaper: {
			title: '',
			doi: '',
			paper_url: '',
			main_pdf_file: null,
			supporting_pdf_files: [],
		},
		draftGroundTruthEntities: [{ sequence: '', n_terminal: '', c_terminal: '', labels_csv: '', notes: '' }],
		busy: false,
		loaded: false,
	},
};

let chartResizeTimer = null;

function getDatasetFilterFromStorage() {
	try {
		const stored = window.localStorage.getItem(DATASET_FILTER_STORAGE_KEY);
		return stored ? stored.trim() : '';
	} catch (_err) {
		return '';
	}
}

function persistDatasetFilter(datasetId) {
	try {
		if (datasetId) {
			window.localStorage.setItem(DATASET_FILTER_STORAGE_KEY, datasetId);
		} else {
			window.localStorage.removeItem(DATASET_FILTER_STORAGE_KEY);
		}
	} catch (_err) {
		// Ignore storage errors.
	}
}

function getBatchesEndpoint() {
	const dataset = (state.selectedDataset || '').trim();
	if (!dataset) return '/api/baseline/batches';
	return `/api/baseline/batches?dataset=${encodeURIComponent(dataset)}`;
}

function buildBatchDetailHref(batchId) {
	const id = encodeURIComponent(batchId);
	const dataset = (state.selectedDataset || '').trim();
	if (!dataset) return `/baseline/${id}`;
	return `/baseline/${id}?dataset=${encodeURIComponent(dataset)}`;
}

function renderDatasetFilterOptions() {
	const select = $('#batchDatasetFilter');
	if (!select) return;
	select.innerHTML = '';
	if (!state.datasetOptions.length) {
		const fallback = document.createElement('option');
		fallback.value = '';
		fallback.textContent = 'No groups';
		select.appendChild(fallback);
		select.disabled = true;
		return;
	}
	select.disabled = false;
	state.datasetOptions.forEach((dataset) => {
		const option = document.createElement('option');
		option.value = dataset.id;
		const label = dataset.label || dataset.id;
		const count = Number(dataset.count || 0);
		option.textContent = `${label}${count > 0 ? ` (${count})` : ''}`;
		select.appendChild(option);
	});
	select.value = state.selectedDataset;
}

async function loadDatasetOptions() {
	try {
		const datasets = await api.getBaselineDatasets();
		state.datasetOptions = Array.isArray(datasets) ? datasets : [];
		const available = new Set(state.datasetOptions.map((item) => item.id));
		const stored = getDatasetFilterFromStorage();
		const preferred = stored || (state.selectedDataset || '').trim();
		if (preferred && available.has(preferred)) {
			state.selectedDataset = preferred;
		} else if (stored && available.has(stored)) {
			state.selectedDataset = stored;
		} else if (available.has('self_assembly')) {
			state.selectedDataset = 'self_assembly';
		} else {
			state.selectedDataset = state.datasetOptions[0]?.id || '';
		}
		persistDatasetFilter(state.selectedDataset);
		renderDatasetFilterOptions();
	} catch (err) {
		console.error('Failed to load dataset options:', err);
	}
}

function normalizeProviderKey(provider) {
	return (provider || 'unknown').toString().trim().toLowerCase();
}

function normalizeModelKey(modelName) {
	return (modelName || '').toString().trim().toLowerCase();
}

function formatProviderName(provider) {
	const key = normalizeProviderKey(provider);
	const descriptor = (state.providers || []).find(
		(item) => normalizeProviderKey(item.provider_id) === key,
	);
	if (descriptor?.label) return descriptor.label;
	if (key === 'openai') return 'OpenAI Full';
	if (key === 'openai-mini') return 'OpenAI Mini';
	if (key === 'openai-nano') return 'OpenAI Nano';
	if (key === 'openrouter') return 'OpenRouter';
	if (key === 'gemini') return 'Gemini';
	if (key === 'deepseek') return 'DeepSeek';
	if (key === 'mock') return 'Mock';
	return provider || 'Unknown';
}

function getBatchModelLabel(batch) {
	const modelName = (batch.model_name || '').toString().trim();
	if (modelName) return modelName;
	const provider = (batch.model_provider || '').toString().trim();
	if (provider) return `${formatProviderName(provider)} (default)`;
	return 'Unknown model';
}

function formatDuration(ms) {
	if (!ms) return '0s';
	const seconds = Math.floor(ms / 1000);
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	const remSeconds = seconds % 60;
	if (minutes < 60) return `${minutes}m ${remSeconds}s`;
	const hours = Math.floor(minutes / 60);
	const remMinutes = minutes % 60;
	return `${hours}h ${remMinutes}m`;
}

function formatTokens(count) {
	if (!count) return '0';
	if (count < 1000) return String(count);
	if (count < 1000000) return `${(count / 1000).toFixed(1)}K`;
	return `${(count / 1000000).toFixed(2)}M`;
}

function formatCost(batch) {
	const total = getBatchEstimatedCostUsd(batch);
	if (!Number.isFinite(total)) return '?';
	if (total < 0.01) return '<$0.01';
	return `$${total.toFixed(2)}`;
}

function formatMatchRate(batch) {
	if (!batch.total_expected_entities) return 'n/a';
	const rate = batch.matched_entities / batch.total_expected_entities;
	return `${(rate * 100).toFixed(0)}%`;
}

function formatDate(isoString) {
	if (!isoString) return '';
	const date = new Date(isoString);
	return date.toLocaleDateString('en-US', {
		month: 'short',
		day: 'numeric',
		hour: '2-digit',
		minute: '2-digit',
	});
}

function getProgressPercent(batch) {
	if (!batch.total_papers) return 0;
	return ((batch.completed + batch.failed) / batch.total_papers) * 100;
}

function formatCount(value) {
	return NUMBER_FORMAT.format(Number(value || 0));
}

function formatCompactNumber(value) {
	return COMPACT_FORMAT.format(Number(value || 0));
}

function formatPercent(value, digits = 1) {
	if (!Number.isFinite(value)) return 'n/a';
	return `${(value * 100).toFixed(digits)}%`;
}

function formatCurrency(value) {
	if (!Number.isFinite(value)) return 'n/a';
	if (value > 0 && value < 0.01) return '<$0.01';
	if (value >= 100) return `$${value.toFixed(0)}`;
	if (value >= 10) return `$${value.toFixed(1)}`;
	return `$${value.toFixed(2)}`;
}

function formatCurrencyTick(value) {
	if (!Number.isFinite(value)) return 'n/a';
	if (value >= 1000) return `$${formatCompactNumber(value)}`;
	if (value >= 100) return `$${value.toFixed(0)}`;
	if (value >= 10) return `$${value.toFixed(1)}`;
	return `$${value.toFixed(2)}`;
}

function formatDurationTick(ms) {
	if (!Number.isFinite(ms) || ms <= 0) return '0s';
	const seconds = Math.floor(ms / 1000);
	if (seconds < 60) return `${seconds}s`;
	const minutes = Math.floor(seconds / 60);
	if (minutes < 60) return `${minutes}m`;
	const hours = Math.floor(minutes / 60);
	if (hours < 24) return `${hours}h`;
	const days = Math.floor(hours / 24);
	return `${days}d`;
}

function getMetricConfig(metricId) {
	return PROVIDER_METRICS[metricId] || PROVIDER_METRICS[DEFAULT_PROVIDER_METRIC];
}

function getProviderChartMetricFromStorage() {
	try {
		const stored = window.localStorage.getItem(PROVIDER_METRIC_STORAGE_KEY);
		if (stored && PROVIDER_METRICS[stored]) return stored;
	} catch (_err) {
		// Ignore storage errors; default metric still works.
	}
	return DEFAULT_PROVIDER_METRIC;
}

function persistProviderChartMetric(metricId) {
	try {
		window.localStorage.setItem(PROVIDER_METRIC_STORAGE_KEY, metricId);
	} catch (_err) {
		// Ignore storage errors; state keeps working.
	}
}

function getProviderChartCompleteOnlyFromStorage() {
	try {
		return window.localStorage.getItem(PROVIDER_COMPLETE_ONLY_STORAGE_KEY) === '1';
	} catch (_err) {
		// Ignore storage errors; default toggle state still works.
	}
	return false;
}

function persistProviderChartCompleteOnly(value) {
	try {
		window.localStorage.setItem(PROVIDER_COMPLETE_ONLY_STORAGE_KEY, value ? '1' : '0');
	} catch (_err) {
		// Ignore storage errors; state keeps working.
	}
}

function initProviderMetricControls() {
	const select = $('#providerMetricSelect');
	const completeOnlyToggle = $('#providerCompleteOnlyToggle');
	if (!select) return;

	select.innerHTML = '';
	Object.values(PROVIDER_METRICS).forEach((metric) => {
		const option = el('option', '', metric.label);
		option.value = metric.id;
		select.appendChild(option);
	});

	state.providerChartMetric = getProviderChartMetricFromStorage();
	select.value = state.providerChartMetric;
	state.providerChartCompleteOnly = getProviderChartCompleteOnlyFromStorage();
	if (completeOnlyToggle) {
		completeOnlyToggle.checked = state.providerChartCompleteOnly;
	}

	select.addEventListener('change', (event) => {
		const nextMetric = event.target.value;
		if (!PROVIDER_METRICS[nextMetric]) return;
		state.providerChartMetric = nextMetric;
		persistProviderChartMetric(nextMetric);
		renderProviderAccuracyChart();
	});
	if (completeOnlyToggle) {
		completeOnlyToggle.addEventListener('change', (event) => {
			state.providerChartCompleteOnly = !!event.target.checked;
			persistProviderChartCompleteOnly(state.providerChartCompleteOnly);
			renderProviderAccuracyChart();
		});
	}
}

function getBatchEstimatedCostUsd(batch) {
	const directCost = Number(batch.estimated_cost_usd);
	if (Number.isFinite(directCost) && directCost >= 0) return directCost;
	return null;
}

function isBatchFullyExtracted(batch) {
	const totalPapers = Math.max(0, Number(batch.total_papers || 0));
	const completedPapers = Math.max(0, Number(batch.completed || 0));
	const failedPapers = Math.max(0, Number(batch.failed || 0));
	const status = (batch.status || '').toString().trim().toLowerCase();
	if (totalPapers <= 0) return false;
	return failedPapers === 0 && completedPapers >= totalPapers && (status === 'completed' || status.includes('completed'));
}

function selectFinishedBatches(batches, { completeOnly = false } = {}) {
	return batches.filter((batch) => {
		const status = (batch.status || '').toString().trim().toLowerCase();
		const model = (batch.model_name || '').toString().trim();
		const provider = (batch.model_provider || '').toString().trim();
		const isRankable =
			RANKABLE_BATCH_STATUSES.has(status) ||
			status.includes('partial') ||
			status.includes('completed') ||
			status.includes('failed');
		if (!isRankable || !(model || provider)) return false;
		if (completeOnly && !isBatchFullyExtracted(batch)) return false;
		return true;
	});
}

function aggregateProviderStats(finishedBatches) {
	const grouped = new Map();
	for (const batch of finishedBatches) {
		const modelRaw = (batch.model_name || '').toString().trim();
		const providerRaw = (batch.model_provider || '').toString().trim();
		if (!modelRaw && !providerRaw) continue;
		const matched = Math.max(0, Number(batch.matched_entities || 0));
		const papersAllMatched = Math.max(0, Number(batch.papers_all_matched || 0));
		const totalPapers = Math.max(0, Number(batch.total_papers || 0));
		const accuracyExpected = BASELINE_ACCURACY_TARGET;
		const modelKey = modelRaw
			? normalizeModelKey(modelRaw)
			: `provider:${normalizeProviderKey(providerRaw)}`;
		if (!grouped.has(modelKey)) {
			grouped.set(modelKey, {
				modelKey,
				providerLabel: getBatchModelLabel(batch),
				matched: 0,
				expected: 0,
				accuracyRuns: 0,
				accuracyTarget: BASELINE_ACCURACY_TARGET,
				papersAllMatchedBest: 0,
				papersTargetMax: 0,
				papersAllMatchedSamples: 0,
				cost: 0,
				costSamples: 0,
				timeMs: 0,
				batches: 0,
			});
		}
		const row = grouped.get(modelKey);
		row.matched += matched;
		row.expected += accuracyExpected;
		row.accuracyRuns += 1;
		row.papersTargetMax = Math.max(row.papersTargetMax, totalPapers);
		if (Number.isFinite(Number(batch.papers_all_matched))) {
			const capped = totalPapers > 0 ? Math.min(papersAllMatched, totalPapers) : papersAllMatched;
			row.papersAllMatchedBest = Math.max(row.papersAllMatchedBest, capped);
			row.papersAllMatchedSamples += 1;
		}
		const batchCost = getBatchEstimatedCostUsd(batch);
		if (Number.isFinite(batchCost)) {
			row.cost += batchCost;
			row.costSamples += 1;
		}
		row.timeMs += Math.max(0, Number(batch.total_time_ms || 0));
		row.batches += 1;
	}

	return Array.from(grouped.values());
}

function computeMetricValue(row, metric) {
	switch (metric.id) {
		case 'accuracy':
			return row.accuracyRuns > 0 ? row.matched / (row.accuracyRuns * row.accuracyTarget) : null;
		case 'papers_all_matched':
			return row.papersAllMatchedSamples > 0 ? Number(row.papersAllMatchedBest || 0) : null;
		case 'total_cost':
			return row.costSamples > 0 ? Number(row.cost || 0) : null;
		case 'total_time':
			return Number(row.timeMs || 0);
		default:
			return null;
	}
}

function buildMetricMetaLabel(row, metric, compact) {
	switch (metric.id) {
		case 'accuracy': {
			const avgMatched = row.accuracyRuns > 0 ? row.matched / row.accuracyRuns : 0;
			return compact
				? `${formatCount(Math.round(avgMatched))}/${formatCount(row.accuracyTarget)} avg · ${row.batches}r`
				: `${formatCount(Math.round(avgMatched))}/${formatCount(row.accuracyTarget)} avg matched · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		}
		case 'papers_all_matched':
			return compact
				? `${formatCount(row.papersAllMatchedBest)}/${formatCount(row.papersTargetMax)} papers · ${row.batches}r`
				: `${formatCount(row.papersAllMatchedBest)}/${formatCount(row.papersTargetMax)} papers fully matched · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		case 'total_cost':
			return compact
				? `${formatCurrency(row.cost)} total · ${row.batches}r`
				: `${formatCurrency(row.cost)} total spend · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		case 'total_time':
			return compact
				? `${formatDuration(row.timeMs)} total · ${row.batches}r`
				: `${formatDuration(row.timeMs)} total time · ${row.batches} run${row.batches === 1 ? '' : 's'}`;
		default:
			return '';
	}
}

function formatMetricValue(metric, value, row = null) {
	switch (metric.id) {
		case 'accuracy':
			return formatPercent(value, 1);
		case 'papers_all_matched':
			return row?.papersTargetMax > 0
				? `${formatCount(value)}/${formatCount(row.papersTargetMax)}`
				: formatCount(value);
		case 'total_cost':
			return formatCurrency(value);
		case 'total_time':
			return formatDuration(value);
		default:
			return String(value);
	}
}

function formatMetricTick(metric, value) {
	switch (metric.id) {
		case 'accuracy':
			return `${Math.round(value * 100)}%`;
		case 'papers_all_matched':
			return formatCompactNumber(value);
		case 'total_cost':
			return formatCurrencyTick(value);
		case 'total_time':
			return formatDurationTick(value);
		default:
			return String(value);
	}
}

function computeProviderMetricRows(finishedBatches, metric) {
	const aggregated = aggregateProviderStats(finishedBatches);
	const rows = [];

	aggregated.forEach((row) => {
		const metricValue = computeMetricValue(row, metric);
		if (!Number.isFinite(metricValue) || metricValue < 0) {
			return;
		}
		rows.push({
			...row,
			metricValue,
		});
	});

	rows.sort((a, b) => {
		const delta = b.metricValue - a.metricValue;
		if (delta !== 0) return delta;
		if (b.matched !== a.matched) return b.matched - a.matched;
		return b.expected - a.expected;
	});

	const totals = rows.reduce(
		(acc, row) => {
			acc.matched += row.matched;
			acc.expected += row.expected;
			acc.papersAllMatched += row.papersAllMatchedBest;
			acc.papersTargetMax = Math.max(acc.papersTargetMax, row.papersTargetMax || 0);
			acc.cost += row.cost;
			acc.timeMs += row.timeMs;
			acc.runs += row.batches;
			return acc;
		},
		{ matched: 0, expected: 0, papersAllMatched: 0, papersTargetMax: 0, cost: 0, timeMs: 0, runs: 0 },
	);

	return { rows, totals };
}

function getNiceStep(rawStep) {
	if (!Number.isFinite(rawStep) || rawStep <= 0) return 1;
	const magnitude = 10 ** Math.floor(Math.log10(rawStep));
	const normalized = rawStep / magnitude;
	if (normalized <= 1) return 1 * magnitude;
	if (normalized <= 2) return 2 * magnitude;
	if (normalized <= 5) return 5 * magnitude;
	return 10 * magnitude;
}

function buildAxisTicks(metric, maxValue) {
	if (metric.axisMode === 'percent') {
		const values = [0, 0.25, 0.5, 0.75, 1];
		return {
			max: 1,
			values,
		};
	}

	if (metric.id === 'papers_all_matched') {
		const axisMax = Math.max(1, Math.round(maxValue || 0));
		const tickValues = Array.from(
			new Set([
				0,
				Math.round(axisMax * 0.25),
				Math.round(axisMax * 0.5),
				Math.round(axisMax * 0.75),
				axisMax,
			]),
		).sort((a, b) => a - b);
		return {
			max: axisMax,
			values: tickValues,
		};
	}

	const safeMax = Math.max(0, maxValue || 0);
	const step = getNiceStep(safeMax / 4 || 1);
	const axisMax = Math.max(step * 4, step);
	return {
		max: axisMax,
		values: [0, step, step * 2, step * 3, step * 4],
	};
}

function truncateLabel(value, maxLength) {
	if (!value || value.length <= maxLength) return value;
	return `${value.slice(0, Math.max(1, maxLength - 1))}\u2026`;
}

function buildProviderChartModel(rows, metric, containerWidth) {
	const width = Math.max(320, Math.floor(containerWidth || 720));
	const compact = width < 720;
	const leftPad = compact ? 122 : 198;
	const rightPad = compact ? 96 : 138;
	const rowHeight = compact ? 46 : 54;
	const barHeight = compact ? 10 : 12;
	const topPad = 24;
	const bottomPad = 44;
	const plotWidth = Math.max(120, width - leftPad - rightPad);
	const axisY = topPad + rows.length * rowHeight + 8;
	const maxMetricValue = metric.id === 'papers_all_matched'
		? rows.reduce((max, row) => Math.max(max, Number(row.papersTargetMax || 0)), 0)
		: rows.reduce((max, row) => Math.max(max, row.metricValue), 0);
	const axis = buildAxisTicks(metric, maxMetricValue);
	const ticks = axis.values.map((value) => ({
		value,
		x: leftPad + plotWidth * (axis.max ? value / axis.max : 0),
		label: formatMetricTick(metric, value),
	}));
	const chartRows = rows.map((row, index) => {
		const ratio = axis.max > 0 ? Math.max(0, Math.min(1, row.metricValue / axis.max)) : 0;
		const yTop = topPad + index * rowHeight;
		const yCenter = yTop + (compact ? 16 : 18);

		return {
			...row,
			providerLabel: compact ? truncateLabel(row.providerLabel, 13) : row.providerLabel,
			ratio,
			valueLabel: formatMetricValue(metric, row.metricValue, row),
			metaLabel: buildMetricMetaLabel(row, metric, compact),
			yTop,
			yCenter,
			barX: leftPad,
			barY: yCenter - barHeight / 2,
			barWidth: plotWidth * ratio,
			barHeight,
			markerX: leftPad + plotWidth * ratio,
		};
	});

	return {
		width,
		height: axisY + bottomPad,
		compact,
		leftPad,
		plotWidth,
		axisY,
		axisMax: axis.max,
		ticks,
		rows: chartRows,
	};
}

function computeParetoFrontierRows(finishedBatches, yMetric = 'papers') {
	const aggregated = aggregateProviderStats(finishedBatches);
	const points = [];
	for (const row of aggregated) {
		const modelKey = (row.modelKey || '').toString().trim().toLowerCase();
		const providerLabel = (row.providerLabel || '').toString().trim().toLowerCase();
		if (modelKey === 'mock-model' || modelKey === 'provider:mock' || providerLabel.startsWith('mock')) {
			continue;
		}
		if (row.costSamples <= 0) continue;
		const x = Number(row.cost || 0);
		const y = yMetric === 'accuracy'
			? (row.accuracyRuns > 0 ? row.matched / (row.accuracyRuns * row.accuracyTarget) : NaN)
			: (row.papersAllMatchedSamples > 0 ? Number(row.papersAllMatchedBest || 0) : NaN);
		if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0) continue;
		points.push({
			...row,
			x,
			y,
			isFrontier: false,
		});
	}
	points.sort((a, b) => {
		if (a.x !== b.x) return a.x - b.x;
		return b.y - a.y;
	});

	let bestY = -Infinity;
	for (const point of points) {
		if (point.y > bestY) {
			point.isFrontier = true;
			bestY = point.y;
		}
	}
	return points;
}

function buildLogAxis(minValue, maxValue) {
	const min = Math.max(Number(minValue || 0), 1e-9);
	const max = Math.max(Number(maxValue || 0), min);
	const minExp = Math.floor(Math.log10(min));
	const maxExp = Math.ceil(Math.log10(max));
	const expRange = Math.max(0, maxExp - minExp);
	const stepExp = Math.max(1, Math.ceil(expRange / 6));
	const values = [];
	for (let exp = minExp; exp <= maxExp; exp += stepExp) {
		values.push(10 ** exp);
	}
	const axisMin = 10 ** minExp;
	const axisMax = 10 ** maxExp;
	if (!values.includes(axisMax)) values.push(axisMax);
	return {
		min: axisMin,
		max: axisMax,
		values: Array.from(new Set(values)).sort((a, b) => a - b),
	};
}

function buildNumericAxis(maxValue, tickCount = 4) {
	const safeMax = Math.max(0, Number(maxValue || 0));
	const step = getNiceStep(safeMax / tickCount || 1);
	const axisMax = Math.max(step * tickCount, step);
	const values = [];
	for (let idx = 0; idx <= tickCount; idx += 1) {
		values.push(step * idx);
	}
	return {
		max: axisMax,
		values,
	};
}

function buildProviderParetoModel(points, containerWidth, yMetric = 'papers') {
	const width = Math.max(320, Math.floor(containerWidth || 720));
	const compact = width < 720;
	const leftPad = compact ? 52 : 66;
	const rightPad = compact ? 20 : 28;
	const topPad = compact ? 24 : 28;
	const bottomPad = compact ? 54 : 58;
	const height = compact ? 320 : 360;
	const plotWidth = Math.max(160, width - leftPad - rightPad);
	const plotHeight = Math.max(140, height - topPad - bottomPad);
	const xMax = points.reduce((max, point) => Math.max(max, point.x), 0);
	const yMax = points.reduce((max, point) => Math.max(max, point.y), 0);
	const xAxis = buildNumericAxis(xMax, 4);
	const papersTargetValue = yMetric === 'papers'
		? Math.max(
			BASELINE_PAPERS_TARGET,
			points.reduce((max, point) => Math.max(max, Number(point.papersTargetMax || 0)), 0),
		)
		: null;
	const yAxis = yMetric === 'accuracy'
		? { max: 1, values: [0, 0.25, 0.5, 0.75, 1] }
		: buildNumericAxis(Math.max(yMax, Number(papersTargetValue || 0)), 4);
	const xTicks = xAxis.values.map((value) => ({
		value,
		x: leftPad + plotWidth * (xAxis.max ? value / xAxis.max : 0),
		label: formatCurrencyTick(value),
	}));
	const yTicks = yAxis.values.map((value) => ({
		value,
		y: topPad + plotHeight - plotHeight * (yAxis.max ? value / yAxis.max : 0),
		label: yMetric === 'accuracy' ? `${Math.round(value * 100)}%` : formatCompactNumber(value),
	}));
	const projectedPoints = points.map((point) => {
		const xRatio = xAxis.max > 0 ? point.x / xAxis.max : 0;
		const yRatio = yAxis.max > 0 ? point.y / yAxis.max : 0;
		const px = leftPad + plotWidth * xRatio;
		const py = topPad + plotHeight - plotHeight * yRatio;
		return {
			...point,
			px,
			py,
			label: compact ? truncateLabel(point.providerLabel, 14) : truncateLabel(point.providerLabel, 24),
			radius: point.isFrontier ? (compact ? 4.8 : 5.6) : (compact ? 3.8 : 4.4),
		};
	});
	const frontierPoints = projectedPoints
		.filter((point) => point.isFrontier)
		.sort((a, b) => a.x - b.x);
	const targetLineY = yMetric === 'papers' && yAxis.max > 0
		? topPad + plotHeight - plotHeight * (Number(papersTargetValue || 0) / yAxis.max)
		: null;
	return {
		width,
		height,
		compact,
		leftPad,
		topPad,
		plotWidth,
		plotHeight,
		xAxis,
		yAxis,
		xTicks,
		yTicks,
		points: projectedPoints,
		frontierPoints,
		yMetric,
		papersTargetValue,
		targetLineY,
	};
}

function createSvgNode(tagName, attrs = {}) {
	const node = document.createElementNS(SVG_NS, tagName);
	for (const [key, value] of Object.entries(attrs)) {
		node.setAttribute(key, String(value));
	}
	return node;
}

function renderProviderChartSkeleton(container) {
	const skeleton = el('div', 'provider-accuracy-skeleton', '');
	for (let idx = 0; idx < 3; idx += 1) {
		const row = el('div', 'provider-accuracy-skeleton__row', '');
		row.appendChild(el('div', 'provider-accuracy-skeleton__label', ''));
		row.appendChild(el('div', 'provider-accuracy-skeleton__rail', ''));
		skeleton.appendChild(row);
	}
	container.appendChild(skeleton);
}

function renderProviderAccuracySvg(container, model, metric, options = {}) {
	const { animate = false } = options;
	const animatedFills = [];
	const svg = createSvgNode('svg', {
		class: 'provider-accuracy-svg',
		viewBox: `0 0 ${model.width} ${model.height}`,
		role: 'img',
		'aria-label': `${metric.label} by model chart`,
	});
	svg.style.width = '100%';
	svg.style.height = 'auto';

	const defs = createSvgNode('defs');
	const gradient = createSvgNode('linearGradient', {
		id: 'providerAccuracyGradient',
		x1: '0%',
		y1: '0%',
		x2: '100%',
		y2: '0%',
	});
	gradient.appendChild(createSvgNode('stop', { offset: '0%', 'stop-color': '#38bdf8' }));
	gradient.appendChild(createSvgNode('stop', { offset: '100%', 'stop-color': '#f472b6' }));
	defs.appendChild(gradient);
	svg.appendChild(defs);

	const guideTop = model.rows.length ? model.rows[0].yTop - 3 : 18;
	for (const tick of model.ticks) {
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-grid',
				x1: tick.x,
				y1: guideTop,
				x2: tick.x,
				y2: model.axisY,
			}),
		);
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-tick',
				x1: tick.x,
				y1: model.axisY,
				x2: tick.x,
				y2: model.axisY + 6,
			}),
		);
		const tickLabel = createSvgNode('text', {
			class: 'provider-accuracy-tick-label',
			x: tick.x,
			y: model.axisY + 20,
			'text-anchor': 'middle',
		});
		tickLabel.textContent = tick.label;
		svg.appendChild(tickLabel);
	}

	svg.appendChild(
		createSvgNode('line', {
			class: 'provider-accuracy-axis',
			x1: model.leftPad,
			y1: model.axisY,
			x2: model.leftPad + model.plotWidth,
			y2: model.axisY,
		}),
	);

	for (const row of model.rows) {
		const label = createSvgNode('text', {
			class: 'provider-accuracy-label',
			x: 10,
			y: row.yCenter + 4,
		});
		label.textContent = row.providerLabel;
		svg.appendChild(label);

		const meta = createSvgNode('text', {
			class: 'provider-accuracy-meta',
			x: 10,
			y: row.yCenter + 19,
		});
		meta.textContent = row.metaLabel;
		svg.appendChild(meta);

		svg.appendChild(
			createSvgNode('rect', {
				class: 'provider-accuracy-rail',
				x: row.barX,
				y: row.barY,
				width: model.plotWidth,
				height: row.barHeight,
				rx: row.barHeight / 2,
				ry: row.barHeight / 2,
			}),
		);

		const fill = createSvgNode('rect', {
			class: `provider-accuracy-fill${animate ? ' is-animated' : ''}`,
			x: row.barX,
			y: row.barY,
			width: row.barWidth,
			height: row.barHeight,
			rx: row.barHeight / 2,
			ry: row.barHeight / 2,
			fill: 'url(#providerAccuracyGradient)',
		});
		if (animate) {
			fill.style.transform = 'scaleX(0)';
			animatedFills.push(fill);
		}
		svg.appendChild(fill);

		svg.appendChild(
			createSvgNode('circle', {
				class: 'provider-accuracy-marker',
				cx: row.markerX,
				cy: row.yCenter,
				r: model.compact ? 3.5 : 4.5,
			}),
		);

		const value = createSvgNode('text', {
			class: 'provider-accuracy-value',
			x: model.leftPad + model.plotWidth + 8,
			y: row.yCenter + 4,
		});
		value.textContent = row.valueLabel;
		svg.appendChild(value);
	}

	container.appendChild(svg);
	if (animate && animatedFills.length) {
		requestAnimationFrame(() => {
			requestAnimationFrame(() => {
				for (const fill of animatedFills) {
					fill.style.transform = 'scaleX(1)';
				}
			});
		});
	}
}

function renderProviderParetoSvg(container, model) {
	let tooltip = null;
	const showTooltip = (point, anchorRect) => {
		if (!tooltip) return;
		tooltip.innerHTML = '';
		tooltip.appendChild(el('div', 'provider-pareto-tooltip__title', point.providerLabel));
		tooltip.appendChild(el('div', 'provider-pareto-tooltip__line', `Cost: ${formatCurrency(point.x)}`));
		tooltip.appendChild(
			el(
				'div',
				'provider-pareto-tooltip__line',
				model.yMetric === 'accuracy'
					? `Accuracy: ${(point.y * 100).toFixed(1)}%`
					: `Papers Fully Matched: ${formatCount(point.y)}`,
			),
		);
		tooltip.appendChild(el('div', 'provider-pareto-tooltip__line', `Runs: ${formatCount(point.batches)}`));
		tooltip.classList.remove('hidden');
		const bounds = container.getBoundingClientRect();
		const baseLeft = anchorRect.left - bounds.left + (anchorRect.width / 2);
		const left = Math.min(
			Math.max(8, baseLeft + 10),
			Math.max(8, bounds.width - tooltip.offsetWidth - 8),
		);
		let top = anchorRect.top - bounds.top - tooltip.offsetHeight - 10;
		if (top < 8) {
			top = Math.min(bounds.height - tooltip.offsetHeight - 8, anchorRect.bottom - bounds.top + 10);
		}
		tooltip.style.left = `${left}px`;
		tooltip.style.top = `${Math.max(8, top)}px`;
	};
	const hideTooltip = () => {
		if (tooltip) tooltip.classList.add('hidden');
	};

	if (ENABLE_PARETO_POINT_HOVER_TOOLTIP) {
		container.style.position = 'relative';
		tooltip = el('div', 'provider-pareto-tooltip hidden', '');
	}

	const svg = createSvgNode('svg', {
		class: 'provider-accuracy-svg',
		viewBox: `0 0 ${model.width} ${model.height}`,
		role: 'img',
		'aria-label': model.yMetric === 'accuracy'
			? 'Pareto frontier chart for cost versus accuracy'
			: 'Pareto frontier chart for cost versus papers fully matched',
	});
	svg.style.width = '100%';
	svg.style.height = 'auto';

	for (const tick of model.xTicks) {
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-grid',
				x1: tick.x,
				y1: model.topPad,
				x2: tick.x,
				y2: model.topPad + model.plotHeight,
			}),
		);
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-tick',
				x1: tick.x,
				y1: model.topPad + model.plotHeight,
				x2: tick.x,
				y2: model.topPad + model.plotHeight + 6,
			}),
		);
		const tickLabel = createSvgNode('text', {
			class: 'provider-accuracy-tick-label',
			x: tick.x,
			y: model.topPad + model.plotHeight + 20,
			'text-anchor': 'middle',
		});
		tickLabel.textContent = tick.label;
		svg.appendChild(tickLabel);
	}

	for (const tick of model.yTicks) {
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-grid',
				x1: model.leftPad,
				y1: tick.y,
				x2: model.leftPad + model.plotWidth,
				y2: tick.y,
			}),
		);
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-accuracy-tick',
				x1: model.leftPad - 6,
				y1: tick.y,
				x2: model.leftPad,
				y2: tick.y,
			}),
		);
		const tickLabel = createSvgNode('text', {
			class: 'provider-accuracy-tick-label',
			x: model.leftPad - 10,
			y: tick.y + 3,
			'text-anchor': 'end',
		});
		tickLabel.textContent = tick.label;
		svg.appendChild(tickLabel);
	}

	svg.appendChild(
		createSvgNode('line', {
			class: 'provider-accuracy-axis',
			x1: model.leftPad,
			y1: model.topPad + model.plotHeight,
			x2: model.leftPad + model.plotWidth,
			y2: model.topPad + model.plotHeight,
		}),
	);
	svg.appendChild(
		createSvgNode('line', {
			class: 'provider-accuracy-axis',
			x1: model.leftPad,
			y1: model.topPad,
			x2: model.leftPad,
			y2: model.topPad + model.plotHeight,
		}),
	);

	if (model.yMetric === 'papers' && Number.isFinite(model.targetLineY)) {
		svg.appendChild(
			createSvgNode('line', {
				class: 'provider-pareto-target-line',
				x1: model.leftPad,
				y1: model.targetLineY,
				x2: model.leftPad + model.plotWidth,
				y2: model.targetLineY,
			}),
		);
		const targetLabel = createSvgNode('text', {
			class: 'provider-pareto-target-label',
			x: model.leftPad + model.plotWidth - 2,
			y: model.targetLineY - 6,
			'text-anchor': 'end',
		});
		targetLabel.textContent = 'Max score';
		svg.appendChild(targetLabel);
	}

	if (model.frontierPoints.length > 1) {
		const pathSegments = model.frontierPoints.map((point, index) =>
			`${index === 0 ? 'M' : 'L'} ${point.px.toFixed(2)} ${point.py.toFixed(2)}`,
		);
		svg.appendChild(
			createSvgNode('path', {
				class: 'provider-pareto-frontier',
				d: pathSegments.join(' '),
			}),
		);
	}

	for (const point of model.points) {
		const dot = createSvgNode('circle', {
			class: point.isFrontier ? 'provider-pareto-point is-frontier' : 'provider-pareto-point',
			cx: point.px,
			cy: point.py,
			r: point.radius,
		});
		const title = createSvgNode('title');
		title.textContent = model.yMetric === 'accuracy'
			? `${point.providerLabel}: ${formatCurrency(point.x)} cost, ${(point.y * 100).toFixed(1)}% accuracy`
			: `${point.providerLabel}: ${formatCurrency(point.x)} cost, ${formatCount(point.y)} papers`;
		dot.appendChild(title);
		if (ENABLE_PARETO_POINT_HOVER_TOOLTIP) {
			dot.setAttribute('tabindex', '0');
			dot.addEventListener('mouseenter', () => showTooltip(point, dot.getBoundingClientRect()));
			dot.addEventListener('mouseleave', hideTooltip);
			dot.addEventListener('focus', () => showTooltip(point, dot.getBoundingClientRect()));
			dot.addEventListener('blur', hideTooltip);
		}
		svg.appendChild(dot);

		const text = createSvgNode('text', {
			class: point.isFrontier ? 'provider-pareto-label is-frontier' : 'provider-pareto-label',
			x: point.px + 7,
			y: point.py - 7,
		});
		text.textContent = point.label;
		svg.appendChild(text);
	}

	const xAxisLabel = createSvgNode('text', {
		class: 'provider-accuracy-meta',
		x: model.leftPad + model.plotWidth / 2,
		y: model.height - 10,
		'text-anchor': 'middle',
	});
	xAxisLabel.textContent = 'Cost (USD)';
	svg.appendChild(xAxisLabel);

	const yAxisLabel = createSvgNode('text', {
		class: 'provider-accuracy-meta',
		x: 16,
		y: model.topPad + model.plotHeight / 2,
		'text-anchor': 'middle',
		transform: `rotate(-90 16 ${model.topPad + model.plotHeight / 2})`,
	});
	yAxisLabel.textContent = model.yMetric === 'accuracy' ? 'Accuracy' : 'Papers Fully Matched';
	svg.appendChild(yAxisLabel);

	container.appendChild(svg);
	if (tooltip) {
		container.appendChild(tooltip);
		svg.addEventListener('mouseleave', hideTooltip);
	}
}

function renderProviderAccuracyChart() {
	const container = $('#providerAccuracyChart');
	const plotMount = $('#providerAccuracyPlot');
	const metric = getMetricConfig(state.providerChartMetric);
	if (!container || !plotMount) return;
	plotMount.innerHTML = '';

	const isLoading = state.providerChartState === 'loading';
	const isError = state.providerChartState === 'error';
	if (isLoading && !state.batches.length) {
		renderProviderChartSkeleton(plotMount);
		return;
	}

	const finishedBatches = selectFinishedBatches(state.batches, {
		completeOnly: state.providerChartCompleteOnly,
	});
	if (metric.id === 'pareto_frontier' || metric.id === 'pareto_frontier_accuracy') {
		const yMetric = metric.id === 'pareto_frontier_accuracy' ? 'accuracy' : 'papers';
		const points = computeParetoFrontierRows(finishedBatches, yMetric);
		if (!points.length) {
			plotMount.appendChild(
				el(
					'div',
					'sw-empty text-xs text-slate-500',
						state.batches.length
							? (yMetric === 'accuracy'
								? (state.providerChartCompleteOnly
									? 'No fully extracted runs have enough cost and accuracy data yet.'
									: 'Pareto frontier needs runs with both cost and accuracy data.')
								: (state.providerChartCompleteOnly
									? 'No fully extracted runs have enough cost and papers-fully-matched data yet.'
									: 'Pareto frontier needs runs with both cost and papers-fully-matched data.'))
							: 'No runs available yet. Start a run to populate analytics.',
				),
			);
			return;
		}
		const model = buildProviderParetoModel(points, plotMount.clientWidth || container.clientWidth || 720, yMetric);
		renderProviderParetoSvg(plotMount, model);
		state.providerChartHasAnimated = true;
		return;
	}

	const { rows } = computeProviderMetricRows(finishedBatches, metric);
	const papersAllMatchedMissing =
		metric.id === 'papers_all_matched' &&
		finishedBatches.length > 0 &&
		finishedBatches.every((batch) => !Number.isFinite(Number(batch.papers_all_matched)));

	if (!rows.length) {
		plotMount.appendChild(
			el(
				'div',
				'sw-empty text-xs text-slate-500',
						papersAllMatchedMissing
							? 'Metric unavailable from the current API payload.'
							: state.batches.length
								? (state.providerChartCompleteOnly
									? 'No fully extracted runs match this filter yet.'
									: 'No models have enough data for this metric yet.')
								: 'No runs available yet. Start a run to populate analytics.',
				),
			);
			return;
	}

	const model = buildProviderChartModel(rows, metric, plotMount.clientWidth || container.clientWidth || 720);
	const prefersReducedMotion =
		typeof window !== 'undefined' &&
		typeof window.matchMedia === 'function' &&
		window.matchMedia('(prefers-reduced-motion: reduce)').matches;
	const shouldAnimate = !state.providerChartHasAnimated && !prefersReducedMotion;

	renderProviderAccuracySvg(plotMount, model, metric, { animate: shouldAnimate });
	state.providerChartHasAnimated = true;
}

function queueProviderChartRerender() {
	if (chartResizeTimer) clearTimeout(chartResizeTimer);
	chartResizeTimer = setTimeout(() => {
		chartResizeTimer = null;
		renderProviderAccuracyChart();
	}, 120);
}

function getCardStatusColor(status) {
	return STATUS_COLORS[status] || 'border-slate-400';
}

function getCardStatusChipClass(status) {
	if (status === 'running') return 'sw-chip--processing';
	if (status === 'completed') return 'sw-chip--success';
	if (status === 'partial') return 'sw-chip--warning';
	return 'sw-chip--error';
}

function getCardProgressFillClass(status) {
	if (status === 'running') return 'bg-cyan-400';
	if (status === 'completed') return 'bg-emerald-400';
	if (status === 'partial') return 'bg-amber-400';
	return 'bg-rose-400';
}

function applyBatchCardShellClass(card, batch) {
	card.className = `sw-card p-4 min-h-[235px] hover:shadow-lg transition-shadow border-l-4 ${getCardStatusColor(batch.status)}`;
}

function renderRetryButton(slot, batch) {
	if (!slot) return;
	slot.innerHTML = '';
	if (batch.failed <= 0 || batch.status === 'running') return;
	const retryBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost text-[10px]');
	retryBtn.innerHTML = `<span class="sw-btn__label">Retry ${batch.failed}</span>`;
	retryBtn.title = `Retry ${batch.failed} failed runs`;
	retryBtn.addEventListener('click', async (e) => {
		e.preventDefault();
		e.stopPropagation();
		await retryBatchFailed(batch.batch_id, retryBtn);
	});
	slot.appendChild(retryBtn);
}

function renderStopButton(slot, batch) {
	if (!slot) return;
	slot.innerHTML = '';
	if (batch.status !== 'running') return;
	const stopBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost text-[10px] text-amber-600 hover:text-amber-700');
	stopBtn.innerHTML = '<span class="sw-btn__label">Stop</span>';
	stopBtn.title = 'Stop all in-progress requests for this run';
	stopBtn.addEventListener('click', async (e) => {
		e.preventDefault();
		e.stopPropagation();
		await stopBatchRun(batch.batch_id, batch.label || batch.batch_id, stopBtn);
	});
	slot.appendChild(stopBtn);
}

function patchBatchCardElement(card, batch) {
	if (!card) return;
	card.dataset.batchId = batch.batch_id;
	applyBatchCardShellClass(card, batch);

	const statusLabel = STATUS_LABELS[batch.status] || batch.status;
	const progress = getProgressPercent(batch);

	const titleLink = card.querySelector('[data-role="title-link"]');
	if (titleLink) {
		titleLink.textContent = batch.label || batch.batch_id;
		titleLink.title = batch.batch_id;
		titleLink.href = buildBatchDetailHref(batch.batch_id);
	}

	const statusBadge = card.querySelector('[data-role="status-badge"]');
	if (statusBadge) {
		statusBadge.className = `sw-chip text-[10px] ${getCardStatusChipClass(batch.status)}`;
		statusBadge.textContent = statusLabel;
	}

	const progressFill = card.querySelector('[data-role="progress-fill"]');
	if (progressFill) {
		progressFill.className = `h-full transition-all duration-300 ${getCardProgressFillClass(batch.status)}`;
		progressFill.style.width = `${progress}%`;
	}

	const completedText = card.querySelector('[data-role="progress-completed"]');
	if (completedText) {
		completedText.textContent = `${batch.completed}/${batch.total_papers} completed`;
	}

	const failedText = card.querySelector('[data-role="progress-failed"]');
	if (failedText) {
		failedText.textContent = batch.failed > 0 ? `${batch.failed} failed` : '';
		failedText.classList.toggle('invisible', batch.failed <= 0);
	}

	const setStatValue = (role, text, highlight = false) => {
		const node = card.querySelector(`[data-role="${role}"]`);
		if (!node) return;
		node.className = highlight ? 'text-emerald-600 font-medium' : 'text-slate-700';
		node.textContent = text;
	};
	setStatValue('stat-match-rate', formatMatchRate(batch), batch.matched_entities > 0);
	setStatValue('stat-cost', formatCost(batch));
	setStatValue('stat-time', formatDuration(batch.total_time_ms));
	setStatValue('stat-input', `${formatTokens(batch.total_input_tokens)}`);
	setStatValue('stat-output', `${formatTokens(batch.total_output_tokens)}`);
	setStatValue('stat-model', batch.model_name || batch.model_provider);

	const createdAt = card.querySelector('[data-role="created-at"]');
	if (createdAt) {
		createdAt.textContent = formatDate(batch.created_at);
	}

	const retrySlot = card.querySelector('[data-role="retry-slot"]');
	renderRetryButton(retrySlot, batch);
	const stopSlot = card.querySelector('[data-role="stop-slot"]');
	renderStopButton(stopSlot, batch);
}

function renderBatchCard(batch) {
	const progress = getProgressPercent(batch);
	const statusLabel = STATUS_LABELS[batch.status] || batch.status;

	const card = el('div', '');
	card.dataset.batchId = batch.batch_id;
	applyBatchCardShellClass(card, batch);

	// Header row: name/id + status badge
	const header = el('div', 'flex items-center justify-between mb-3');
	const titleLink = el('a', 'font-semibold text-sm truncate flex-1 mr-2 hover:text-cyan-500 cursor-pointer', batch.label || batch.batch_id);
	titleLink.dataset.role = 'title-link';
	titleLink.title = batch.batch_id;
	titleLink.href = buildBatchDetailHref(batch.batch_id);

	const statusBadge = el('span', `sw-chip text-[10px] ${getCardStatusChipClass(batch.status)}`, statusLabel);
	statusBadge.dataset.role = 'status-badge';

	header.appendChild(titleLink);
	header.appendChild(statusBadge);
	card.appendChild(header);

	// Progress bar
	const progressWrapper = el('div', 'mb-3');
	const progressBar = el('div', 'h-2 bg-slate-200 rounded-full overflow-hidden');
	const progressFill = el('div', `h-full transition-all duration-300 ${getCardProgressFillClass(batch.status)}`);
	progressFill.dataset.role = 'progress-fill';
	progressFill.style.width = `${progress}%`;
	progressBar.appendChild(progressFill);
	progressWrapper.appendChild(progressBar);

	const progressText = el('div', 'flex justify-between text-[10px] text-slate-500 mt-1');
	const completedSpan = el('span', '', `${batch.completed}/${batch.total_papers} completed`);
	completedSpan.dataset.role = 'progress-completed';
	const failedSpan = el('span', `text-rose-500 ${batch.failed > 0 ? '' : 'invisible'}`, batch.failed > 0 ? `${batch.failed} failed` : '');
	failedSpan.dataset.role = 'progress-failed';
	progressText.appendChild(completedSpan);
	progressText.appendChild(failedSpan);
	progressWrapper.appendChild(progressText);
	card.appendChild(progressWrapper);

	// Stats grid - 3 columns for more info
	const statsGrid = el('div', 'grid grid-cols-3 gap-2 text-[11px]');

	const addStat = (label, value, highlight = false, role = '') => {
		const stat = el('div', 'flex flex-col');
		stat.appendChild(el('span', 'sw-kicker text-[10px] text-slate-400', label));
		const valueNode = el('span', highlight ? 'text-emerald-600 font-medium' : 'text-slate-700', value);
		if (role) valueNode.dataset.role = role;
		stat.appendChild(valueNode);
		statsGrid.appendChild(stat);
	};

	addStat('Match Rate', formatMatchRate(batch), batch.matched_entities > 0, 'stat-match-rate');
	addStat('Cost', formatCost(batch), false, 'stat-cost');
	addStat('Time', formatDuration(batch.total_time_ms), false, 'stat-time');
	addStat('Input', `${formatTokens(batch.total_input_tokens)}`, false, 'stat-input');
	addStat('Output', `${formatTokens(batch.total_output_tokens)}`, false, 'stat-output');
	addStat('Model', batch.model_name || batch.model_provider, false, 'stat-model');

	card.appendChild(statsGrid);

	// Action buttons row
	const actionsRow = el('div', 'flex items-center justify-between mt-3 pt-3 border-t border-slate-200');

	const leftActions = el('div', 'flex items-center gap-2');
	const stopSlot = el('div', 'flex items-center gap-2');
	stopSlot.dataset.role = 'stop-slot';
	leftActions.appendChild(stopSlot);
	renderStopButton(stopSlot, batch);
	const retrySlot = el('div', 'flex items-center gap-2');
	retrySlot.dataset.role = 'retry-slot';
	leftActions.appendChild(retrySlot);
	renderRetryButton(retrySlot, batch);

	// Delete button
	const deleteBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost text-[10px] text-rose-500 hover:text-rose-600');
	deleteBtn.innerHTML = '<span class="sw-btn__label">Delete</span>';
	deleteBtn.title = 'Delete this run';
	deleteBtn.addEventListener('click', async (e) => {
		e.preventDefault();
		e.stopPropagation();
		await deleteBatch(batch.batch_id, batch.label || batch.batch_id);
	});
	leftActions.appendChild(deleteBtn);

	actionsRow.appendChild(leftActions);

	// Date on the right
	const dateNode = el('span', 'text-[10px] text-slate-500', formatDate(batch.created_at));
	dateNode.dataset.role = 'created-at';
	actionsRow.appendChild(dateNode);

	card.appendChild(actionsRow);

	return card;
}

function renderBatchGrid() {
	const grid = $('#batchGrid');
	const emptyState = $('#emptyState');
	const countEl = $('#batchCount');

	if (!grid) return;

	grid.innerHTML = '';

	if (!state.batches.length) {
		grid.classList.add('hidden');
		emptyState?.classList.remove('hidden');
		if (countEl) countEl.textContent = '0 runs';
		renderProviderAccuracyChart();
		return;
	}

	grid.classList.remove('hidden');
	emptyState?.classList.add('hidden');
	if (countEl) countEl.textContent = `${state.batches.length} run${state.batches.length !== 1 ? 's' : ''}`;

	// Sort by created_at descending (newest first)
	const sorted = [...state.batches].sort((a, b) => {
		const dateA = new Date(a.created_at || 0);
		const dateB = new Date(b.created_at || 0);
		return dateB - dateA;
	});

	for (const batch of sorted) {
		grid.appendChild(renderBatchCard(batch));
	}
	renderProviderAccuracyChart();
}

function updateBatchCard(batchId, updates) {
	const batch = state.batches.find(b => b.batch_id === batchId);
	if (!batch) return;

	Object.assign(batch, updates);

	// Patch just that card in place (avoid scroll jumps from replacing nodes).
	const existingCard = document.querySelector(`[data-batch-id="${batchId}"]`);
	if (existingCard) {
		patchBatchCardElement(existingCard, batch);
	}
}

async function loadBatches() {
	try {
		updateStatus('Loading evaluation runs...');
		if (!state.batches.length) {
			state.providerChartState = 'loading';
			state.providerChartError = '';
			renderProviderAccuracyChart();
		}
		const response = await api.get(getBatchesEndpoint());
		state.batches = response.batches || [];
		state.providerChartState = 'ready';
		state.providerChartError = '';
		renderBatchGrid();
		updateStatus('');
	} catch (err) {
		console.error('Failed to load batches:', err);
		state.providerChartState = 'error';
		state.providerChartError = err?.message || 'Failed to load model analytics';
		renderProviderAccuracyChart();
		updateStatus(`Error: ${err.message}`);
	}
}

async function loadPrompts() {
	try {
		const response = await api.getPrompts();
		state.prompts = response.prompts || [];
		state.activePromptId = response.active_prompt_id;
		renderPromptOptions();
	} catch (err) {
		console.error('Failed to load prompts:', err);
	}
}

function renderPromptOptions() {
	const select = $('#batchPrompt');
	if (!select) return;

	select.innerHTML = '';

	const defaultOpt = el('option', '', 'Default (active prompt)');
	defaultOpt.value = '';
	select.appendChild(defaultOpt);

	for (const prompt of state.prompts) {
		const opt = el('option', '', prompt.name + (prompt.is_active ? ' (active)' : ''));
		opt.value = String(prompt.id);
		select.appendChild(opt);
	}
}

function updateStatus(message) {
	const statusEl = $('#statusMessage');
	if (statusEl) statusEl.textContent = message || '';
}

function createEmptyGroundTruthEntity() {
	return { sequence: '', n_terminal: '', c_terminal: '', labels_csv: '', notes: '' };
}

function groupCasesByPaper(cases) {
	const grouped = new Map();
	for (const caseItem of cases || []) {
		const key = (caseItem.paper_key || caseItem.id || '').toString();
		if (!grouped.has(key)) {
			const metadataTitle = caseItem?.metadata?.title;
			grouped.set(key, { key, title: metadataTitle || caseItem.title || key, cases: [] });
		}
		grouped.get(key).cases.push(caseItem);
	}
	return Array.from(grouped.values()).sort((a, b) => a.title.localeCompare(b.title));
}

function getEvalBuilderPaperGroups() {
	const datasetId = state.evalBuilder.selectedDatasetId;
	if (!datasetId) return [];
	return groupCasesByPaper(state.cases.filter((item) => item.dataset === datasetId));
}

function getEvalBuilderDatasetStats() {
	const paperKeysByDataset = new Map();
	for (const caseItem of state.cases || []) {
		const datasetId = (caseItem.dataset || '').toString().trim();
		if (!datasetId) continue;
		if (!paperKeysByDataset.has(datasetId)) {
			paperKeysByDataset.set(datasetId, new Set());
		}
		const key = (caseItem.paper_key || caseItem.id || '').toString().trim();
		if (key) {
			paperKeysByDataset.get(datasetId).add(key);
		}
	}

	return (state.datasets || []).map((dataset) => ({
		...dataset,
		paperCount: (paperKeysByDataset.get(dataset.id) || new Set()).size,
	}));
}

function getEvalBuilderVisibleDatasets() {
	const withStats = getEvalBuilderDatasetStats();
	if (!withStats.length) return [];
	const primary = withStats.find((dataset) => dataset.id === EVAL_BUILDER_PRIMARY_DATASET_ID)
		|| withStats.find((dataset) => dataset.paperCount === EVAL_BUILDER_PRIMARY_PAPER_COUNT)
		|| null;
	const custom = withStats.filter((dataset) => dataset.source_file === 'eval_builder');
	if (primary) {
		return [primary, ...custom.filter((dataset) => dataset.id !== primary.id)];
	}
	if (custom.length) return custom;
	return [withStats[0]];
}

function getSelectedPaperGroup() {
	if (!state.evalBuilder.selectedPaperKey) return null;
	return getEvalBuilderPaperGroups().find((group) => group.key === state.evalBuilder.selectedPaperKey) || null;
}

function setEvalBuilderOpen(isOpen) {
	const modal = $('#evalBuilderModal');
	if (!modal) return;
	state.evalBuilder.open = Boolean(isOpen);
	modal.classList.toggle('hidden', !isOpen);
}

function setEvalBuilderStatus(message) {
	const node = $('#evalBuilderStatus');
	if (node) node.textContent = message || '';
}

function setEvalBuilderError(message) {
	const node = $('#evalBuilderError');
	if (!node) return;
	if (message) {
		node.textContent = message;
		node.classList.remove('hidden');
		return;
	}
	node.textContent = '';
	node.classList.add('hidden');
}

function setEvalBuilderBusy(isBusy) {
	state.evalBuilder.busy = Boolean(isBusy);
	[
		'#evalBuilderNewGroupBtn',
		'#evalBuilderNewPaperBtn',
		'#evalBuilderDeleteGroupBtn',
		'#evalBuilderDeletePaperBtn',
		'#evalBuilderCreateGroupBtn',
		'#evalBuilderSavePaperBtn',
	].forEach((selector) => {
		const node = $(selector);
		if (node) node.disabled = state.evalBuilder.busy;
	});
}

function prefillEvalBuilderGroupDraft(dataset) {
	state.evalBuilder.draftGroup = {
		id: dataset?.id || '',
		label: dataset?.label || dataset?.id || '',
		description: dataset?.description || '',
	};
}

function prefillEvalBuilderPaperDraft(paperGroup) {
	const firstCase = paperGroup?.cases?.[0] || null;
	state.evalBuilder.draftPaper = {
		title: firstCase?.title || '',
		doi: firstCase?.doi || '',
		paper_url: firstCase?.paper_url || '',
		main_pdf_file: null,
		supporting_pdf_files: [],
	};
	const mappedEntities = (paperGroup?.cases || []).map((caseItem) => ({
		sequence: caseItem.sequence || '',
		n_terminal: caseItem.n_terminal || '',
		c_terminal: caseItem.c_terminal || '',
		labels_csv: Array.isArray(caseItem.labels) ? caseItem.labels.join(', ') : '',
		notes: caseItem.notes || '',
	}));
	state.evalBuilder.draftGroundTruthEntities = mappedEntities.length ? mappedEntities : [createEmptyGroundTruthEntity()];
}

function resetEvalBuilderPaperDraft() {
	state.evalBuilder.draftPaper = {
		title: '',
		doi: '',
		paper_url: '',
		main_pdf_file: null,
		supporting_pdf_files: [],
	};
	state.evalBuilder.draftGroundTruthEntities = [createEmptyGroundTruthEntity()];
}

function renderEvalBuilderForm() {
	const modeNode = $('#evalBuilderMode');
	if (modeNode) modeNode.textContent = `Mode: ${state.evalBuilder.mode}`;

	const groupId = $('#evalBuilderGroupId');
	const groupLabel = $('#evalBuilderGroupLabel');
	const groupDescription = $('#evalBuilderGroupDescription');
	if (groupId) groupId.value = state.evalBuilder.draftGroup.id || '';
	if (groupLabel) groupLabel.value = state.evalBuilder.draftGroup.label || '';
	if (groupDescription) groupDescription.value = state.evalBuilder.draftGroup.description || '';

	const paperTitle = $('#evalBuilderPaperTitle');
	const paperDoi = $('#evalBuilderPaperDoi');
	const paperUrl = $('#evalBuilderPaperUrl');
	if (paperTitle) paperTitle.value = state.evalBuilder.draftPaper.title || '';
	if (paperDoi) paperDoi.value = state.evalBuilder.draftPaper.doi || '';
	if (paperUrl) paperUrl.value = state.evalBuilder.draftPaper.paper_url || '';

	const mainPdf = $('#evalBuilderMainPdf');
	const supporting = $('#evalBuilderSupportingPdfs');
	if (mainPdf) mainPdf.value = '';
	if (supporting) supporting.value = '';

	const container = $('#evalBuilderGroundTruthList');
	if (!container) return;
	container.innerHTML = '';
	const entities = state.evalBuilder.draftGroundTruthEntities || [];
	entities.forEach((entity, index) => {
		const row = el('div', 'sw-card p-2 space-y-2');
		row.appendChild(el('div', 'sw-kicker text-[10px] text-slate-500', `Entity ${index + 1}`));
		const fields = [
			{ key: 'sequence', label: 'Sequence', required: true },
			{ key: 'n_terminal', label: 'N-terminal' },
			{ key: 'c_terminal', label: 'C-terminal' },
			{ key: 'labels_csv', label: 'Labels (comma-separated)' },
			{ key: 'notes', label: 'Notes' },
		];
		fields.forEach((field) => {
			const wrapper = el('div', 'space-y-1');
			const labelNode = el('label', 'sw-kicker text-[10px] text-slate-500 block', field.label + (field.required ? ' *' : ''));
			const input = field.key === 'notes' ? document.createElement('textarea') : document.createElement('input');
			input.className = 'sw-input sw-input--sm';
			input.value = entity[field.key] || '';
			input.dataset.action = 'gt-input';
			input.dataset.index = String(index);
			input.dataset.field = field.key;
			wrapper.appendChild(labelNode);
			wrapper.appendChild(input);
			row.appendChild(wrapper);
		});
		const removeBtn = el('button', 'sw-btn sw-btn--sm sw-btn--ghost text-red-600', 'Remove');
		removeBtn.type = 'button';
		removeBtn.dataset.action = 'remove-gt-entity';
		removeBtn.dataset.index = String(index);
		row.appendChild(removeBtn);
		container.appendChild(row);
	});
}

function renderEvalBuilderGroupsList() {
	const container = $('#evalBuilderGroupsList');
	if (!container) return;
	container.innerHTML = '';
	const visibleDatasets = getEvalBuilderVisibleDatasets();
	if (!visibleDatasets.length) {
		container.appendChild(el('div', 'text-xs text-slate-500', 'No datasets available.'));
		return;
	}
	visibleDatasets.forEach((dataset) => {
		const selected = dataset.id === state.evalBuilder.selectedDatasetId;
		const row = el('button', `w-full text-left sw-card p-2 ${selected ? 'ring-2 ring-cyan-400' : ''}`);
		row.type = 'button';
		row.dataset.action = 'select-group';
		row.dataset.datasetId = dataset.id;
		row.appendChild(el('div', 'text-xs font-semibold text-slate-800 break-words', dataset.label || dataset.id));
		row.appendChild(el('div', 'text-[11px] text-slate-500 break-words', dataset.id));
		row.appendChild(el('div', 'text-[11px] text-slate-500', `${dataset.paperCount || 0} papers`));
		container.appendChild(row);
	});
}

function renderEvalBuilderPapersList() {
	const container = $('#evalBuilderPapersList');
	if (!container) return;
	container.innerHTML = '';
	const groups = getEvalBuilderPaperGroups();
	if (!groups.length) {
		container.appendChild(el('div', 'text-xs text-slate-500', 'No papers in selected group.'));
		return;
	}
	groups.forEach((paperGroup) => {
		const selected = paperGroup.key === state.evalBuilder.selectedPaperKey;
		const row = el('button', `w-full text-left sw-card p-2 ${selected ? 'ring-2 ring-cyan-400' : ''}`);
		row.type = 'button';
		row.dataset.action = 'select-paper';
		row.dataset.paperKey = paperGroup.key;
		row.appendChild(el('div', 'text-xs font-semibold text-slate-800 break-words', paperGroup.title || paperGroup.key));
		row.appendChild(el('div', 'text-[11px] text-slate-500 break-words', paperGroup.key));
		row.appendChild(el('div', 'text-[11px] text-slate-500', `${paperGroup.cases.length} entities`));
		container.appendChild(row);
	});
}

function renderEvalBuilder() {
	if (!state.evalBuilder.open) return;
	renderEvalBuilderGroupsList();
	renderEvalBuilderPapersList();
	renderEvalBuilderForm();
}

let evalBuilderLoadPromise = null;

async function loadEvalBuilderData(force = false) {
	if (state.evalBuilder.loaded && !force) return;
	if (evalBuilderLoadPromise && !force) return evalBuilderLoadPromise;
	evalBuilderLoadPromise = (async () => {
	const payload = await api.get('/api/baseline/cases?include_latest=false');
	state.cases = payload.cases || [];
	state.datasets = payload.datasets || [];
	state.evalBuilder.loaded = true;
	const visibleDatasets = getEvalBuilderVisibleDatasets();
	const visibleIds = new Set(visibleDatasets.map((dataset) => dataset.id));
	if (!state.evalBuilder.selectedDatasetId || !visibleIds.has(state.evalBuilder.selectedDatasetId)) {
		state.evalBuilder.selectedDatasetId = visibleDatasets[0]?.id || null;
	}
	})();
	try {
		await evalBuilderLoadPromise;
	} finally {
		evalBuilderLoadPromise = null;
	}
}

function openEvalBuilderModal() {
	setEvalBuilderError('');
	setEvalBuilderOpen(true);
	setEvalBuilderStatus(state.evalBuilder.loaded ? 'Evaluation group builder ready.' : 'Loading evaluation datasets...');
	renderEvalBuilder();
	void loadEvalBuilderData(false)
		.then(() => {
			if (state.evalBuilder.selectedDatasetId) {
				const selectedDataset = getEvalBuilderVisibleDatasets().find((item) => item.id === state.evalBuilder.selectedDatasetId)
					|| state.datasets.find((item) => item.id === state.evalBuilder.selectedDatasetId);
				if (state.evalBuilder.mode !== 'create_group') {
					state.evalBuilder.mode = 'edit_group';
					prefillEvalBuilderGroupDraft(selectedDataset);
				}
			}
			renderEvalBuilder();
			setEvalBuilderStatus('Evaluation group builder ready.');
		})
		.catch((err) => {
			console.error('Failed to load evaluation builder data:', err);
			setEvalBuilderError(err?.message || 'Failed to load evaluation builder data.');
		});
}

function closeEvalBuilderModal() {
	setEvalBuilderOpen(false);
	setEvalBuilderError('');
	setEvalBuilderStatus('');
}

function selectEvalBuilderGroup(datasetId) {
	state.evalBuilder.selectedDatasetId = datasetId || null;
	state.evalBuilder.selectedPaperKey = null;
	state.evalBuilder.mode = 'edit_group';
	const selectedDataset = getEvalBuilderVisibleDatasets().find((item) => item.id === state.evalBuilder.selectedDatasetId)
		|| state.datasets.find((item) => item.id === state.evalBuilder.selectedDatasetId);
	prefillEvalBuilderGroupDraft(selectedDataset);
	resetEvalBuilderPaperDraft();
	renderEvalBuilder();
	setEvalBuilderStatus('Editing existing group draft.');
}

function selectEvalBuilderPaper(paperKey) {
	state.evalBuilder.selectedPaperKey = paperKey || null;
	state.evalBuilder.mode = 'edit_paper';
	const paperGroup = getSelectedPaperGroup();
	prefillEvalBuilderPaperDraft(paperGroup);
	renderEvalBuilder();
}

function startEvalBuilderCreateGroupMode() {
	state.evalBuilder.mode = 'create_group';
	state.evalBuilder.selectedPaperKey = null;
	state.evalBuilder.draftGroup = {
		id: '',
		label: '',
		description: '',
	};
	renderEvalBuilder();
	setEvalBuilderError('');
	setEvalBuilderStatus('Create-group mode active.');
}

function startEvalBuilderCreatePaperMode() {
	state.evalBuilder.mode = 'create_paper';
	state.evalBuilder.selectedPaperKey = null;
	resetEvalBuilderPaperDraft();
	renderEvalBuilder();
}

function syncEvalBuilderDraftFromInputs() {
	const groupId = $('#evalBuilderGroupId');
	const groupLabel = $('#evalBuilderGroupLabel');
	const groupDescription = $('#evalBuilderGroupDescription');
	const paperTitle = $('#evalBuilderPaperTitle');
	const paperDoi = $('#evalBuilderPaperDoi');
	const paperUrl = $('#evalBuilderPaperUrl');
	state.evalBuilder.draftGroup = {
		id: groupId?.value?.trim() || '',
		label: groupLabel?.value?.trim() || '',
		description: groupDescription?.value?.trim() || '',
	};
	state.evalBuilder.draftPaper = {
		...state.evalBuilder.draftPaper,
		title: paperTitle?.value?.trim() || '',
		doi: paperDoi?.value?.trim() || '',
		paper_url: paperUrl?.value?.trim() || '',
	};
}

async function handleEvalBuilderCreateGroup() {
	syncEvalBuilderDraftFromInputs();
	const validation = validateGroupDraft(state.evalBuilder.draftGroup);
	if (!validation.ok) {
		setEvalBuilderError(validation.errors.join(' '));
		return;
	}
	const payload = buildGroupPayload(state.evalBuilder.draftGroup);
	setEvalBuilderBusy(true);
	setEvalBuilderError('');
	try {
		const response = await submitCreateGroupMock(payload);
		await loadEvalBuilderData(true);
		await loadDatasetOptions();
		state.evalBuilder.selectedDatasetId = response?.id || payload.dataset_id;
		if (state.evalBuilder.selectedDatasetId) {
			state.selectedDataset = state.evalBuilder.selectedDatasetId;
			persistDatasetFilter(state.selectedDataset);
			renderDatasetFilterOptions();
			await loadBatches();
		}
		state.evalBuilder.mode = 'edit_group';
		prefillEvalBuilderGroupDraft(
			state.datasets.find((item) => item.id === state.evalBuilder.selectedDatasetId),
		);
		renderEvalBuilder();
		setEvalBuilderStatus('Group saved.');
	} catch (err) {
		setEvalBuilderError(err?.message || 'Create group failed.');
	} finally {
		setEvalBuilderBusy(false);
	}
}

function buildPaperDraftForValidation() {
	syncEvalBuilderDraftFromInputs();
	return {
		mode: state.evalBuilder.mode,
		selected_dataset_id: state.evalBuilder.selectedDatasetId,
		selected_paper_key: state.evalBuilder.selectedPaperKey,
		title: state.evalBuilder.draftPaper.title,
		doi: state.evalBuilder.draftPaper.doi,
		paper_url: state.evalBuilder.draftPaper.paper_url,
		main_pdf_file: state.evalBuilder.draftPaper.main_pdf_file,
		supporting_pdf_files: state.evalBuilder.draftPaper.supporting_pdf_files,
		ground_truth_entities: state.evalBuilder.draftGroundTruthEntities,
	};
}

async function handleEvalBuilderSavePaper() {
	const draft = buildPaperDraftForValidation();
	const validation = validatePaperDraft(draft);
	if (!validation.ok) {
		setEvalBuilderError(validation.errors.join(' '));
		return;
	}
	const payload = buildPaperPayload(draft);
	setEvalBuilderBusy(true);
	setEvalBuilderError('');
	try {
		const response = await submitSavePaperMock(payload);
		await loadEvalBuilderData(true);
		await loadDatasetOptions();
		if (response?.dataset_id) {
			state.evalBuilder.selectedDatasetId = response.dataset_id;
			if (state.selectedDataset !== response.dataset_id) {
				state.selectedDataset = response.dataset_id;
				persistDatasetFilter(state.selectedDataset);
				renderDatasetFilterOptions();
				await loadBatches();
			}
		}
		if (response?.paper_key) {
			state.evalBuilder.selectedPaperKey = response.paper_key;
		}
		state.evalBuilder.mode = 'edit_paper';
		renderEvalBuilder();
		setEvalBuilderStatus(`Paper saved (${response?.saved_cases || 0} entities).`);
	} catch (err) {
		setEvalBuilderError(err?.message || 'Save paper failed.');
	} finally {
		setEvalBuilderBusy(false);
	}
}

async function handleEvalBuilderDeleteGroup() {
	const datasetId = state.evalBuilder.selectedDatasetId;
	if (!datasetId) {
		setEvalBuilderError('Select a group first.');
		return;
	}
	const confirmed = window.confirm(`Delete group "${datasetId}"?`);
	if (!confirmed) return;
	setEvalBuilderBusy(true);
	setEvalBuilderError('');
	try {
		const response = await submitDeleteGroupMock({ dataset_id: datasetId });
		await loadEvalBuilderData(true);
		await loadDatasetOptions();
		const visible = getEvalBuilderVisibleDatasets();
		state.evalBuilder.selectedDatasetId = visible[0]?.id || null;
		if (state.selectedDataset === datasetId) {
			state.selectedDataset = state.datasetOptions[0]?.id || '';
			persistDatasetFilter(state.selectedDataset);
			renderDatasetFilterOptions();
			await loadBatches();
		}
		state.evalBuilder.selectedPaperKey = null;
		state.evalBuilder.mode = 'edit_group';
		renderEvalBuilder();
		setEvalBuilderStatus(`Group deleted (${response?.deleted_cases || 0} cases removed).`);
	} catch (err) {
		setEvalBuilderError(err?.message || 'Delete group failed.');
	} finally {
		setEvalBuilderBusy(false);
	}
}

async function handleEvalBuilderDeletePaper() {
	const paperGroup = getSelectedPaperGroup();
	if (!paperGroup) {
		setEvalBuilderError('Select a paper first.');
		return;
	}
	const confirmed = window.confirm(`Delete paper "${paperGroup.title || paperGroup.key}"?`);
	if (!confirmed) return;
	setEvalBuilderBusy(true);
	setEvalBuilderError('');
	try {
		const response = await submitDeletePaperMock({
			dataset_id: state.evalBuilder.selectedDatasetId,
			paper_key: paperGroup.key,
			title: paperGroup.title,
			entity_count: paperGroup.cases.length,
		});
		await loadEvalBuilderData(true);
		await loadDatasetOptions();
		state.evalBuilder.selectedPaperKey = null;
		state.evalBuilder.mode = 'edit_group';
		resetEvalBuilderPaperDraft();
		renderEvalBuilder();
		setEvalBuilderStatus(`Paper deleted (${response?.deleted_cases || 0} entities removed).`);
	} catch (err) {
		setEvalBuilderError(err?.message || 'Delete paper failed.');
	} finally {
		setEvalBuilderBusy(false);
	}
}

function openNewBatchModal() {
	const modal = $('#newBatchModal');
	if (modal) {
		modal.classList.remove('hidden');
		$('#batchName')?.focus();
	}
}

function closeNewBatchModal() {
	const modal = $('#newBatchModal');
	if (modal) {
		modal.classList.add('hidden');
		// Reset form
		const form = $('#newBatchForm');
		if (form) form.reset();
		renderBatchModelOptions({ preserveSelection: false });
	}
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

function renderBatchModelOptions({ preserveSelection = true } = {}) {
	const select = $('#batchModel');
	const modelSelect = $('#batchProviderModel');
	if (!select || !modelSelect) return;
	const descriptor = (state.providers || []).find((item) => item.provider_id === select.value);
	const models = [];
	const seen = new Set();
	for (const candidate of [descriptor?.default_model, ...(descriptor?.curated_models || [])]) {
		const model = (candidate || '').trim();
		if (!model || seen.has(model)) continue;
		seen.add(model);
		models.push(model);
	}

	const previous = preserveSelection ? (modelSelect.value || '') : '';
	modelSelect.innerHTML = '';

	if (!models.length) {
		const fallback = document.createElement('option');
		fallback.value = '';
		fallback.textContent = 'Provider default';
		modelSelect.appendChild(fallback);
		modelSelect.value = '';
		return;
	}

	for (const model of models) {
		const option = document.createElement('option');
		option.value = model;
		option.textContent = model;
		modelSelect.appendChild(option);
	}

	modelSelect.value = previous && models.includes(previous) ? previous : models[0];
}

function renderBatchProviderOptions() {
	const select = $('#batchModel');
	if (!select) return;
	const enabled = (state.providers || []).filter((item) => item.enabled);
	if (!enabled.length) return;
	const previous = select.value;
	select.innerHTML = '';
	for (const item of enabled) {
		const option = document.createElement('option');
		option.value = item.provider_id;
		option.textContent = item.label || item.provider_id;
		select.appendChild(option);
	}
	select.value = enabled.some((item) => item.provider_id === previous)
		? previous
		: enabled[0].provider_id;
	renderBatchModelOptions({ preserveSelection: true });
}

async function loadProviders() {
	try {
		const payload = await api.getProviders();
		let providers = payload.providers || [];
		if (shouldRefreshProviderCatalog(providers)) {
			const refreshed = await api.refreshProviders();
			providers = refreshed.providers || providers;
		}
		state.providers = providers;
		renderBatchProviderOptions();
	} catch (err) {
		console.error('Failed to load provider catalog:', err);
	}
}

async function createBatch(name, model, promptId, modelId) {
	const submitBtn = $('#submitBatchBtn');
	const label = submitBtn?.querySelector('.sw-btn__label');

	try {
		if (submitBtn) {
			submitBtn.disabled = true;
			if (label) label.textContent = 'Creating...';
		}

		updateStatus('Creating evaluation run...');

		const response = await api.post('/api/baseline/batch-enqueue', {
			dataset: state.selectedDataset || 'self_assembly',
			label: name || null,
			provider: model,
			model: modelId || null,
			prompt_id: promptId ? parseInt(promptId, 10) : null,
		});

		updateStatus(`Run created: ${response.enqueued} papers queued`);
		closeNewBatchModal();

		// Reload batches to show the new one
		await loadBatches();
	} catch (err) {
		console.error('Failed to create batch:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (submitBtn) {
			submitBtn.disabled = false;
			if (label) label.textContent = 'Start Run';
		}
	}
}

async function retryBatchFailed(batchId, button) {
	const label = button?.querySelector('.sw-btn__label');
	const originalText = label?.textContent || 'Retry';

	try {
		if (button) {
			button.disabled = true;
			if (label) label.textContent = 'Retrying...';
		}

		updateStatus('Retrying failed runs...');

		const response = await api.post('/api/baseline/batch-retry', {
			batch_id: batchId,
		});

		updateStatus(`Retrying ${response.retried} runs`);

		// Reload batches to show updated status
		await loadBatches();
	} catch (err) {
		console.error('Failed to retry batch:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (button) {
			button.disabled = false;
			if (label) label.textContent = originalText;
		}
	}
}

async function stopBatchRun(batchId, batchLabel, button) {
	if (!confirm(`Stop run "${batchLabel}"?\n\nThis cancels all queued/in-progress requests for this run.`)) {
		return;
	}

	const label = button?.querySelector('.sw-btn__label');
	const originalText = label?.textContent || 'Stop';

	try {
		if (button) {
			button.disabled = true;
			if (label) label.textContent = 'Stopping...';
		}

		updateStatus('Stopping run...');

		const response = await api.post('/api/baseline/batch-stop', {
			batch_id: batchId,
		});

		updateStatus(`Stopped ${response.cancelled_runs} runs (${response.cancelled_jobs} queue jobs).`);
		await loadBatches();
	} catch (err) {
		console.error('Failed to stop batch:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (button) {
			button.disabled = false;
			if (label) label.textContent = originalText;
		}
	}
}

async function deleteBatch(batchId, batchLabel) {
	// Confirm deletion
	if (!confirm(`Delete run "${batchLabel}"?\n\nThis will permanently delete the run and all its extraction results.`)) {
		return;
	}

	try {
		updateStatus('Deleting run...');

		await api.del(`/api/baseline/batch/${encodeURIComponent(batchId)}`);

		updateStatus('Run deleted');

		// Remove from state and re-render
		state.batches = state.batches.filter(b => b.batch_id !== batchId);
		state.providerChartState = 'ready';
		state.providerChartError = '';
		renderBatchGrid();
	} catch (err) {
		console.error('Failed to delete batch:', err);
		updateStatus(`Error: ${err.message}`);
	}
}

async function resetBaselineDefaults(button) {
	const confirmed = window.confirm(
		'Reset baseline defaults for all evaluations?\n\nThis removes all local baseline edits and cannot be undone.',
	);
	if (!confirmed) return;

	const label = button?.querySelector('.sw-btn__label');
	const originalLabel = label?.textContent || 'Reset Baseline Data';
	try {
		if (button) {
			button.disabled = true;
		}
		if (label) {
			label.textContent = 'Resetting...';
		}
		updateStatus('Resetting baseline data...');
		const response = await api.resetBaselineDefaults();
		await loadBatches();
		updateStatus(
			`Baseline reset complete (${formatCount(response.total_cases)} cases loaded, ${formatCount(response.deleted_cases)} replaced).`,
		);
	} catch (err) {
		console.error('Failed to reset baseline defaults:', err);
		updateStatus(`Error: ${err.message}`);
	} finally {
		if (button) {
			button.disabled = false;
		}
		if (label) {
			label.textContent = originalLabel;
		}
	}
}

// Debounce state for SSE updates
let sseUpdateTimer = null;
const pendingBatchUpdates = new Set();

function connectSSE() {
	if (state.sseConnection) {
		state.sseConnection.close();
	}

	state.sseConnection = api.createSSEConnection(
		(data) => {
			if (data.event === 'baseline_recompute_finished' || data.event === 'baseline_recompute_progress') {
				queueBatchUpdate(data.data?.batch_id || '__baseline_recompute__');
				return;
			}
			if (data.event === 'run_status' && data.data?.batch_id) {
				// Queue batch update with debouncing
				queueBatchUpdate(data.data.batch_id);
			}
		},
		(err) => {
			console.error('SSE connection error:', err);
			// Reconnect after delay
			setTimeout(() => connectSSE(), 5000);
		}
	);
}

function queueBatchUpdate(batchId) {
	pendingBatchUpdates.add(batchId);

	// Debounce: wait 500ms after last event before fetching
	if (sseUpdateTimer) {
		clearTimeout(sseUpdateTimer);
	}
	sseUpdateTimer = setTimeout(() => {
		processPendingBatchUpdates();
	}, 500);
}

function renderBatchGridPreservingScroll() {
	const x = window.scrollX;
	const y = window.scrollY;
	renderBatchGrid();
	window.scrollTo(x, y);
}

async function processPendingBatchUpdates() {
	if (pendingBatchUpdates.size === 0) return;

	const batchIds = Array.from(pendingBatchUpdates);
	pendingBatchUpdates.clear();
	sseUpdateTimer = null;

	try {
		const response = await api.get(getBatchesEndpoint());
		const fetchedBatches = response.batches || [];
		state.providerChartState = 'ready';
		state.providerChartError = '';

		if (batchIds.includes('__baseline_recompute__')) {
			state.batches = fetchedBatches;
			renderBatchGridPreservingScroll();
			return;
		}

		let shouldRenderGrid = false;

		for (const batchId of batchIds) {
			const updatedBatch = fetchedBatches.find(b => b.batch_id === batchId);
			if (updatedBatch) {
				// Update in state
				const idx = state.batches.findIndex(b => b.batch_id === batchId);
				if (idx >= 0) {
					state.batches[idx] = updatedBatch;
				} else {
					// New batch
					state.batches.unshift(updatedBatch);
				}
				// Re-render that card
				const existingCard = document.querySelector(`[data-batch-id="${batchId}"]`);
				if (existingCard) {
					patchBatchCardElement(existingCard, updatedBatch);
				} else {
					// New batch card - re-render grid
					shouldRenderGrid = true;
				}
			}
		}

		if (shouldRenderGrid) {
			renderBatchGridPreservingScroll();
		} else {
			renderProviderAccuracyChart();
		}
	} catch (err) {
		state.providerChartState = 'error';
		state.providerChartError = err?.message || 'Failed to refresh model analytics';
		renderProviderAccuracyChart();
		console.error('Failed to update batches:', err);
	}
}

async function initializeOverviewData() {
	await loadDatasetOptions();
	await Promise.all([loadProviders(), loadPrompts()]);
	await loadBatches();
}

function init() {
	// Load data
	initProviderMetricControls();
	renderProviderAccuracyChart();
	void initializeOverviewData();

	// Connect SSE for live updates
	connectSSE();

	// Event listeners
	$('#newBatchBtn')?.addEventListener('click', openNewBatchModal);
	$('#emptyNewBatchBtn')?.addEventListener('click', openNewBatchModal);
	$('#cancelBatchBtn')?.addEventListener('click', closeNewBatchModal);
	$('#modalBackdrop')?.addEventListener('click', closeNewBatchModal);
	$('#batchDatasetFilter')?.addEventListener('change', async (event) => {
		const next = (event.target?.value || '').trim();
		if (!next || next === state.selectedDataset) return;
		state.selectedDataset = next;
		persistDatasetFilter(next);
		await loadBatches();
	});
	$('#openEvalBuilder')?.addEventListener('click', () => {
		openEvalBuilderModal();
	});
	$('#evalBuilderClose')?.addEventListener('click', closeEvalBuilderModal);
	$('#evalBuilderBackdrop')?.addEventListener('click', closeEvalBuilderModal);
	$('#evalBuilderNewGroupBtn')?.addEventListener('click', startEvalBuilderCreateGroupMode);
	$('#evalBuilderNewPaperBtn')?.addEventListener('click', startEvalBuilderCreatePaperMode);
	$('#evalBuilderCreateGroupBtn')?.addEventListener('click', async () => {
		await handleEvalBuilderCreateGroup();
	});
	$('#evalBuilderSavePaperBtn')?.addEventListener('click', async () => {
		await handleEvalBuilderSavePaper();
	});
	$('#evalBuilderDeleteGroupBtn')?.addEventListener('click', async () => {
		await handleEvalBuilderDeleteGroup();
	});
	$('#evalBuilderDeletePaperBtn')?.addEventListener('click', async () => {
		await handleEvalBuilderDeletePaper();
	});
	['#evalBuilderGroupId', '#evalBuilderGroupLabel', '#evalBuilderGroupDescription', '#evalBuilderPaperTitle', '#evalBuilderPaperDoi', '#evalBuilderPaperUrl'].forEach((selector) => {
		const node = $(selector);
		if (node) node.addEventListener('input', syncEvalBuilderDraftFromInputs);
	});
	$('#evalBuilderMainPdf')?.addEventListener('change', () => {
		const node = $('#evalBuilderMainPdf');
		const file = node?.files && node.files[0] ? node.files[0] : null;
		state.evalBuilder.draftPaper.main_pdf_file = file;
	});
	$('#evalBuilderSupportingPdfs')?.addEventListener('change', () => {
		const node = $('#evalBuilderSupportingPdfs');
		const files = node?.files ? Array.from(node.files) : [];
		state.evalBuilder.draftPaper.supporting_pdf_files = files;
	});
	$('#evalBuilderAddEntityBtn')?.addEventListener('click', () => {
		state.evalBuilder.draftGroundTruthEntities.push(createEmptyGroundTruthEntity());
		renderEvalBuilderForm();
	});
	$('#evalBuilderGroupsList')?.addEventListener('click', (event) => {
		const target = event.target?.closest?.('[data-action="select-group"]');
		if (!target) return;
		selectEvalBuilderGroup(target.dataset.datasetId || null);
	});
	$('#evalBuilderPapersList')?.addEventListener('click', (event) => {
		const target = event.target?.closest?.('[data-action="select-paper"]');
		if (!target) return;
		selectEvalBuilderPaper(target.dataset.paperKey || null);
	});
	$('#evalBuilderGroundTruthList')?.addEventListener('click', (event) => {
		const target = event.target?.closest?.('[data-action="remove-gt-entity"]');
		if (!target) return;
		const index = Number(target.dataset.index);
		if (!Number.isInteger(index) || index < 0) return;
		if (state.evalBuilder.draftGroundTruthEntities.length <= 1) {
			setEvalBuilderError('At least one ground truth entity is required.');
			return;
		}
		state.evalBuilder.draftGroundTruthEntities.splice(index, 1);
		renderEvalBuilderForm();
	});
	$('#evalBuilderGroundTruthList')?.addEventListener('input', (event) => {
		const target = event.target;
		if (!target || target.dataset.action !== 'gt-input') return;
		const index = Number(target.dataset.index);
		const field = target.dataset.field;
		if (!Number.isInteger(index) || index < 0 || !field) return;
		const entity = state.evalBuilder.draftGroundTruthEntities[index];
		if (!entity) return;
		entity[field] = target.value;
	});
	$('#batchModel')?.addEventListener('change', () => renderBatchModelOptions({ preserveSelection: false }));
	renderBatchModelOptions({ preserveSelection: true });
	$('#resetBaselineDefaultsBtn')?.addEventListener('click', async () => {
		await resetBaselineDefaults($('#resetBaselineDefaultsBtn'));
	});

	// Form submission
	$('#newBatchForm')?.addEventListener('submit', async (e) => {
		e.preventDefault();
		const name = $('#batchName')?.value?.trim() || '';
		const model = $('#batchModel')?.value || 'openai-nano';
		const selectedModel = $('#batchProviderModel')?.value?.trim() || null;
		const promptId = $('#batchPrompt')?.value || null;
		await createBatch(name, model, promptId, selectedModel);
	});

	// Keyboard escape to close modal
	document.addEventListener('keydown', (e) => {
		if (e.key === 'Escape') {
			closeEvalBuilderModal();
			closeNewBatchModal();
		}
	});

	window.addEventListener('resize', queueProviderChartRerender);
}

// Initialize on DOM ready
if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', init);
} else {
	init();
}
