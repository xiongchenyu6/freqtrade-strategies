import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
	return twMerge(clsx(inputs));
}

export function fmtUSD(n: number | null | undefined): string {
	if (n == null) return '—';
	return '$' + Math.round(n).toLocaleString();
}
export function fmtPct(n: number | null | undefined, digits = 2): string {
	if (n == null) return '—';
	return `${n >= 0 ? '+' : ''}${n.toFixed(digits)}%`;
}
export function fmtTime(iso: string | null | undefined): string {
	if (!iso) return '—';
	return iso.replace('T', ' ').slice(0, 16);
}
export function agoText(iso: string): string {
	if (!iso) return '';
	const diff = (Date.now() - new Date(iso).getTime()) / 60_000;
	if (diff < 60) return `${Math.floor(diff)}m ago`;
	if (diff < 1440) return `${Math.floor(diff / 60)}h ago`;
	return `${Math.floor(diff / 1440)}d ago`;
}
