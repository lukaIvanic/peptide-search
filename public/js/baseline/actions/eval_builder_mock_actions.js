import * as api from '../../api.js';

const GROUP_ID_PATTERN = /^[a-z0-9_-]+$/;

function _asText(value) {
  if (value === null || value === undefined) return '';
  return String(value).trim();
}

function _parseLabelsCsv(value) {
  return _asText(value)
    .split(',')
    .map((part) => part.trim())
    .filter(Boolean);
}

function _fileMeta(file) {
  if (!file) return null;
  return {
    name: file.name,
    size: file.size,
    type: file.type || 'application/octet-stream',
  };
}

function _log(action, payload) {
  const prefix = `[eval-builder-mock] ${action}`;
  console.log(prefix);
  console.log(JSON.stringify(payload, null, 2));
}

export function validateGroupDraft(draft) {
  const errors = [];
  const id = _asText(draft?.id);
  const label = _asText(draft?.label);

  if (!id) {
    errors.push('Group ID is required.');
  } else if (!GROUP_ID_PATTERN.test(id)) {
    errors.push('Group ID must match [a-z0-9_-].');
  }

  if (!label) {
    errors.push('Group label is required.');
  }

  return { ok: errors.length === 0, errors };
}

export function validatePaperDraft(draft) {
  const errors = [];
  const mode = _asText(draft?.mode) || 'create_paper';
  const title = _asText(draft?.title);
  const mainPdfFile = draft?.main_pdf_file || null;
  const entities = Array.isArray(draft?.ground_truth_entities) ? draft.ground_truth_entities : [];

  if (!title) {
    errors.push('Paper title is required.');
  }

  if (mode === 'create_paper' && !mainPdfFile) {
    errors.push('Main PDF is required for create mode.');
  }

  if (!entities.length) {
    errors.push('At least one ground-truth entity is required.');
  }

  entities.forEach((entity, index) => {
    if (!_asText(entity?.sequence)) {
      errors.push(`Entity #${index + 1}: sequence is required.`);
    }
  });

  return { ok: errors.length === 0, errors };
}

export function buildGroupPayload(draft) {
  return {
    dataset_id: _asText(draft?.id),
    label: _asText(draft?.label),
    description: _asText(draft?.description) || null,
  };
}

export function buildPaperPayload(draft) {
  const entities = Array.isArray(draft?.ground_truth_entities) ? draft.ground_truth_entities : [];
  const supporting = Array.isArray(draft?.supporting_pdf_files) ? draft.supporting_pdf_files : [];
  const mainFile = draft?.main_pdf_file || null;

  return {
    mode: _asText(draft?.mode) || 'create_paper',
    selected_dataset_id: _asText(draft?.selected_dataset_id) || null,
    selected_paper_key: _asText(draft?.selected_paper_key) || null,
    paper: {
      title: _asText(draft?.title),
      doi: _asText(draft?.doi) || null,
      paper_url: _asText(draft?.paper_url) || null,
    },
    files: {
      main_pdf: _fileMeta(mainFile),
      supporting_pdfs: supporting.map(_fileMeta).filter(Boolean),
      main_pdf_file: mainFile,
      supporting_pdf_files: supporting,
    },
    ground_truth_entities: entities.map((entity) => ({
      sequence: _asText(entity?.sequence),
      n_terminal: _asText(entity?.n_terminal) || null,
      c_terminal: _asText(entity?.c_terminal) || null,
      labels: _parseLabelsCsv(entity?.labels_csv),
      notes: _asText(entity?.notes) || null,
    })),
  };
}

export async function submitCreateGroupMock(payload) {
  _log('create-group', payload);
  return api.upsertBaselineDataset({
    dataset_id: _asText(payload?.dataset_id),
    label: _asText(payload?.label),
    description: _asText(payload?.description) || null,
  });
}

export async function submitSavePaperMock(payload) {
  _log('save-paper', payload);
  const formData = new FormData();
  formData.append('mode', _asText(payload?.mode) || 'create_paper');
  formData.append('dataset_id', _asText(payload?.selected_dataset_id));
  if (_asText(payload?.selected_paper_key)) {
    formData.append('selected_paper_key', _asText(payload?.selected_paper_key));
  }
  formData.append('title', _asText(payload?.paper?.title));
  if (_asText(payload?.paper?.doi)) formData.append('doi', _asText(payload?.paper?.doi));
  if (_asText(payload?.paper?.paper_url)) formData.append('paper_url', _asText(payload?.paper?.paper_url));

  const entities = Array.isArray(payload?.ground_truth_entities) ? payload.ground_truth_entities : [];
  formData.append('entities_json', JSON.stringify(entities));

  const mainFile = payload?.files?.main_pdf_file || payload?.main_pdf_file || null;
  if (mainFile instanceof File) {
    formData.append('main_pdf', mainFile, mainFile.name);
  }

  const supportingFiles = Array.isArray(payload?.files?.supporting_pdf_files)
    ? payload.files.supporting_pdf_files
    : Array.isArray(payload?.supporting_pdf_files)
      ? payload.supporting_pdf_files
      : [];
  supportingFiles.forEach((file) => {
    if (file instanceof File) {
      formData.append('supporting_pdfs', file, file.name);
    }
  });

  return api.saveBaselinePaperGroup(formData);
}

export async function submitDeleteGroupMock(payload) {
  _log('delete-group', payload);
  return api.deleteBaselineDataset(_asText(payload?.dataset_id));
}

export async function submitDeletePaperMock(payload) {
  _log('delete-paper', payload);
  const paperKey = _asText(payload?.paper_key);
  if (!paperKey) throw new Error('paper_key is required');
  return api.deleteBaselinePaper(paperKey);
}
