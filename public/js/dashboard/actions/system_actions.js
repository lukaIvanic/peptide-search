import * as api from '../../api.js';

export const getHealth = () => api.getHealth();
export const createSSEConnection = (handlers) => api.createSSEConnection(handlers);
export const extractFile = (files, promptId, title) => api.extractFile(files, promptId, title);
