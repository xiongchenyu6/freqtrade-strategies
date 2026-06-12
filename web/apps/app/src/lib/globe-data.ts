// 全球市场 globe data — exchange venues + news-source HQ cities.
// All coordinates and trading hours below are public facts (venue HQs,
// published regular sessions). Open/closed is computed from the venue's
// IANA timezone via Intl.DateTimeFormat, so DST is handled exactly.
// NOTE: regular sessions only — public holidays are NOT modelled.

export interface ExchangeVenue {
	id: string;
	name: string; // en
	zh: string;
	city: string;
	cityZh: string;
	lat: number;
	lng: number;
	tz: string; // IANA timezone
	/** Trading windows in venue-local minutes-from-midnight, [start, end). */
	sessions: [number, number][];
	/** ISO weekdays the venue trades (1=Mon … 7=Sun). */
	days: number[];
	/** Relative marker size on the globe. */
	weight: number;
	/** Session-hours label for the panel. */
	hours: string;
	note?: { zh: string; en: string };
}

const hm = (h: number, m: number) => h * 60 + m;

export const EXCHANGES: ExchangeVenue[] = [
	{
		id: 'nyse',
		name: 'NYSE',
		zh: '纽交所',
		city: 'New York',
		cityZh: '纽约',
		lat: 40.7069,
		lng: -74.0113,
		tz: 'America/New_York',
		sessions: [[hm(9, 30), hm(16, 0)]],
		days: [1, 2, 3, 4, 5],
		weight: 1.0,
		hours: '09:30–16:00 ET'
	},
	{
		id: 'nasdaq',
		name: 'NASDAQ',
		zh: '纳斯达克',
		city: 'New York',
		cityZh: '纽约',
		lat: 40.7569,
		lng: -73.9861,
		tz: 'America/New_York',
		sessions: [[hm(9, 30), hm(16, 0)]],
		days: [1, 2, 3, 4, 5],
		weight: 1.0,
		hours: '09:30–16:00 ET'
	},
	{
		id: 'cme',
		name: 'CME',
		zh: '芝商所',
		city: 'Chicago',
		cityZh: '芝加哥',
		lat: 41.8781,
		lng: -87.6298,
		tz: 'America/Chicago',
		// CME Globex runs nearly 23h (Sun 17:00 → Fri 16:00 CT with daily
		// 16:00–17:00 maintenance breaks). We show the main equity-index RTH
		// window and note it below.
		sessions: [[hm(8, 30), hm(15, 0)]],
		days: [1, 2, 3, 4, 5],
		weight: 0.9,
		hours: '08:30–15:00 CT (主要时段)',
		note: {
			zh: 'Globex 电子盘近 23 小时,此处标注主要时段',
			en: 'Globex runs nearly 23h; main session shown'
		}
	},
	{
		id: 'lse',
		name: 'LSE',
		zh: '伦交所',
		city: 'London',
		cityZh: '伦敦',
		lat: 51.5155,
		lng: -0.0922,
		tz: 'Europe/London',
		sessions: [[hm(8, 0), hm(16, 30)]],
		days: [1, 2, 3, 4, 5],
		weight: 0.9,
		hours: '08:00–16:30 London'
	},
	{
		id: 'xetra',
		name: 'Deutsche Börse (Xetra)',
		zh: '德交所',
		city: 'Frankfurt',
		cityZh: '法兰克福',
		lat: 50.1109,
		lng: 8.6821,
		tz: 'Europe/Berlin',
		sessions: [[hm(9, 0), hm(17, 30)]],
		days: [1, 2, 3, 4, 5],
		weight: 0.8,
		hours: '09:00–17:30 CET'
	},
	{
		id: 'six',
		name: 'SIX Swiss',
		zh: '瑞交所',
		city: 'Zurich',
		cityZh: '苏黎世',
		lat: 47.3769,
		lng: 8.5417,
		tz: 'Europe/Zurich',
		sessions: [[hm(9, 0), hm(17, 30)]],
		days: [1, 2, 3, 4, 5],
		weight: 0.6,
		hours: '09:00–17:30 CET'
	},
	{
		id: 'hkex',
		name: 'HKEX',
		zh: '港交所',
		city: 'Hong Kong',
		cityZh: '香港',
		lat: 22.2849,
		lng: 114.1577,
		tz: 'Asia/Hong_Kong',
		sessions: [
			[hm(9, 30), hm(12, 0)],
			[hm(13, 0), hm(16, 0)]
		],
		days: [1, 2, 3, 4, 5],
		weight: 0.9,
		hours: '09:30–12:00 / 13:00–16:00 HKT'
	},
	{
		id: 'sse',
		name: 'SSE',
		zh: '上交所',
		city: 'Shanghai',
		cityZh: '上海',
		lat: 31.2304,
		lng: 121.4737,
		tz: 'Asia/Shanghai',
		sessions: [
			[hm(9, 30), hm(11, 30)],
			[hm(13, 0), hm(15, 0)]
		],
		days: [1, 2, 3, 4, 5],
		weight: 0.9,
		hours: '09:30–11:30 / 13:00–15:00 CST'
	},
	{
		id: 'tse',
		name: 'TSE',
		zh: '东证',
		city: 'Tokyo',
		cityZh: '东京',
		lat: 35.6804,
		lng: 139.769,
		tz: 'Asia/Tokyo',
		sessions: [
			[hm(9, 0), hm(11, 30)],
			[hm(12, 30), hm(15, 0)]
		],
		days: [1, 2, 3, 4, 5],
		weight: 0.9,
		hours: '09:00–11:30 / 12:30–15:00 JST'
	},
	{
		id: 'sgx',
		name: 'SGX',
		zh: '新交所',
		city: 'Singapore',
		cityZh: '新加坡',
		lat: 1.2789,
		lng: 103.8508,
		tz: 'Asia/Singapore',
		sessions: [[hm(9, 0), hm(17, 0)]],
		days: [1, 2, 3, 4, 5],
		weight: 0.7,
		hours: '09:00–17:00 SGT'
	},
	{
		id: 'asx',
		name: 'ASX',
		zh: '澳交所',
		city: 'Sydney',
		cityZh: '悉尼',
		lat: -33.8651,
		lng: 151.2099,
		tz: 'Australia/Sydney',
		sessions: [[hm(10, 0), hm(16, 0)]],
		days: [1, 2, 3, 4, 5],
		weight: 0.7,
		hours: '10:00–16:00 AEST/AEDT'
	}
];

