import * as api from '../../api.js';

export const getHealth = () => api.getHealth();
export const createSSEConnection = (onMessage, onError) => api.createSSEConnection(onMessage, onError);
export const extractFile = (files, promptId, title, provider, model) =>
    api.extractFile(files, promptId, title, provider, model);
