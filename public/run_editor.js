import { getRun, editRun } from './js/api.js?v=dev45';

const $ = (sel) => document.querySelector(sel);

let editorState = null;
let currentRunId = null;
let isDirty = false;

function getRunIdFromPath() {
	const parts = window.location.pathname.split('/').filter(Boolean);
	if (parts[parts.length - 1] === 'edit') {
		const id = parseInt(parts[parts.length - 2], 10);
		return Number.isNaN(id) ? null : id;
	}
	const last = parseInt(parts[parts.length - 1], 10);
	return Number.isNaN(last) ? null : last;
}

function deepClone(value) {
	return JSON.parse(JSON.stringify(value));
}

function initState(rawJson) {
	const payload = deepClone(rawJson || { paper: {}, entities: [], comment: null });
	payload.paper = payload.paper || {};
	payload.entities = payload.entities || [];
	payload.entities.forEach((entity) => {
		entity.labels = entity.labels || [];
		entity.morphology = entity.morphology || [];
		entity.validation_methods = entity.validation_methods || [];
		entity.reported_characteristics = entity.reported_characteristics || [];
		entity.conditions = entity.conditions || { ph: null, concentration: null, concentration_units: null, temperature_c: null };
		entity.thresholds = entity.thresholds || { cac: null, cgc: null, mgc: null };
		entity._evidenceRows = buildEvidenceRows(entity.evidence || {});
	});
	return payload;
}

function renderEditor() {
	renderPaperFields();
	renderEntitiesEditor();
	$('#commentField').value = editorState.comment || '';
}

function renderPaperFields() {
	const container = $('#paperFields');
	container.innerHTML = '';
	const paper = editorState.paper || {};
	container.appendChild(renderInput('Title', paper.title || '', (value) => { paper.title = value || null; }));
	container.appendChild(renderInput('DOI', paper.doi || '', (value) => { paper.doi = value || null; }));
	container.appendChild(renderInput('URL', paper.url || '', (value) => { paper.url = value || null; }));
	container.appendChild(renderInput('Source', paper.source || '', (value) => { paper.source = value || null; }));
	container.appendChild(renderInput('Year', paper.year || '', (value) => { paper.year = value ? Number(value) : null; }, 'number'));
	container.appendChild(renderInput('Authors (comma separated)', (paper.authors || []).join(', '), (value) => {
		paper.authors = splitList(value);
	}));
}

function renderEntitiesEditor() {
	const container = $('#entitiesEditor');
	container.innerHTML = '';
	editorState.entities.forEach((entity, index) => {
		container.appendChild(renderEntityCard(entity, index));
	});
}

