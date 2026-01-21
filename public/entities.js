import {
	getEntities,
	getEntity,
	getEntityKpis,
	getQualityRules,
	updateQualityRules,
} from './js/api.js?v=dev45';
import { initTour } from './js/tour.js?v=dev45';
import { markMilestone, renderChecklist, resetMilestones } from './js/onboarding.js?v=dev45';

const $ = (sel) => document.querySelector(sel);

const state = {
	items: [],
	aggregates: [],
	kpis: null,
	groupBy: '',
	showMissingKey: false,
	latestOnly: false,
	recentOnly: false,
	recentMinutes: 15,
	reviewMode: false,
	reviewPool: [],
	reviewIndex: 0,
	evidenceMode: false,
	missingFieldFilter: null,
	compareA: '',
	compareB: '',
};

const QA_ONBOARDING_KEY = 'onboarding_entities_v1';
const QA_STEPS = [
	{ key: 'opened_entity', label: 'Open an entity detail' },
	{ key: 'review_mode', label: 'Use review mode' },
	{ key: 'evidence_gaps', label: 'Check evidence gaps view' },
	{ key: 'compare_prompts', label: 'Compare prompt versions' },
];

const INVALID_FLAGS = new Set([
	'invalid_ph',
	'invalid_temperature',
	'invalid_concentration',
	'invalid_sequence_chars',
	'evidence_missing_quote',
	'peptide_and_molecule_set',
]);
const REGRESSION_THRESHOLD = 0.5;

async function loadKpis() {
	state.latestOnly = $('#latestOnly').checked;
	state.recentOnly = $('#recentOnly').checked;
	state.recentMinutes = parseRecentMinutes();
	const data = await getEntityKpis({
		latestOnly: state.latestOnly,
		recentMinutes: state.recentOnly ? state.recentMinutes : null,
	});
	state.kpis = data;
	renderKpis();
}

async function loadEntities() {
	state.groupBy = $('#groupBySelect').value;
	if (state.groupBy && !$('#showMissingKey').checked) {
		$('#showMissingKey').checked = true;
	}
	state.showMissingKey = $('#showMissingKey').checked;
	state.latestOnly = $('#latestOnly').checked;
	state.recentOnly = $('#recentOnly').checked;
	state.recentMinutes = parseRecentMinutes();
	const data = await getEntities(state.groupBy || null, state.showMissingKey, {
		latestOnly: state.latestOnly,
		recentMinutes: state.recentOnly ? state.recentMinutes : null,
	});
	state.items = data.items || [];
	state.aggregates = data.aggregates || [];
	updateFilterOptions();
	updateMissingFieldFilter();
	renderEntities();
}

function parseRecentMinutes() {
	const input = $('#recentMinutes');
	const value = Number.parseInt(input?.value || '15', 10);
	if (Number.isNaN(value) || value < 1) return 15;
	return value;
}

function renderKpis() {
	const kpis = state.kpis;
	if (!kpis) return;
	$('#kpiTotal').textContent = kpis.total_entities ?? 0;
	$('#kpiMissing').textContent = `${(kpis.missing_evidence_pct ?? 0).toFixed(1)}%`;
	$('#kpiInvalid').textContent = `${(kpis.invalid_pct ?? 0).toFixed(1)}%`;

	const morph = $('#kpiMorphology');
	morph.innerHTML = '';
	(kpis.top_morphology || []).forEach((item) => {
		morph.appendChild(el('div', 'text-xs text-slate-600', `${item.value}: ${item.count}`));
	});
	if (!(kpis.top_morphology || []).length) {
		morph.appendChild(el('div', 'text-xs text-slate-400', 'No data'));
	}

	const validation = $('#kpiValidation');
	validation.innerHTML = '';
	(kpis.top_validation_methods || []).forEach((item) => {
		validation.appendChild(el('div', 'text-xs text-slate-600', `${item.value}: ${item.count}`));
	});
	if (!(kpis.top_validation_methods || []).length) {
		validation.appendChild(el('div', 'text-xs text-slate-400', 'No data'));
	}

	const missingFields = $('#kpiMissingFields');
	missingFields.innerHTML = '';
	(kpis.top_missing_fields || []).forEach((item) => {
		missingFields.appendChild(el('div', 'text-xs text-slate-600', `${item.value}: ${item.count}`));
	});
	if (!(kpis.top_missing_fields || []).length) {
		missingFields.appendChild(el('div', 'text-xs text-slate-400', 'No data'));
	}
}

