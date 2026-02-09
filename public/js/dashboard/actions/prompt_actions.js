import * as api from '../../api.js';

export const getPrompts = () => api.getPrompts();
export const createPrompt = (payload) => api.createPrompt(payload);
export const createPromptVersion = (promptId, payload) => api.createPromptVersion(promptId, payload);
export const activatePrompt = (promptId) => api.activatePrompt(promptId);