function renderEntityCard(entity, index) {
	const card = el('div', 'sw-card border border-slate-200 rounded-xl p-4 bg-slate-50 space-y-4');
	const header = el('div', 'flex items-center justify-between');
	header.appendChild(el('div', 'text-sm font-semibold text-slate-700', `Entity ${index + 1}`));
	const removeBtn = el('button', 'text-xs text-red-600 hover:underline', 'Remove');
	removeBtn.addEventListener('click', () => {
		editorState.entities.splice(index, 1);
		renderEntitiesEditor();
	});
	header.appendChild(removeBtn);
	card.appendChild(header);

	const typeSelect = renderSelect('Type', entity.type || 'peptide', ['peptide', 'molecule'], (value) => {
		entity.type = value;
		renderEntitiesEditor();
	});
	card.appendChild(typeSelect);

	const peptide = entity.peptide || { sequence_one_letter: null, sequence_three_letter: null, n_terminal_mod: null, c_terminal_mod: null, is_hydrogel: null };
	entity.peptide = peptide;
	const molecule = entity.molecule || { chemical_formula: null, smiles: null, inchi: null };
	entity.molecule = molecule;

	const peptideSection = el('div', 'grid grid-cols-1 md:grid-cols-2 gap-3');
	peptideSection.appendChild(renderInput('Sequence (one-letter)', peptide.sequence_one_letter || '', (value) => { peptide.sequence_one_letter = value || null; }));
	peptideSection.appendChild(renderInput('Sequence (three-letter)', peptide.sequence_three_letter || '', (value) => { peptide.sequence_three_letter = value || null; }));
	peptideSection.appendChild(renderInput('N-terminal mod', peptide.n_terminal_mod || '', (value) => { peptide.n_terminal_mod = value || null; }));
	peptideSection.appendChild(renderInput('C-terminal mod', peptide.c_terminal_mod || '', (value) => { peptide.c_terminal_mod = value || null; }));
	peptideSection.appendChild(renderCheckbox('Hydrogel', peptide.is_hydrogel === true, (value) => { peptide.is_hydrogel = value; }));
	card.appendChild(sectionBlock('Peptide', peptideSection));

	const moleculeSection = el('div', 'grid grid-cols-1 md:grid-cols-2 gap-3');
	moleculeSection.appendChild(renderInput('Chemical formula', molecule.chemical_formula || '', (value) => { molecule.chemical_formula = value || null; }));
	moleculeSection.appendChild(renderInput('SMILES', molecule.smiles || '', (value) => { molecule.smiles = value || null; }));
	moleculeSection.appendChild(renderInput('InChI', molecule.inchi || '', (value) => { molecule.inchi = value || null; }));
	card.appendChild(sectionBlock('Molecule', moleculeSection));

	const conditions = entity.conditions || { ph: null, concentration: null, concentration_units: null, temperature_c: null };
	entity.conditions = conditions;
	const conditionsSection = el('div', 'grid grid-cols-1 md:grid-cols-2 gap-3');
	conditionsSection.appendChild(renderInput('pH', conditions.ph ?? '', (value) => { conditions.ph = value ? Number(value) : null; }, 'number'));
	conditionsSection.appendChild(renderInput('Concentration', conditions.concentration ?? '', (value) => { conditions.concentration = value ? Number(value) : null; }, 'number'));
	conditionsSection.appendChild(renderInput('Concentration units', conditions.concentration_units || '', (value) => { conditions.concentration_units = value || null; }));
	conditionsSection.appendChild(renderInput('Temperature (C)', conditions.temperature_c ?? '', (value) => { conditions.temperature_c = value ? Number(value) : null; }, 'number'));
	card.appendChild(sectionBlock('Conditions', conditionsSection));

	const thresholds = entity.thresholds || { cac: null, cgc: null, mgc: null };
	entity.thresholds = thresholds;
	const thresholdsSection = el('div', 'grid grid-cols-1 md:grid-cols-2 gap-3');
	thresholdsSection.appendChild(renderInput('CAC', thresholds.cac ?? '', (value) => { thresholds.cac = value ? Number(value) : null; }, 'number'));
	thresholdsSection.appendChild(renderInput('CGC', thresholds.cgc ?? '', (value) => { thresholds.cgc = value ? Number(value) : null; }, 'number'));
	thresholdsSection.appendChild(renderInput('MGC', thresholds.mgc ?? '', (value) => { thresholds.mgc = value ? Number(value) : null; }, 'number'));
	card.appendChild(sectionBlock('Thresholds', thresholdsSection));

	card.appendChild(renderInput('Labels (comma separated)', (entity.labels || []).join(', '), (value) => { entity.labels = splitList(value); }));
	card.appendChild(renderInput('Morphology (comma separated)', (entity.morphology || []).join(', '), (value) => { entity.morphology = splitList(value); }));
	card.appendChild(renderInput('Validation methods (comma separated)', (entity.validation_methods || []).join(', '), (value) => { entity.validation_methods = splitList(value); }));
	card.appendChild(renderInput('Reported characteristics (comma separated)', (entity.reported_characteristics || []).join(', '), (value) => { entity.reported_characteristics = splitList(value); }));
	card.appendChild(renderTextarea('Process protocol', entity.process_protocol || '', (value) => { entity.process_protocol = value || null; }));

	card.appendChild(renderEvidenceEditor(entity));
	return card;
}