function renderEntities() {
	const groupBy = state.groupBy;
	const aggregatesTable = $('#aggregatesTable');
	const missingFieldsTable = $('#missingFieldsTable');
	const entitiesTable = $('#entitiesTable');
	const emptyState = $('#entitiesEmpty');
	aggregatesTable.classList.add('hidden');
	missingFieldsTable.classList.add('hidden');
	entitiesTable.classList.remove('hidden');

	if (groupBy) {
		state.reviewPool = [];
		updateReviewStatus();
		state.evidenceMode = false;
		$('#evidenceMode').checked = false;
		renderAggregates();
		return;
	}

	const filtered = filterItems(state.items);
	const reviewPool = buildReviewPool(filtered);
	state.reviewPool = reviewPool;
	updateReviewStatus();
	const listToRender = state.reviewMode ? reviewPool : filtered;

	if (state.evidenceMode) {
		renderEvidenceGaps(filtered);
		return;
	}

	if (!listToRender.length) {
		entitiesTable.innerHTML = '';
		emptyState.classList.remove('hidden');
		renderPromptComparison();
		return;
	}
	emptyState.classList.add('hidden');
	entitiesTable.innerHTML = '';
	entitiesTable.appendChild(renderEntityHeader());
	listToRender.forEach((item) => {
		entitiesTable.appendChild(renderEntityRow(item));
	});
	renderPromptComparison();
}

function renderAggregates() {
	const aggregatesTable = $('#aggregatesTable');
	const entitiesTable = $('#entitiesTable');
	const emptyState = $('#entitiesEmpty');
	entitiesTable.classList.add('hidden');
	aggregatesTable.classList.remove('hidden');
	aggregatesTable.innerHTML = '';

	if (!state.aggregates.length) {
		emptyState.classList.remove('hidden');
		return;
	}
	emptyState.classList.add('hidden');

	const header = el('div', 'sw-row sw-row--header sw-kicker grid grid-cols-5 gap-3 px-6 py-3 text-xs text-slate-500');
	header.appendChild(el('div', '', 'Group value'));
	header.appendChild(el('div', '', 'Entities'));
	header.appendChild(el('div', '', 'Runs'));
	header.appendChild(el('div', '', 'Papers'));
	header.appendChild(el('div', '', 'Actions'));
	aggregatesTable.appendChild(header);

	state.aggregates.forEach((item) => {
		const row = el('div', 'sw-row grid grid-cols-5 gap-3 px-6 py-3 text-sm text-slate-700 hover:bg-slate-50');
		row.appendChild(el('div', 'font-medium', item.group_value));
		row.appendChild(el('div', '', String(item.entity_count)));
		row.appendChild(el('div', '', String(item.run_count)));
		row.appendChild(el('div', '', String(item.paper_count)));
		const action = el('button', 'text-xs text-indigo-600 hover:underline', 'Show entities');
		action.addEventListener('click', () => {
			$('#groupBySelect').value = '';
			$('#entitySearch').value = item.group_value;
			loadEntities();
		});
		row.appendChild(action);
		aggregatesTable.appendChild(row);
	});
}

function renderEvidenceGaps(items) {
	const missingFieldsTable = $('#missingFieldsTable');
	const entitiesTable = $('#entitiesTable');
	const emptyState = $('#entitiesEmpty');
	entitiesTable.classList.add('hidden');
	missingFieldsTable.classList.remove('hidden');
	missingFieldsTable.innerHTML = '';

	const buckets = {};
	items.forEach((item) => {
		(item.missing_evidence_fields || []).forEach((field) => {
			const bucket = buckets[field] || { count: 0, entityIds: [] };
			bucket.count += 1;
			bucket.entityIds.push(item.id);
			buckets[field] = bucket;
		});
	});

	const entries = Object.entries(buckets).sort((a, b) => b[1].count - a[1].count);
	if (!entries.length) {
		emptyState.classList.remove('hidden');
		return;
	}
	emptyState.classList.add('hidden');

	const header = el('div', 'sw-row sw-row--header sw-kicker grid grid-cols-3 gap-3 px-6 py-3 text-xs text-slate-500');
	header.appendChild(el('div', '', 'Field'));
	header.appendChild(el('div', '', 'Missing entities'));
	header.appendChild(el('div', '', 'Actions'));
	missingFieldsTable.appendChild(header);

	entries.forEach(([field, bucket]) => {
		const row = el('div', 'sw-row grid grid-cols-3 gap-3 px-6 py-3 text-sm text-slate-700 hover:bg-slate-50');
		row.appendChild(el('div', 'font-medium', field));
		row.appendChild(el('div', '', String(bucket.count)));
		const actions = el('div', 'flex gap-3');
		const openSample = el('button', 'text-xs text-indigo-600 hover:underline', 'Open sample');
		openSample.addEventListener('click', () => openEntityDrawer(bucket.entityIds[0]));
		const showEntities = el('button', 'text-xs text-indigo-600 hover:underline', 'Show entities');
		showEntities.addEventListener('click', () => {
			state.missingFieldFilter = field;
			state.evidenceMode = false;
			$('#evidenceMode').checked = false;
			updateMissingFieldFilter();
			renderEntities();
		});
		actions.appendChild(openSample);
		actions.appendChild(showEntities);
		row.appendChild(actions);
		missingFieldsTable.appendChild(row);
	});
}

function updateMissingFieldFilter() {
	const row = $('#missingFieldFilterRow');
	const value = $('#missingFieldFilterValue');
	if (!row || !value) return;
	if (!state.missingFieldFilter) {
		row.classList.add('hidden');
		value.textContent = '';
		return;
	}
	row.classList.remove('hidden');
	value.textContent = state.missingFieldFilter;
}

