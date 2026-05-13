// Shared row types for the public API (mirrors migration 002 + 007 views).

/** Aggregate snapshot exposed to anon via api.public_stats. */
export interface PublicStats {
	total_runs: number;
	total_trades: number;
	distinct_strategies: number;
	best_profit_pct: number | null;
	best_calmar: number | null;
	best_sharpe: number | null;
	best_sortino: number | null;
	best_win_rate: number | null;
	min_max_dd: number | null;
	last_updated: string;
}

export interface BacktestRun {
	id: number;
	job_id: string | null;
	strategy: string;
	timeframe: string | null;
	timerange: string | null;
	started_at: string | null;
	finished_at: string | null;
	duration_sec: number | null;
	total_trades: number | null;
	wins: number | null;
	losses: number | null;
	win_rate_pct: number | null;
	total_profit_pct: number | null;
	total_profit_abs: number | null;
	max_drawdown_pct: number | null;
	calmar: number | null;
	sharpe: number | null;
	sortino: number | null;
	profit_factor: number | null;
	pairs: string[] | null;
	factors: string[] | null;
	imported_at: string;
}

export interface BacktestTrade {
	run_id: number;
	trade_id: number;
	pair: string;
	is_short: boolean;
	open_date: string;
	close_date: string | null;
	open_rate: number | null;
	close_rate: number | null;
	stake_amount: number | null;
	profit_abs: number | null;
	profit_pct: number | null;
	exit_reason: string | null;
	enter_tag: string | null;
	trade_duration_min: number | null;
}

export interface OhlcRow {
	pair: string;
	bucket: string; // ISO ts
	open: number;
	high: number;
	low: number;
	close: number;
	volume: number;
}

export interface LiveTrade {
	bot_name: string;
	pair: string;
	is_short: boolean;
	strategy: string | null;
	open_date: string;
	close_date: string | null;
	open_rate: number | null;
	close_rate: number | null;
	stake_amount: number | null;
	profit_abs: number | null;
	profit_pct: number | null;
	exit_reason: string | null;
	synced_at: string;
}

export interface WfResult {
	id: number;
	run_date: string;
	strategy: string;
	timeframe: string;
	window_label: string;
	window_start: string;
	window_end: string;
	status: 'ok' | 'failed' | string;
	trades: number | null;
	tot_profit_pct: number | null;
	tot_profit_usdt: number | null;
	avg_profit_pct: number | null;
}

export interface EventDcaTrigger {
	ts: string;
	kind: 'FLASH' | 'FAST' | 'SUSTAIN' | 'CAPITUL' | string;
	price: number | null;
	severity: number | null;
	fng: number | null;
	amount_usdt: number | null;
	mode: string | null;
}

// Supabase-side events
export interface KolEvent {
	id: number;
	timestamp: string;
	kol: string;
	sentiment: string | null;
	score: number | null;
	title: string;
	source: string | null;
}

export interface HyperoptEpoch {
	id: string;
	strategy: string;
	file_ts: string;
	epoch: number;
	is_best: boolean | null;
	is_initial_point: boolean | null;
	is_random: boolean | null;
	loss: number | null;
	params: Record<string, number> | null;
	sharpe: number | null;
	calmar: number | null;
	sortino: number | null;
	sqn: number | null;
	profit_total: number | null;
	winrate: number | null;
	total_trades: number | null;
	max_drawdown: number | null;
	holding_avg_hours: number | null;
	results_explanation: string | null;
	synced_at: string;
}

export interface DcaLogRow {
	id: number;
	timestamp: string;
	mode: string;
	base_usdt: number;
	multiplier: number;
	amount_usdt: number;
	fng_value: number | null;
	cycle_score: number | null;
	cycle_signal: string | null;
	explain: Record<string, unknown> | null;
	order_result: unknown | null;
}

// Kelly sizing verdict — generated server-side by
// strategies/telegram_alerts.py --write-kelly-status. Refreshed on every
// daily-report run; the file lives at static/data/kelly_status.json.
export interface KellyStatusEntry {
	name: string;
	status: 'ok' | 'negative_edge' | 'insufficient_n' | 'no_data';
	verdict: string;
	win_rate?: number;
	payoff_ratio?: number;
	n_trades?: number;
	f_half_point?: number;
	f_half_shrunk?: number;
	error?: string;
}

export interface KellyStatusFile {
	generated_at: string;
	min_trades_for_kelly: number;
	wilson_z: number;
	strategies: KellyStatusEntry[];
	error?: string;
}