const WD: Record<string, number> = { Mon: 1, Tue: 2, Wed: 3, Thu: 4, Fri: 5, Sat: 6, Sun: 7 };

/** Venue-local clock: minutes from midnight + ISO weekday + HH:mm string. */
export function localClock(tz: string, now: Date = new Date()) {
	const parts = new Intl.DateTimeFormat('en-US', {
		timeZone: tz,
		hour: '2-digit',
		minute: '2-digit',
		hourCycle: 'h23',
		weekday: 'short'
	}).formatToParts(now);
	let h = 0,
		m = 0,
		wd = 0;
	for (const p of parts) {
		if (p.type === 'hour') h = Number(p.value);
		else if (p.type === 'minute') m = Number(p.value);
		else if (p.type === 'weekday') wd = WD[p.value] ?? 0;
	}
	return { minutes: h * 60 + m, weekday: wd, hhmm: `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}` };
}

/**
 * Regular-session open check (weekday + local-time windows via the venue's
 * IANA timezone — exact under DST). Holidays are NOT considered.
 */
export function isOpen(ex: ExchangeVenue, now: Date = new Date()): boolean {
	const { minutes, weekday } = localClock(ex.tz, now);
	if (!ex.days.includes(weekday)) return false;
	return ex.sessions.some(([a, b]) => minutes >= a && minutes < b);
}

// --- News-source HQ cities (public facts). Sources without a clear single
// HQ are intentionally omitted rather than guessed. ---

export interface NewsCity {
	city: string;
	cityZh: string;
	lat: number;
	lng: number;
	sources: string[];
}

const CITY: Record<string, { cityZh: string; lat: number; lng: number }> = {
	'New York': { cityZh: '纽约', lat: 40.7128, lng: -74.006 },
	Nashville: { cityZh: '纳什维尔', lat: 36.1627, lng: -86.7816 },
	'Washington DC': { cityZh: '华盛顿', lat: 38.8951, lng: -77.0364 },
	Frankfurt: { cityZh: '法兰克福', lat: 50.1109, lng: 8.6821 }
};

/** source name (as stored in quant.news_items) → HQ city key. */
export const SOURCE_HQ: Record<string, string> = {
	CoinDesk: 'New York',
	Cointelegraph: 'New York',
	Decrypt: 'New York',
	'The Block': 'New York',
	'Bitcoin Magazine': 'Nashville',
	Fed: 'Washington DC',
	SEC: 'Washington DC',
	ECB: 'Frankfurt',
	MarketWatch: 'New York',
	// CNBC HQ is Englewood Cliffs, NJ — metro New York; grouped under the
	// New York pin, source label stays "CNBC".
	CNBC: 'New York'
};

/** Group news sources into HQ city pins (only sources we can place honestly). */
export function newsCities(sources: Iterable<string>): NewsCity[] {
	const byCity = new Map<string, NewsCity>();
	for (const s of sources) {
		const cityKey = SOURCE_HQ[s];
		if (!cityKey) continue; // unknown HQ → no pin (never fabricate)
		let c = byCity.get(cityKey);
		if (!c) {
			const geo = CITY[cityKey];
			c = { city: cityKey, cityZh: geo.cityZh, lat: geo.lat, lng: geo.lng, sources: [] };
			byCity.set(cityKey, c);
		}
		if (!c.sources.includes(s)) c.sources.push(s);
	}
	return [...byCity.values()];
}