function renderEvidenceEditor(entity) {
	const wrapper = el('div', 'space-y-3');
	wrapper.appendChild(el('div', 'sw-kicker text-xs text-slate-600', 'Evidence'));

	const rows = entity._evidenceRows || [];
	const table = el('div', 'space-y-2');
	rows.forEach((row, idx) => {
		table.appendChild(renderEvidenceRow(entity, row, idx));
	});
	wrapper.appendChild(table);

	const addBtn = el('button', 'text-xs text-indigo-600 hover:underline', 'Add evidence row');
	addBtn.addEventListener('click', () => {
		entity._evidenceRows.push({ field: '', quote: '', section: '', page: '' });
		renderEntitiesEditor();
	});
	wrapper.appendChild(addBtn);
	return wrapper;
}

function renderEvidenceRow(entity, row, idx) {
	const container = el('div', 'sw-card border border-slate-200 bg-slate-50 p-3 grid grid-cols-1 md:grid-cols-4 gap-2 items-start');
	container.appendChild(renderInput('Field path', row.field || '', (value) => { row.field = value; }));
	container.appendChild(renderInput('Quote', row.quote || '', (value) => { row.quote = value; }));
	container.appendChild(renderInput('Section', row.section || '', (value) => { row.section = value; }));
	container.appendChild(renderInput('Page', row.page || '', (value) => { row.page = value; }, 'number'));
	const removeBtn = el('button', 'text-xs text-red-600 hover:underline mt-1', 'Remove');
	removeBtn.addEventListener('click', () => {
		entity._evidenceRows.splice(idx, 1);
		renderEntitiesEditor();
	});
	container.appendChild(removeBtn);
	return container;
}

function renderInput(label, value, onChange, type = 'text') {
	const wrapper = el('div', 'space-y-1');
	wrapper.appendChild(el('label', 'text-xs text-slate-500', label));
	const input = document.createElement('input');
	input.type = type;
	input.value = value;
	input.className = 'w-full rounded-md border border-slate-300 p-2 text-sm';
	input.addEventListener('input', (e) => {
		onChange(e.target.value);
		markDirty();
	});
	wrapper.appendChild(input);
	return wrapper;
}

function renderTextarea(label, value, onChange) {
	const wrapper = el('div', 'space-y-1');
	wrapper.appendChild(el('label', 'text-xs text-slate-500', label));
	const textarea = document.createElement('textarea');
	textarea.rows = 2;
	textarea.value = value;
	textarea.className = 'w-full rounded-md border border-slate-300 p-2 text-sm';
	textarea.addEventListener('input', (e) => {
		onChange(e.target.value);
		markDirty();
	});
	wrapper.appendChild(textarea);
	return wrapper;
}

function renderSelect(label, value, options, onChange) {
	const wrapper = el('div', 'space-y-1');
	wrapper.appendChild(el('label', 'text-xs text-slate-500', label));
	const select = document.createElement('select');
	select.className = 'w-full rounded-md border border-slate-300 p-2 text-sm';
	options.forEach((opt) => {
		const option = document.createElement('option');
		option.value = opt;
		option.textContent = opt;
		if (opt === value) option.selected = true;
		select.appendChild(option);
	});
	select.addEventListener('change', (e) => {
		onChange(e.target.value);
		markDirty();
	});
	wrapper.appendChild(select);
	return wrapper;
}

function renderCheckbox(label, checked, onChange) {
	const wrapper = el('label', 'flex items-center gap-2 text-xs text-slate-600');
	const checkbox = document.createElement('input');
	checkbox.type = 'checkbox';
	checkbox.checked = checked;
	checkbox.addEventListener('change', (e) => {
		onChange(e.target.checked);
		markDirty();
	});
	wrapper.appendChild(checkbox);
	wrapper.appendChild(document.createTextNode(label));
	return wrapper;
}

