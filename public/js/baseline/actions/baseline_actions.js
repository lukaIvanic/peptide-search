import * as api from '../../api.js';

export const get = (path, opts) => api.get(path, opts);
export const post = (path, body, opts) => api.post(path, body, opts);
export const createSSEConnection = (onMessage, onError) => api.createSSEConnection(onMessage, onError);
export const getBaselineCases = (dataset) => api.getBaselineCases(dataset);
export const getBaselineLatestRun = (caseId) => api.getBaselineLatestRun(caseId);
export const getBaselineCase = (caseId) => api.getBaselineCase(caseId);
export const createBaselineCase = (payload) => api.createBaselineCase(payload);
export const updateBaselineCase = (caseId, payload) => api.updateBaselineCase(caseId, payload);
export const deleteBaselineCase = (caseId, expectedUpdatedAt) => api.deleteBaselineCase(caseId, expectedUpdatedAt);
export const deleteBaselinePaper = (paperKey) => api.deleteBaselinePaper(paperKey);
export const getBaselineRecomputeStatus = () => api.getBaselineRecomputeStatus();
export const resetBaselineDefaults = () => api.resetBaselineDefaults();
export const getBaselineLocalPdfInfo = (caseId) => api.getBaselineLocalPdfInfo(caseId);
export const getBaselineLocalPdfUrl = (caseId) => api.getBaselineLocalPdfUrl(caseId);
export const getBaselineLocalPdfSiInfo = (caseId) => api.getBaselineLocalPdfSiInfo(caseId);
export const getBaselineLocalPdfSiUrl = (caseId, index = 0) => api.getBaselineLocalPdfSiUrl(caseId, index);
export const resolveBaselineSource = (caseId, options = {}) => api.resolveBaselineSource(caseId, options);
export const retryBaselineCase = (caseId, payload = {}) => api.retryBaselineCase(caseId, payload);
export const uploadBaselinePdf = (caseId, file, provider, promptId) => api.uploadBaselinePdf(caseId, file, provider, promptId);
export const enqueueBaselineAll = (provider = 'openai', promptId = null, dataset = null, force = false) =>
  api.enqueueBaselineAll(provider, promptId, dataset, force);
export const forceReextract = (paperId, provider) => api.forceReextract(paperId, provider);