function filterItems(items) {
	const term = $('#entitySearch').value.trim().toLowerCase();
	const type = $('#entityType').value;
	const provider = $('#providerFilter').value;
	const prompt = $('#promptFilter').value;
	const source = $('#sourceFilter').value;
	const requireMissing = $('#flagMissing').checked;
	const requireInvalid = $('#flagInvalid').checked;

	return items.filter((item) => {
		if (type !== 'all' && item.entity_type !== type) return false;
		if (provider !== 'all' && item.model_provider !== provider) return false;
		if (prompt !== 'all' && item.prompt_version !== prompt) return false;
		if (source !== 'all' && item.paper_source !== source) return false;
		if (requireMissing && !item.flags?.includes('missing_evidence')) return false;
		if (requireInvalid && !item.flags?.some((flag) => INVALID_FLAGS.has(flag))) return false;

		if (state.missingFieldFilter && !(item.missing_evidence_fields || []).includes(state.missingFieldFilter)) {
			return false;
		}
		if (!term) return true;
		const hay = [
			item.peptide_sequence_one_letter,
			item.peptide_sequence_three_letter,
			item.chemical_formula,
			item.smiles,
			item.inchi,
			item.paper_title,
			item.paper_doi,
			item.model_provider,
			item.prompt_version,
			item.paper_source,
		].filter(Boolean).join(' ').toLowerCase();
		return hay.includes(term);
	});
}

function renderEntityHeader() {
	const header = el('div', 'sw-row sw-row--header sw-kicker grid grid-cols-8 gap-3 px-6 py-3 text-xs text-slate-500');
	header.appendChild(el('div', '', 'Identifier'));
	header.appendChild(el('div', '', 'Type'));
	header.appendChild(el('div', '', 'Morphology'));
	header.appendChild(el('div', '', 'Validation'));
	header.appendChild(el('div', '', 'Conditions'));
	header.appendChild(el('div', '', 'Evidence %'));
	header.appendChild(el('div', '', 'Paper'));
	header.appendChild(el('div', '', 'Model/Prompt'));
	return header;
}

function renderEntityRow(item) {
	const rowClass = [
		'sw-row grid grid-cols-8 gap-3 px-6 py-3 text-sm text-slate-700 cursor-pointer',
		'hover:bg-slate-50 border-l-4 border-transparent',
		item.flags?.includes('missing_evidence') ? 'border-l-amber-400' : '',
		item.flags?.some((flag) => INVALID_FLAGS.has(flag)) ? 'border-l-red-400' : '',
	].join(' ');
	const row = el('div', rowClass);
	const identifier = el('div', 'space-y-1');
	identifier.appendChild(el('div', 'font-medium', formatIdentifier(item)));
	const badges = el('div', 'flex flex-wrap gap-1');
	if (item.flags?.includes('missing_evidence')) {
		badges.appendChild(el('span', 'px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[10px]', 'missing evidence'));
	}
	if (item.flags?.some((flag) => INVALID_FLAGS.has(flag))) {
		badges.appendChild(el('span', 'px-2 py-0.5 rounded-full bg-red-100 text-red-700 text-[10px]', 'invalid'));
	}
	if (badges.childNodes.length) {
		identifier.appendChild(badges);
	}
	row.appendChild(identifier);
	row.appendChild(el('div', '', item.entity_type || '-'));
	row.appendChild(el('div', 'text-xs', (item.morphology || []).slice(0, 2).join(', ') || '-'));
	row.appendChild(el('div', 'text-xs', (item.validation_methods || []).slice(0, 2).join(', ') || '-'));
	row.appendChild(el('div', 'text-xs', formatConditions(item)));
	row.appendChild(el('div', '', `${item.evidence_coverage ?? 0}%`));
	row.appendChild(el('div', 'text-xs text-slate-500', item.paper_title || '-'));
	row.appendChild(el('div', 'text-xs text-slate-500', formatModel(item)));
	row.addEventListener('click', () => openEntityDrawer(item.id));
	row.setAttribute('role', 'button');
	row.setAttribute('tabindex', '0');
	row.addEventListener('keydown', (event) => {
		if (event.key === 'Enter' || event.key === ' ') {
			event.preventDefault();
			openEntityDrawer(item.id);
		}
	});
	return row;
}

function formatIdentifier(item) {
	return item.peptide_sequence_one_letter
		|| item.peptide_sequence_three_letter
		|| item.smiles
		|| item.inchi
		|| item.chemical_formula
		|| `Entity ${item.id}`;
}

function formatConditions(item) {
	const parts = [];
	if (item.ph !== null && item.ph !== undefined) parts.push(`pH ${item.ph}`);
	if (item.concentration !== null && item.concentration !== undefined) {
		const unit = item.concentration_units ? ` ${item.concentration_units}` : '';
		parts.push(`${item.concentration}${unit}`);
	}
	if (item.temperature_c !== null && item.temperature_c !== undefined) {
		parts.push(`${item.temperature_c}°C`);
	}
	return parts.join(' · ') || '-';
}

function formatModel(item) {
	const provider = item.model_provider || '-';
	const prompt = item.prompt_version || '-';
	return `${provider} · ${prompt}`;
}