function sectionBlock(title, content) {
	const block = el('div', 'space-y-2');
	block.appendChild(el('div', 'sw-kicker text-xs text-slate-600', title));
	block.appendChild(content);
	return block;
}

function splitList(value) {
	return value
		.split(',')
		.map((item) => item.trim())
		.filter(Boolean);
}

function buildEvidenceRows(evidenceMap) {
	const rows = [];
	Object.entries(evidenceMap || {}).forEach(([field, items]) => {
		(items || []).forEach((item) => {
			rows.push({
				field,
				quote: item.quote || '',
				section: item.section || '',
				page: item.page ?? '',
			});
		});
	});
	return rows;
}

function buildEvidenceMap(rows) {
	const map = {};
	rows.forEach((row) => {
		if (!row.field || !row.quote) return;
		if (!map[row.field]) map[row.field] = [];
		map[row.field].push({
			quote: row.quote,
			section: row.section || null,
			page: row.page === '' ? null : Number(row.page),
		});
	});
	return Object.keys(map).length ? map : null;
}

async function handleSave() {
	const status = $('#saveStatus');
	const reason = $('#editReason').value.trim();
	const payload = deepClone(editorState);
	payload.comment = $('#commentField').value.trim() || null;

	if (!payload.paper || !Array.isArray(payload.entities)) {
		status.textContent = 'Invalid payload.';
		return;
	}

	payload.entities.forEach((entity) => {
		const rows = entity._evidenceRows || [];
		const invalidRow = rows.find((row) => (row.field && !row.quote) || (!row.field && row.quote));
		if (invalidRow) {
			throw new Error('Evidence rows must include both field and quote.');
		}
		entity.evidence = buildEvidenceMap(rows);
		delete entity._evidenceRows;
	});

	status.textContent = 'Saving...';
	try {
		const result = await editRun(currentRunId, payload, reason || null);
		isDirty = false;
		window.location.href = `/runs/${result.extraction_id}`;
	} catch (err) {
		status.textContent = err.message || 'Save failed';
	}
}

function el(tag, cls, text) {
	const e = document.createElement(tag);
	if (cls) e.className = cls;
	if (text !== undefined) e.textContent = text;
	return e;
}

async function init() {
	const runId = getRunIdFromPath();
	if (!runId) {
		$('#saveStatus').textContent = 'Invalid run ID';
		return;
	}
	currentRunId = runId;
	$('#backToRun').href = `/runs/${runId}`;

	const data = await getRun(runId);
	editorState = initState(data.run?.raw_json);
	renderEditor();
	$('#commentField').addEventListener('input', (event) => {
		editorState.comment = event.target.value;
		markDirty();
	});

	$('#addEntityBtn').addEventListener('click', () => {
		editorState.entities.push({
			type: 'peptide',
			peptide: {
				sequence_one_letter: null,
				sequence_three_letter: null,
				n_terminal_mod: null,
				c_terminal_mod: null,
				is_hydrogel: null,
			},
			molecule: {
				chemical_formula: null,
				smiles: null,
				inchi: null,
			},
			labels: [],
			morphology: [],
			conditions: { ph: null, concentration: null, concentration_units: null, temperature_c: null },
			thresholds: { cac: null, cgc: null, mgc: null },
			validation_methods: [],
			process_protocol: null,
			reported_characteristics: [],
			evidence: null,
			_evidenceRows: [],
		});
		renderEntitiesEditor();
		markDirty();
	});

	$('#saveBtn').addEventListener('click', handleSave);
}

init();

function markDirty() {
	isDirty = true;
}

window.addEventListener('beforeunload', (event) => {
	if (!isDirty) return;
	event.preventDefault();
	event.returnValue = '';
});
