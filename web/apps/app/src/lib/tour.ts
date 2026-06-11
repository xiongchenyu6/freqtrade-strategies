// Relaunch handle for the first-login onboarding tour.
// Pages set this to true to force the tour open regardless of the
// localStorage done-flag (e.g. the "replay" button on /start); the
// onboarding-tour component resets it to false when the tour closes.
import { writable } from 'svelte/store';

export const tourOpen = writable(false);