function buildReviewPool(items) {
	if (!state.reviewMode) return [];
	const flagged = items.filter((item) => (item.flags || []).length);
	return flagged.sort((a, b) => reviewScore(b) - reviewScore(a));
}

function reviewScore(item) {
	let score = 0;
	score += 100 - (item.evidence_coverage ?? 0);
	if (item.flags?.includes('missing_evidence')) score += 20;
	if (item.flags?.some((flag) => INVALID_FLAGS.has(flag))) score += 50;
	return score;
}

function updateReviewStatus() {
	const label = $('#reviewStatus');
	if (!label) return;
	if (!state.reviewMode) {
		label.textContent = '';
		return;
	}
	const total = state.reviewPool.length;
	if (!total) {
		label.textContent = 'No flagged entities.';
		return;
	}
	const index = Math.min(state.reviewIndex + 1, total);
	label.textContent = `Reviewing ${index} of ${total}`;
}

function updateFilterOptions() {
	const providerSelect = $('#providerFilter');
	const promptSelect = $('#promptFilter');
	const sourceSelect = $('#sourceFilter');
	if (!providerSelect || !promptSelect || !sourceSelect) return;

	const providers = uniqueValues(state.items.map((item) => item.model_provider));
	const prompts = uniqueValues(state.items.map((item) => item.prompt_version));
	const sources = uniqueValues(state.items.map((item) => item.paper_source));

	setOptions(providerSelect, providers, 'all');
	setOptions(promptSelect, prompts, 'all');
	setOptions(sourceSelect, sources, 'all');
	updatePromptCompareOptions(prompts);
}

function setOptions(select, values, defaultValue) {
	const current = select.value || defaultValue;
	select.innerHTML = '';
	select.appendChild(new Option(`All ${select.id.replace('Filter', '').toLowerCase()}s`, 'all'));
	values.forEach((value) => {
		const option = new Option(value, value);
		select.appendChild(option);
	});
	if ([...select.options].some((opt) => opt.value === current)) {
		select.value = current;
	}
}

function uniqueValues(values) {
	const set = new Set(values.filter(Boolean));
	return Array.from(set).sort();
}

function updatePromptCompareOptions(prompts) {
	const selectA = $('#comparePromptA');
	const selectB = $('#comparePromptB');
	if (!selectA || !selectB) return;

	const currentA = selectA.value;
	const currentB = selectB.value;
	selectA.innerHTML = '';
	selectB.innerHTML = '';
	selectA.appendChild(new Option('Select prompt A', ''));
	selectB.appendChild(new Option('Select prompt B', ''));
	prompts.forEach((value) => {
		selectA.appendChild(new Option(value, value));
		selectB.appendChild(new Option(value, value));
	});
	if (currentA) selectA.value = currentA;
	if (currentB) selectB.value = currentB;
}

async function openEntityDrawer(entityId) {
	const drawer = $('#entityDrawer');
	const overlay = $('#entityDrawerOverlay');
	const content = $('#entityDrawerContent');
	content.innerHTML = '<div class="text-xs text-slate-500">Loading...</div>';
	drawer.classList.remove('translate-x-full');
	overlay.classList.remove('hidden');

	const data = await getEntity(entityId);
	content.innerHTML = '';

	content.appendChild(renderEntitySummary(data));
	content.appendChild(renderMetaBlocks(data));
	content.appendChild(renderEntityLinks(data));
	content.appendChild(renderMissingEvidenceSummary(data));
	content.appendChild(renderEntityFields(data));
	markMilestone(QA_ONBOARDING_KEY, 'opened_entity');
	renderQaChecklist();
	updateContextHint();
}

function renderEntitySummary(data) {
	const item = data.item || {};
	const wrapper = el('div', 'space-y-2');
	wrapper.appendChild(el('div', 'text-sm font-semibold', formatIdentifier(item)));
	const meta = el('div', 'text-xs text-slate-500', `Type: ${item.entity_type || '-'}`);
	wrapper.appendChild(meta);

	const flagWrap = el('div', 'flex flex-wrap gap-2');
	(item.flags || []).forEach((flag) => {
		flagWrap.appendChild(el('span', 'px-2 py-0.5 rounded-full bg-amber-100 text-amber-700 text-[11px]', flag));
	});
	if (!(item.flags || []).length) {
		flagWrap.appendChild(el('span', 'text-xs text-slate-400', 'No flags'));
	}
	wrapper.appendChild(flagWrap);
	wrapper.appendChild(el('div', 'text-xs text-slate-500', `Evidence coverage: ${item.evidence_coverage ?? 0}%`));
	return wrapper;
}

function renderEntityLinks(data) {
	const wrapper = el('div', 'space-y-2');
	const run = data.run || {};
	if (run.id) {
		const row = el('div', 'flex items-center gap-3 text-xs');
		const link = el('a', 'sw-chip text-indigo-600 hover:bg-indigo-50', 'Open run detail');
		link.href = `/runs/${run.id}`;
		link.target = '_blank';
		const edit = el('a', 'sw-chip text-indigo-600 hover:bg-indigo-50', 'Open editor');
		edit.href = `/runs/${run.id}/edit`;
		edit.target = '_blank';
		row.appendChild(link);
		row.appendChild(edit);
		wrapper.appendChild(row);
	}
	return wrapper;
}

