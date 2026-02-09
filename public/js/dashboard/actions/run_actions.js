import * as api from '../../api.js';

export const getRuns = (paperId) => api.getRuns(paperId);
export const retryRun = (runId) => api.retryRun(runId);
export const resolveRunSource = (runId) => api.resolveRunSource(runId);
export const retryRunWithSource = (runId, payload) => api.retryRunWithSource(runId, payload);
export const uploadRunPdf = (runId, files, provider, promptId) => api.uploadRunPdf(runId, files, provider, promptId);
export const forceReextract = (paperId) => api.forceReextract(paperId);
export const retryFailedRuns = (payload) => api.retryFailedRuns(payload);
export const getFailedRuns = (filters) => api.getFailedRuns(filters);
export const getFailureSummary = (days, maxRuns) => api.getFailureSummary(days, maxRuns);
