import * as api from '../../api.js';

export const search = (query, rows = 10) => api.search(query, rows);
export const enqueue = (papers, provider = 'openai', promptId = null, model = null) =>
    api.enqueue(papers, provider, promptId, model);
export const getPapers = () => api.getPapers();