function renderMetaBlocks(data) {
	const wrapper = el('div', 'space-y-3');
	const paper = data.paper || {};
	const run = data.run || {};

	if (paper.id) {
		const block = el('div', 'text-xs text-slate-600 space-y-1');
		block.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Paper'));
		block.appendChild(el('div', '', paper.title || 'Untitled'));
		const line = [paper.source, paper.year, paper.doi].filter(Boolean).join(' · ');
		if (line) block.appendChild(el('div', 'text-slate-500', line));
		if (paper.url) {
			const link = el('a', 'text-indigo-600 hover:underline', paper.url);
			link.href = paper.url;
			link.target = '_blank';
			block.appendChild(link);
		}
		wrapper.appendChild(block);
	}

	if (run.id) {
		const block = el('div', 'text-xs text-slate-600 space-y-1');
		block.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', 'Run'));
		block.appendChild(el('div', '', `Run ${run.id}`));
		const line = [
			run.status ? `status: ${run.status}` : null,
			run.model_provider ? `provider: ${run.model_provider}` : null,
			run.model_name ? `model: ${run.model_name}` : null,
			run.prompt_version ? `prompt: ${run.prompt_version}` : null,
		].filter(Boolean).join(' · ');
		if (line) block.appendChild(el('div', 'text-slate-500', line));
		if (run.created_at) {
			block.appendChild(el('div', 'text-slate-500', `created: ${new Date(run.created_at).toLocaleString()}`));
		}
		if (run.comment) {
			block.appendChild(el('div', 'text-slate-500', `comment: ${run.comment}`));
		}
		wrapper.appendChild(block);
	}
	return wrapper;
}

function renderMissingEvidenceSummary(data) {
	const missing = data.missing_evidence_fields || [];
	if (!missing.length) return el('div', 'sw-empty text-xs text-slate-400 p-2', 'All extracted fields have evidence.');
	const wrapper = el('div', 'text-xs text-amber-600 space-y-1');
	wrapper.appendChild(el('div', 'sw-kicker text-[10px] text-amber-500', 'Missing evidence'));
	missing.slice(0, 8).forEach((field) => {
		wrapper.appendChild(el('div', '', field));
	});
	if (missing.length > 8) {
		wrapper.appendChild(el('div', '', `+${missing.length - 8} more`));
	}
	return wrapper;
}

function renderEntityFields(data) {
	const entity = data.entity || {};
	const evidence = data.evidence || {};
	const missing = new Set(data.missing_evidence_fields || []);

	const container = el('div', 'space-y-3');
	const fields = buildFieldList(entity);
	fields.forEach((field) => {
		const details = document.createElement('details');
		details.className = 'sw-card border border-slate-200 rounded-md p-3 bg-slate-50';
		const summary = document.createElement('summary');
		summary.className = 'cursor-pointer text-sm font-medium text-slate-700';
		summary.textContent = `${field.label}: ${formatFieldValue(field.value)}`;
		details.appendChild(summary);

		const body = el('div', 'mt-2 text-xs text-slate-600 space-y-1');
		if (missing.has(field.path)) {
			body.appendChild(el('div', 'text-amber-600', 'Missing evidence'));
		}
		const items = evidence[field.path] || [];
		if (!items.length) {
			body.appendChild(el('div', 'text-slate-400', 'No evidence provided.'));
		} else {
			items.forEach((item) => {
				const line = [
					item.quote ? `"${item.quote}"` : null,
					item.section ? `section: ${item.section}` : null,
					typeof item.page === 'number' ? `page: ${item.page}` : null,
				].filter(Boolean).join(' · ');
				body.appendChild(el('div', '', line));
			});
		}
		details.appendChild(body);
		container.appendChild(details);
	});
	return container;
}

function buildFieldList(entity) {
	const fields = [];
	const peptide = entity.peptide || {};
	const molecule = entity.molecule || {};
	const conditions = entity.conditions || {};
	const thresholds = entity.thresholds || {};

	addField(fields, 'Peptide sequence (1-letter)', 'peptide.sequence_one_letter', peptide.sequence_one_letter);
	addField(fields, 'Peptide sequence (3-letter)', 'peptide.sequence_three_letter', peptide.sequence_three_letter);
	addField(fields, 'N-terminal mod', 'peptide.n_terminal_mod', peptide.n_terminal_mod);
	addField(fields, 'C-terminal mod', 'peptide.c_terminal_mod', peptide.c_terminal_mod);
	addField(fields, 'Hydrogel', 'peptide.is_hydrogel', peptide.is_hydrogel);

	addField(fields, 'Chemical formula', 'molecule.chemical_formula', molecule.chemical_formula);
	addField(fields, 'SMILES', 'molecule.smiles', molecule.smiles);
	addField(fields, 'InChI', 'molecule.inchi', molecule.inchi);

	addField(fields, 'Labels', 'labels', entity.labels);
	addField(fields, 'Morphology', 'morphology', entity.morphology);
	addField(fields, 'Validation methods', 'validation_methods', entity.validation_methods);
	addField(fields, 'Reported characteristics', 'reported_characteristics', entity.reported_characteristics);

	addField(fields, 'pH', 'conditions.ph', conditions.ph);
	addField(fields, 'Concentration', 'conditions.concentration', conditions.concentration);
	addField(fields, 'Concentration units', 'conditions.concentration_units', conditions.concentration_units);
	addField(fields, 'Temperature (C)', 'conditions.temperature_c', conditions.temperature_c);

	addField(fields, 'CAC', 'thresholds.cac', thresholds.cac);
	addField(fields, 'CGC', 'thresholds.cgc', thresholds.cgc);
	addField(fields, 'MGC', 'thresholds.mgc', thresholds.mgc);

	addField(fields, 'Process protocol', 'process_protocol', entity.process_protocol);

	return fields.filter((field) => field.value !== undefined && field.value !== null && field.value !== '');
}

function addField(list, label, path, value) {
	list.push({ label, path, value });
}

function formatFieldValue(value) {
	if (Array.isArray(value)) {
		return value.join(', ') || '-';
	}
	if (value === null || value === undefined || value === '') {
		return '-';
	}
	return String(value);
}

function el(tag, cls, text) {
	const node = document.createElement(tag);
	if (cls) node.className = cls;
	if (text !== undefined) node.textContent = text;
	return node;
}

async function openRulesEditor() {
	const modal = $('#rulesModal');
	const editor = $('#rulesEditor');
	const status = $('#rulesStatus');
	modal.classList.remove('hidden');
	modal.classList.add('flex');
	status.textContent = 'Loading rules...';
	try {
		const data = await getQualityRules();
		editor.value = JSON.stringify(data.rules || {}, null, 2);
		status.textContent = '';
	} catch (err) {
		status.textContent = err.message || 'Failed to load rules';
	}
}

async function saveRules() {
	const editor = $('#rulesEditor');
	const status = $('#rulesStatus');
	const saveBtn = $('#saveRulesBtn');
	try {
		const parsed = JSON.parse(editor.value);
		status.textContent = 'Saving...';
		if (saveBtn) {
			saveBtn.disabled = true;
			saveBtn.textContent = 'Saving...';
		}
		await updateQualityRules(parsed);
		status.textContent = 'Saved';
		showRulesToast();
		closeRules();
		await loadKpis();
		await loadEntities();
	} catch (err) {
		status.textContent = err.message || 'Failed to save rules';
	} finally {
		if (saveBtn) {
			saveBtn.disabled = false;
			saveBtn.textContent = 'Save rules';
		}
	}
}

function closeDrawer() {
	$('#entityDrawer').classList.add('translate-x-full');
	$('#entityDrawerOverlay').classList.add('hidden');
}

function closeRules() {
	$('#rulesModal').classList.add('hidden');
	$('#rulesModal').classList.remove('flex');
}

function showRulesToast() {
	const toast = $('#rulesToast');
	if (!toast) return;
	toast.classList.remove('hidden');
	setTimeout(() => {
		toast.classList.add('hidden');
	}, 2000);
}

function bindEvents() {
	$('#entitySearch').addEventListener('input', renderEntities);
	$('#providerFilter').addEventListener('change', renderEntities);
	$('#promptFilter').addEventListener('change', renderEntities);
	$('#sourceFilter').addEventListener('change', renderEntities);
	$('#entityType').addEventListener('change', renderEntities);
	$('#flagMissing').addEventListener('change', renderEntities);
	$('#flagInvalid').addEventListener('change', renderEntities);
	$('#groupBySelect').addEventListener('change', loadEntities);
	$('#showMissingKey').addEventListener('change', loadEntities);
	$('#latestOnly').addEventListener('change', async () => {
		await loadKpis();
		await loadEntities();
	});
	$('#recentOnly').addEventListener('change', async () => {
		await loadKpis();
		await loadEntities();
	});
	$('#recentMinutes').addEventListener('change', async () => {
		if (!$('#recentOnly').checked) return;
		await loadKpis();
		await loadEntities();
	});
	$('#reviewMode').addEventListener('change', () => {
		state.reviewMode = $('#reviewMode').checked;
		state.reviewIndex = 0;
		renderEntities();
		if (state.reviewMode) {
			markMilestone(QA_ONBOARDING_KEY, 'review_mode');
			renderQaChecklist();
			updateContextHint();
		}
	});
	$('#evidenceMode').addEventListener('change', () => {
		state.evidenceMode = $('#evidenceMode').checked;
		renderEntities();
		if (state.evidenceMode) {
			markMilestone(QA_ONBOARDING_KEY, 'evidence_gaps');
			renderQaChecklist();
			updateContextHint();
		}
	});
	$('#clearMissingFieldFilter').addEventListener('click', () => {
		state.missingFieldFilter = null;
		updateMissingFieldFilter();
		renderEntities();
	});
	$('#comparePromptsBtn').addEventListener('click', () => {
		state.compareA = $('#comparePromptA').value;
		state.compareB = $('#comparePromptB').value;
		renderPromptComparison();
		if (state.compareA && state.compareB) {
			markMilestone(QA_ONBOARDING_KEY, 'compare_prompts');
			renderQaChecklist();
		}
	});
	$('#exportEvidenceCsv').addEventListener('click', exportEvidenceCsv);
	$('#reviewNextBtn').addEventListener('click', openNextReview);
	$('#reviewRandomBtn').addEventListener('click', openRandomReview);
	$('#closeEntityDrawer').addEventListener('click', closeDrawer);
	$('#entityDrawerOverlay').addEventListener('click', closeDrawer);

	$('#openRulesBtn').addEventListener('click', openRulesEditor);
	$('#closeRulesBtn').addEventListener('click', closeRules);
	$('#saveRulesBtn').addEventListener('click', saveRules);

	document.addEventListener('keydown', (event) => {
		if (event.metaKey || event.ctrlKey || event.altKey) return;
		const tag = event.target?.tagName?.toLowerCase?.();
		if (tag === 'input' || tag === 'textarea' || tag === 'select') return;
		if (event.key === 'n' || event.key === 'N') {
			event.preventDefault();
			openNextReview();
		}
		if (event.key === 'r' || event.key === 'R') {
			event.preventDefault();
			openRandomReview();
		}
		if (event.key === 'e' || event.key === 'E') {
			event.preventDefault();
			state.evidenceMode = !state.evidenceMode;
			$('#evidenceMode').checked = state.evidenceMode;
			renderEntities();
		}
	});
}

function renderPromptComparison() {
	const container = $('#promptCompareResults');
	const delta = $('#promptCompareDelta');
	if (!container) return;
	container.innerHTML = '';
	if (delta) delta.textContent = '';
	if (!state.compareA || !state.compareB) {
		container.appendChild(el('div', 'text-slate-400', 'Select two prompt versions to compare.'));
		return;
	}
	const dataA = computeStats(state.items.filter((item) => item.prompt_version === state.compareA));
	const dataB = computeStats(state.items.filter((item) => item.prompt_version === state.compareB));
	container.appendChild(renderCompareCard(`Prompt ${state.compareA}`, dataA));
	container.appendChild(renderCompareCard(`Prompt ${state.compareB}`, dataB));
	if (delta) {
		const missingDelta = dataB.missingPct - dataA.missingPct;
		const invalidDelta = dataB.invalidPct - dataA.invalidPct;
		delta.innerHTML = '';
		delta.appendChild(renderDeltaBadge('Missing evidence', missingDelta));
		delta.appendChild(renderDeltaBadge('Invalid entries', invalidDelta));
	}
}

function computeStats(items) {
	const total = items.length;
	let missingCount = 0;
	let invalidCount = 0;
	const missingFields = {};
	const morphology = {};
	const validation = {};

	items.forEach((item) => {
		if (item.flags?.includes('missing_evidence')) missingCount += 1;
		if (item.flags?.some((flag) => INVALID_FLAGS.has(flag))) invalidCount += 1;
		(item.missing_evidence_fields || []).forEach((field) => {
			missingFields[field] = (missingFields[field] || 0) + 1;
		});
		(item.morphology || []).forEach((value) => {
			morphology[value] = (morphology[value] || 0) + 1;
		});
		(item.validation_methods || []).forEach((value) => {
			validation[value] = (validation[value] || 0) + 1;
		});
	});

	return {
		total,
		missingPct: total ? (missingCount / total) * 100 : 0,
		invalidPct: total ? (invalidCount / total) * 100 : 0,
		topMissingFields: topBuckets(missingFields),
		topMorphology: topBuckets(morphology),
		topValidation: topBuckets(validation),
	};
}

function topBuckets(map) {
	return Object.entries(map)
		.sort((a, b) => b[1] - a[1])
		.slice(0, 4)
		.map(([value, count]) => ({ value, count }));
}

function renderCompareCard(title, stats) {
	const card = el('div', 'sw-card border border-slate-200 rounded-md p-3 space-y-2');
	card.appendChild(el('div', 'sw-kicker text-xs text-slate-700', title));
	card.appendChild(el('div', '', `Entities: ${stats.total}`));
	card.appendChild(el('div', '', `Missing evidence: ${stats.missingPct.toFixed(1)}%`));
	card.appendChild(el('div', '', `Invalid entries: ${stats.invalidPct.toFixed(1)}%`));
	card.appendChild(renderBucketList('Top missing fields', stats.topMissingFields));
	card.appendChild(renderBucketList('Top morphology', stats.topMorphology));
	card.appendChild(renderBucketList('Top validation', stats.topValidation));
	return card;
}

function renderBucketList(label, items) {
	const block = el('div', 'space-y-1');
	block.appendChild(el('div', 'sw-kicker text-[10px] text-slate-400', label));
	if (!items.length) {
		block.appendChild(el('div', 'sw-empty text-slate-400 p-2', 'No data'));
		return block;
	}
	items.forEach((item) => {
		block.appendChild(el('div', '', `${item.value}: ${item.count}`));
	});
	return block;
}

function formatDelta(value, label) {
	const sign = value > 0 ? '+' : '';
	return `${label} Δ ${sign}${value.toFixed(1)}%`;
}

function renderDeltaBadge(label, value) {
	const badge = document.createElement('span');
	const trend = value > REGRESSION_THRESHOLD
		? 'regression'
		: value < -REGRESSION_THRESHOLD
			? 'improvement'
			: 'stable';
	const sign = value > 0 ? '+' : '';
	const styles = {
		regression: 'bg-red-100 text-red-700',
		improvement: 'bg-emerald-100 text-emerald-700',
		stable: 'bg-slate-100 text-slate-600',
	};
	badge.className = `inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[11px] mr-2 ${styles[trend]}`;
	badge.textContent = `${label} Δ ${sign}${value.toFixed(1)}% (${trend})`;
	return badge;
}

function openNextReview() {
	if (!state.reviewPool.length) return;
	const item = state.reviewPool[state.reviewIndex % state.reviewPool.length];
	state.reviewIndex = (state.reviewIndex + 1) % state.reviewPool.length;
	updateReviewStatus();
	openEntityDrawer(item.id);
}

function openRandomReview() {
	if (!state.reviewPool.length) return;
	const index = Math.floor(Math.random() * state.reviewPool.length);
	state.reviewIndex = index;
	updateReviewStatus();
	openEntityDrawer(state.reviewPool[index].id);
}

function exportEvidenceCsv() {
	const items = filterItems(state.items);
	if (!items.length) return;
	const buckets = {};
	items.forEach((item) => {
		(item.missing_evidence_fields || []).forEach((field) => {
			buckets[field] = (buckets[field] || 0) + 1;
		});
	});
	const rows = Object.entries(buckets)
		.sort((a, b) => b[1] - a[1])
		.map(([field, count]) => [field, String(count)]);
	if (!rows.length) return;

	const lines = ['field,missing_count', ...rows.map((row) => row.map(csvEscape).join(','))];
	const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8;' });
	const url = URL.createObjectURL(blob);
	const link = document.createElement('a');
	link.href = url;
	link.download = 'evidence_gaps.csv';
	document.body.appendChild(link);
	link.click();
	document.body.removeChild(link);
	URL.revokeObjectURL(url);
}

function csvEscape(value) {
	const text = String(value ?? '');
	if (text.includes('"') || text.includes(',') || text.includes('\n')) {
		return `"${text.replace(/"/g, '""')}"`;
	}
	return text;
}

async function init() {
	bindEvents();
	await loadKpis();
	await loadEntities();
	initTourGuide();
	renderQaChecklist();
	initContextHints();
}

init();

function renderQaChecklist() {
	renderChecklist({
		containerId: '#qaChecklist',
		progressId: '#qaProgress',
		items: QA_STEPS,
		storageKey: QA_ONBOARDING_KEY,
	});
	const resetBtn = document.querySelector('#resetQaChecklist');
	if (resetBtn && !resetBtn.dataset.bound) {
		resetBtn.dataset.bound = '1';
		resetBtn.addEventListener('click', () => {
			resetMilestones(QA_ONBOARDING_KEY);
			renderQaChecklist();
		});
	}
}

function initContextHints() {
	const dismiss = document.querySelector('#contextHintDismiss');
	if (dismiss) dismiss.addEventListener('click', hideHint);
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
	const state = getQaState();
	if (!state.opened_entity) {
		showHint('Tip: Click any entity row to inspect evidence per field.', 'entities_open_hint');
		return;
	}
	if (state.opened_entity && !state.review_mode) {
		showHint('Tip: Toggle Review mode to step through flagged entities.', 'entities_review_hint');
		return;
	}
	if (state.review_mode && !state.evidence_gaps) {
		showHint('Tip: Use Evidence gaps view to see missing evidence by field.', 'entities_gaps_hint');
		return;
	}
	hideHint();
}

function getQaState() {
	try {
		return JSON.parse(localStorage.getItem(QA_ONBOARDING_KEY) || '{}');
	} catch {
		return {};
	}
}

function initTourGuide() {
	const tour = initTour({
		storageKey: 'tour_entities_v1',
		autoStart: true,
		steps: [
			{
				selector: '#entitySearch',
				title: 'Search entities',
				body: 'Filter sequences, papers, and providers instantly.',
			},
			{
				selector: '#flagMissing',
				title: 'Evidence flags',
				body: 'Focus on missing evidence and invalid values.',
			},
			{
				selector: '#evidenceMode',
				title: 'Evidence gaps',
				body: 'See which fields most often lack evidence.',
			},
			{
				selector: '#reviewMode',
				title: 'Review mode',
				body: 'Step through flagged entities quickly.',
			},
			{
				selector: '#comparePromptsBtn',
				title: 'Prompt comparison',
				body: 'Compare KPIs between prompt versions.',
			},
		],
	});
	const btn = document.querySelector('#startTourBtn');
	if (btn) btn.addEventListener('click', tour.start);
}
