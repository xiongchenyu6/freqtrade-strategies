<script lang="ts">
	// 策略墓地 — the trust artifact. Copy-trading leaderboards delete blown-up
	// traders; we publish every strategy we tried and abandoned, with post-mortems.
	// Static bilingual content sourced from docs/RETIRED_STRATEGIES.md; no server load.
	import { page } from '$app/stores';
	import { type Lang } from '$lib/i18n';

	const lang = $derived<Lang>($page.data.lang ?? 'zh');
	const en = $derived(lang === 'en');

	type B = { zh: string; en: string };

	// --- The 5 patterns that fooled us (TL;DR of the retirement doc) ---
	const PATTERNS: B[] = [
		{
			zh: '样本内盈利因子(PF)> 3 → 几乎必然过拟合。样本内和样本外的差距,90% 是噪音。',
			en: 'In-sample profit factor > 3.0 → almost always overfit. 90% of the gap between IS and OOS is noise.'
		},
		{
			zh: 'Calmar > 20 是红灯,不是卖点 —— 说明样本太小,还没遇到真正的回撤。',
			en: 'Calmar > 20 is a red flag, not a feature — it means the sample is too small to have hit a real drawdown yet.'
		},
		{
			zh: '样本内 p < 0.0001 → 在样本内数据上谈统计显著性,是循环论证。',
			en: 'p-value < 0.0001 in-sample → statistical significance on in-sample data is circular reasoning.'
		},
		{
			zh: '单个样本外窗口盈利 → 一个幸运季度能掩盖四个亏损季度。永远走 walk-forward。',
			en: 'A single profitable OOS window → one lucky quarter can hide four losing quarters. Always walk-forward.'
		},
		{
			zh: 'LLM 情绪信号("极端时逆向"提示词):Claude 不管什么行情,96% 的情况都回答 contrarian=true —— 所谓信号只是加了步骤的随机噪音。',
			en: '"Contrarian at extremes" LLM prompts: Claude sets contrarian=true 96% of the time regardless of the prompt — the signal is random noise with extra steps.'
		}
	];

	// --- Strategy families ---
	type FamilyId = 'sentiment' | 'early' | 'dead' | 'honest';
	const FAMILIES: { id: FamilyId; label: B; note?: B }[] = [
		{
			id: 'sentiment',
			label: { zh: '情绪 / ML 过拟合家族', en: 'Sentiment / ML overfit cluster' },
			note: {
				zh: '这里的每一个策略都至少通过过一项上面的"看起来很棒"测试,然后在现实里失败。',
				en: 'Every strategy here passed at least one of the "looks great" tests above — and still failed in reality.'
			}
		},
		{
			id: 'early',
			label: { zh: '早期迭代', en: 'Early iterations' },
			note: {
				zh: '被后续架构取代的雏形 —— 不是因为亏钱而死,而是因为不够好。',
				en: 'Prototypes superseded by later architecture — retired not for losing money, but for not being good enough.'
			}
		},
		{
			id: 'dead',
			label: { zh: '死掉的优势', en: 'Dead edges' },
			note: {
				zh: '看起来是真的,其实不是。统计上最漂亮的尸体埋在这里。',
				en: 'Looked real, weren’t. The statistically prettiest corpse is buried here.'
			}
		},
		{
			id: 'honest',
			label: { zh: 'HonestTrend 早期版本', en: 'HonestTrend earlier variants' },
			note: {
				zh: '这些版本早于 HonestTrendGeneric + 风控框架。它们是梯子上的横档,不是梯子本身。',
				en: 'These predate the HonestTrendGeneric + risk-manager architecture. They were rungs on the ladder, not the ladder itself.'
			}
		}
	];

	type Grave = {
		file: string;
		family: FamilyId;
		sub?: B; // short descriptor
		why: B; // 死因
		looked?: B; // 当时看起来
		happened?: B; // 实际发生
		lesson: B; // 📌 教训
	};

	const GRAVES: Grave[] = [
		// --- Sentiment / ML family (overfit cluster) ---
		{
			file: 'SentimentTrend.py',
			family: 'sentiment',
			sub: { zh: '实盘模式 LLM 情绪策略', en: 'Live-mode sentiment strategy with LLM signals' },
			why: {
				zh: '样本内 PF 6.86,样本外塌到约 1.05。',
				en: 'PF 6.86 in-sample collapsed to ~1.05 OOS.'
			},
			looked: {
				zh: '手工 FnG 闸门 + LLM 情绪 + 反思记忆 + BTC 周期指标的组合,200+ 个特征。',
				en: 'Combined a hand-crafted FnG gate + LLM sentiment + reflective memory + BTC cycle indicators → 200+ features.'
			},
			happened: {
				zh: '特征重要性分析显示:LLM 信号贡献为 0%,与 FnG 完全冗余。大多数"特征"只是恰好与 2024 年牛市价格相关的噪音。',
				en: 'Feature-importance analysis showed the LLM signal contributed 0% — redundant with FnG. Most "features" were noise that happened to correlate with price in the 2024 bull market.'
			},
			lesson: {
				zh: '加特征 ≠ 加优势。永远做消融实验(ablation)。',
				en: 'Adding features ≠ adding edge. Always ablate.'
			}
		},
		{
			file: 'SentimentTrendBT.py / SentimentTrendBT.json',
			family: 'sentiment',
			why: {
				zh: 'SentimentTrend.py 的可回测版本,用历史 FnG + 重建的 LLM 输出。测了 v1–v6 共 6 个变体,没有一个有样本外优势。',
				en: 'Backtestable version of SentimentTrend.py, using historical FnG + reconstructed LLM outputs. Tested 6 variants (v1–v6); none had OOS edge.'
			},
			lesson: {
				zh: '历史情绪重建是一个会泄漏的抽象(leaky abstraction)。',
				en: 'Historical sentiment reconstruction is a leaky abstraction.'
			}
		},
		{
			file: 'SentimentUltimate.py',
			family: 'sentiment',
			why: {
				zh: '手工特征 + FreqAI LightGBM 分类器的混合。样本内 PF 6.86 → 样本外 PF 1.05。教科书级过拟合。',
				en: 'Hand-crafted + FreqAI LightGBM classifier hybrid. In-sample PF 6.86 → OOS PF 1.05. Textbook overfitting.'
			},
			lesson: {
				zh: '在没有先验经济逻辑的特征上跑 ML = 拟合噪音。',
				en: 'ML on features with no a-priori economic thesis = noise-fit.'
			}
		},
		{
			file: 'SentimentHybrid.py',
			family: 'sentiment',
			why: {
				zh: '更早的混合尝试,从未通过样本外检验。',
				en: 'Earlier hybrid attempt. Never passed OOS.'
			},
			lesson: {
				zh: '不能用训练模型的那份数据来验证模型。',
				en: 'You can’t validate an ML model on the same data you trained it on.'
			}
		},
		{
			file: 'SentimentRL.py / SentimentRL1h.py',
			family: 'sentiment',
			why: {
				zh: 'PPO / A2C 强化学习智能体。样本内学会了"加了步骤的买入持有";样本外:彻底亏损,然后躺平不动。',
				en: 'PPO/A2C reinforcement-learning agents. Learned "buy-and-hold with extra steps" in-sample. OOS: total loss, then gave up.'
			},
			lesson: {
				zh: '在小样本金融数据(区区几百万个 tick)上,RL 会灾难性过拟合。你需要跨多个市场的数百万个 episode 才够。',
				en: 'RL on small financial samples (a few million ticks) overfits catastrophically. You’d need millions of episodes across many markets.'
			}
		},
		{
			file: 'SentimentFreqAI.py / SentimentFreqAIClassifier.py',
			family: 'sentiment',
			why: {
				zh: 'FreqAI 流水线,LightGBM、XGBoost、PyTorch MLP、Transformer 全试了。样本内拟合都很漂亮(Calmar > 50),样本外全部消失。',
				en: 'FreqAI pipelines with LightGBM, XGBoost, PyTorch MLP, Transformer. All produced beautiful in-sample fits (Calmar > 50) that vanished out-of-sample.'
			},
			lesson: {
				zh: 'n < 5000 个样本配 50+ 个特征,ML 模型只会记忆,不会泛化。没有例外。',
				en: 'ML models trained on n < 5000 examples with 50+ features will memorize, not generalize. Guaranteed.'
			}
		},
		// --- Early iterations (superseded) ---
		{
			file: 'TrendFollowEMA.py',
			family: 'early',
			why: {
				zh: '最早的趋势跟踪策略,被 HonestTrendGeneric 及其子类替代。功能相似,但没有 FnG 防御、风控集成和 walk-forward 验证。',
				en: 'Earliest trend-follower; replaced by HonestTrendGeneric and its subclasses. Functionally similar but without FnG defense, risk-manager integration, or walk-forward validation.'
			},
			lesson: {
				zh: '任何策略的第一版都是原型,不是产品。',
				en: 'The first version of any strategy is a prototype, not a product.'
			}
		},
		{
			file: 'DonchianBreakout.py',
			family: 'early',
			why: {
				zh: '日线级别的突破尝试。每年约 8 笔交易,太少,没法验证。样本外结论不明。',
				en: 'Breakout attempts on the daily timeframe. Too few trades/year (~8) to validate. OOS inconclusive.'
			},
			lesson: {
				zh: '交易频率太低时,不管表面结果多好,回测在统计上都是没用的。',
				en: 'Low trade frequency makes any backtest statistically useless regardless of apparent results.'
			}
		},
		// --- Dead edges (looked real, weren't) ---
		{
			file: 'PairMeanReversion.py',
			family: 'dead',
			sub: { zh: 'ETH/BTC 均值回归', en: 'ETH/BTC mean reversion' },
			why: {
				zh: '均值回归假设在 2025 年被持续的 ETH/BTC 单边趋势打破。样本外:亏钱。',
				en: 'The mean-reversion assumption broke under 2025’s persistent ETH/BTC trend drift. OOS: lost money.'
			},
			looked: {
				zh: 'ETH/BTC z-score 均值回归:z < −2 时买 ETH(ETH 相对 BTC 低估),z 回到 0 时退出。诱人的统计:样本内 p < 0.0001(n=2382,平均每周 +0.96%)。',
				en: 'ETH/BTC z-score mean reversion: buy ETH when z < −2 (ETH undervalued vs BTC), exit when z reverts to 0. The seductive stat: p < 0.0001 in-sample (n=2382, avg +0.96% per week).'
			},
			happened: {
				zh: '2025 年 ETH/BTC 出现持续的单边趋势漂移,均值回归的前提不复存在。',
				en: '2025 saw persistent ETH/BTC trend drift; the mean-reversion premise stopped existing.'
			},
			lesson: {
				zh: '历史数据上的统计显著性,不保证底层市场状态(regime)会持续。"每个策略都死于坠崖"(Taleb)。永远给 regime 变化留一个 kill-switch。',
				en: 'Statistical significance on historical data does not guarantee the underlying regime persists. "Every strategy dies cliff-fall" (Taleb). Always have a kill-switch on regime change.'
			}
		},
		// --- HonestTrend earlier variants ---
		{
			file: 'HonestTrend.py',
			family: 'honest',
			sub: { zh: '日线', en: 'daily' },
			why: {
				zh: '每年约 10 笔交易。两年下来 n=20,什么都验证不了。',
				en: '~10 trades/year. Can’t validate anything with n=20 across 2 years.'
			},
			lesson: {
				zh: '日线级趋势跟踪、3 个交易对,样本量不足以做任何显著性检验。',
				en: 'Daily-timeframe trend following on 3 pairs gives insufficient sample for significance tests.'
			}
		},
		{
			file: 'HonestTrend1h.py',
			family: 'honest',
			sub: { zh: '1 小时', en: '1h' },
			why: {
				zh: '多组参数下样本外 −14% 到 −25%。Stage 2 跨周期测试后来证实:这个优势在 1h 级别完全失效,与 EMA 参数选择无关。',
				en: 'OOS −14% to −25% across multiple parameter choices. The Stage 2 cross-timeframe test later confirmed: the 1h timeframe completely fails for this edge, regardless of EMA choice.'
			},
			lesson: {
				zh: '"信号在 X 周期有效"往往其实是"执行在 X 周期有效"的简写。延迟是致命的。',
				en: '"Signal works at X timeframe" is often shorthand for "execution works at X timeframe". Latency kills.'
			}
		},
		{
			file: 'HonestTrend1m.py',
			family: 'honest',
			sub: { zh: '1 分钟,原始版', en: '1m, original' },
			why: {
				zh: '被 HonestTrend1mLive.py 子类替代。这是风控框架出现之前的原始版本。',
				en: 'Superseded by the HonestTrend1mLive.py subclass. This was the original before the risk-manager framework.'
			},
			lesson: {
				zh: '风控要在部署前加,不是部署后。',
				en: 'Add risk-management before you deploy, not after.'
			}
		},
		{
			file: 'HonestTrend15m.py + .json',
			family: 'honest',
			sub: { zh: '15 分钟,原始版', en: '15m, original' },
			why: {
				zh: '被 HonestTrend15mDry.py 替代。这是 hyperopt 拟合版(EMA 94/139,比率 1.48x)—— 当时我们还不知道这个拟合是不是真的。',
				en: 'Superseded by HonestTrend15mDry.py. This was the hyperopt-fitted version (EMA 94/139, ratio 1.48x) before we understood whether the fit was real.'
			},
			lesson: {
				zh: 'hyperopt 的结果必须先通过 walk-forward 验证,才能被当作"正式参数"。',
				en: 'Hyperopt results must be walk-forward validated before being treated as "the" parameters.'
			}
		},
		{
			file: 'HonestTrend15m_2xRatio.py + .json',
			family: 'honest',
			why: {
				zh: '完成使命后退役 —— 它证明了优势是真的(非 hyperopt 的 2x 比率组合在样本外也盈利),但不如 1.48x 比率稳健。',
				en: 'Served its purpose — proved the edge is real (non-hyperopt 2x ratios also profit OOS) but not as robust as the 1.48x ratio.'
			},
			looked: {
				zh: 'Stage 1 测试脚手架:固定 slow = 2×fast,fast 在 24、48、72、96、128、160 之间变化。',
				en: 'Stage 1 testing artifact: fixed slow = 2×fast, varied fast across 24, 48, 72, 96, 128, 160.'
			},
			lesson: {
				zh: '测试脚手架要和生产代码分开放。',
				en: 'Keep testing scaffolding separate from production code.'
			}
		},
		{
			file: 'HonestTrend4h.py',
			family: 'honest',
			sub: { zh: '4 小时', en: '4h' },
			why: {
				zh: '样本外 PF 最高(1.74),但每年只有约 15 笔交易,不足以做有意义的验证。不是坏策略,只是数据不够、无法信任。',
				en: 'Best PF (1.74 OOS) but only ~15 trades/year. Too few for meaningful validation. Not a bad strategy; just not enough data to trust.'
			},
			lesson: {
				zh: '15 笔交易上的 PF 1.74,意味着 PF 的 95% 置信区间大约是 [0.7, 4.5]。等于没说。',
				en: 'A 1.74 PF over 15 trades means your 95% CI on PF is roughly [0.7, 4.5]. Useless.'
			}
		}
	];

	// --- Family filter tabs ---
	let activeFamily = $state<'all' | FamilyId>('all');
	const visibleFamilies = $derived(
		FAMILIES.filter((f) => activeFamily === 'all' || f.id === activeFamily)
	);
	function gravesOf(id: FamilyId): Grave[] {
		return GRAVES.filter((g) => g.family === id);
	}
	function pick(b: B): string {
		return en ? b.en : b.zh;
	}
</script>

<svelte:head>
	<title>{en ? 'Strategy graveyard' : '策略墓地'} · Crypto Quant</title>
</svelte:head>

<main class="mx-auto mt-12 max-w-3xl px-5 pb-16">
	<!-- Header -->
	<h1 class="text-2xl font-bold tracking-tight sm:text-3xl">
		<span aria-hidden="true">🪦</span>
		{en ? 'Strategy graveyard' : '策略墓地'}
	</h1>
	<p class="mt-4 text-sm leading-relaxed text-muted-foreground sm:text-base">
		{en
			? 'Copy-trading platforms delete the traders who blow up. We do the opposite — every strategy we tried and abandoned is published here, with its cause of death. The failures are as much a part of the real track record as the wins.'
			: '跟单平台会删掉爆仓的交易员;我们反过来 —— 公开展示自己试过并放弃的每一个策略,和它们的死因。失败记录和盈利记录一样,都是真实的一部分。'}
	</p>
	<p class="mt-2 text-xs text-muted-foreground">
		{en
			? 'The code for these strategies has been deleted (2026-04-22); this page is the only record that remains.'
			: '这些策略的代码已删除(2026-04-22),本页是它们仅存的记录。'}
	</p>

	<!-- The 5 patterns that fooled us -->
	<section class="mt-10">
		<h2 class="text-lg font-semibold tracking-tight">
			{en ? 'The 5 patterns that fooled us' : '骗过我们的 5 个模式'}
		</h2>
		<p class="mt-1.5 text-sm text-muted-foreground">
			{en
				? 'Every strategy below passed at least one of these "looks great" tests — and still failed in reality.'
				: '下面的每个策略,都至少通过过其中一项"看起来很棒"的测试 —— 然后在现实里失败。'}
		</p>
		<ol class="mt-4 flex flex-col gap-3">
			{#each PATTERNS as p, i (i)}
				<li class="flex items-start gap-3 rounded-xl border border-border bg-card p-4">
					<span
						class="mt-0.5 grid h-6 w-6 shrink-0 place-items-center rounded-full bg-[color-mix(in_oklab,var(--loss)_15%,transparent)] font-mono text-xs font-bold text-[var(--loss)]"
						aria-hidden="true"
					>
						{i + 1}
					</span>
					<p class="text-sm leading-relaxed">{pick(p)}</p>
				</li>
			{/each}
		</ol>
	</section>

	<!-- Graves, grouped by family -->
	<section class="mt-12">
		<div class="flex flex-wrap items-center justify-between gap-3">
			<h2 class="text-lg font-semibold tracking-tight">
				{en ? 'The graves' : '墓碑'}
				<span class="ml-1.5 text-sm font-normal text-muted-foreground">
					{GRAVES.length}
					{en ? 'strategies' : '个策略'}
				</span>
			</h2>
			<!-- Family tab chips -->
			<div class="flex flex-wrap gap-2">
				<button
					type="button"
					onclick={() => (activeFamily = 'all')}
					class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
					class:bg-primary={activeFamily === 'all'}
					class:text-primary-foreground={activeFamily === 'all'}
					class:bg-secondary={activeFamily !== 'all'}
					class:text-muted-foreground={activeFamily !== 'all'}
					class:border={activeFamily !== 'all'}
					class:border-border={activeFamily !== 'all'}
				>
					{en ? 'All' : '全部'}
				</button>
				{#each FAMILIES as f (f.id)}
					<button
						type="button"
						onclick={() => (activeFamily = f.id)}
						class="rounded-full px-3 py-1 text-xs font-medium transition-colors"
						class:bg-primary={activeFamily === f.id}
						class:text-primary-foreground={activeFamily === f.id}
						class:bg-secondary={activeFamily !== f.id}
						class:text-muted-foreground={activeFamily !== f.id}
						class:border={activeFamily !== f.id}
						class:border-border={activeFamily !== f.id}
					>
						{pick(f.label)}
					</button>
				{/each}
			</div>
		</div>

		{#each visibleFamilies as fam (fam.id)}
			<div class="mt-8">
				<h3 class="font-semibold tracking-tight">{pick(fam.label)}</h3>
				{#if fam.note}
					<p class="mt-1 text-sm text-muted-foreground">{pick(fam.note)}</p>
				{/if}
				<div class="mt-3 flex flex-col gap-3">
					{#each gravesOf(fam.id) as g (g.file)}
						<article class="rounded-xl border border-border bg-card p-5">
							<div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
								<h4 class="font-mono text-sm font-semibold text-primary">{g.file}</h4>
								{#if g.sub}
									<span class="text-xs text-muted-foreground">{pick(g.sub)}</span>
								{/if}
							</div>
							<dl class="mt-3 flex flex-col gap-2.5">
								<div>
									<dt class="bdv-eyebrow text-[9px] text-muted-foreground">
										{en ? 'Why retired' : '死因'}
									</dt>
									<dd class="mt-0.5 text-sm leading-relaxed">{pick(g.why)}</dd>
								</div>
								{#if g.looked}
									<div>
										<dt class="bdv-eyebrow text-[9px] text-muted-foreground">
											{en ? 'What looked good' : '当时看起来'}
										</dt>
										<dd class="mt-0.5 text-sm leading-relaxed text-muted-foreground">
											{pick(g.looked)}
										</dd>
									</div>
								{/if}
								{#if g.happened}
									<div>
										<dt class="bdv-eyebrow text-[9px] text-muted-foreground">
											{en ? 'What actually happened' : '实际发生'}
										</dt>
										<dd class="mt-0.5 text-sm leading-relaxed text-muted-foreground">
											{pick(g.happened)}
										</dd>
									</div>
								{/if}
								<div class="rounded-md bg-secondary/60 px-3 py-2">
									<dt class="sr-only">{en ? 'Lesson' : '教训'}</dt>
									<dd class="text-sm leading-relaxed">
										<span aria-hidden="true">📌</span>
										<span class="font-medium">{en ? 'Lesson:' : '教训:'}</span>
										{pick(g.lesson)}
									</dd>
								</div>
							</dl>
						</article>
					{/each}
				</div>
			</div>
		{/each}
	</section>

	<!-- Footer: survivors + restoration protocol -->
	<section class="mt-12 rounded-2xl border border-border bg-card p-6">
		<p class="text-sm leading-relaxed">
			<a href="/wf" class="font-medium text-primary hover:underline">
				{en
					? 'What do the survivors look like? See the rolling validation across 8 market regimes →'
					: '活下来的策略长什么样?看 8 个市场环境的滚动检验 →'}
			</a>
		</p>
		<p class="mt-3 text-sm leading-relaxed text-muted-foreground">
			{en
				? 'Restoration protocol: any revival must re-pass the full walk-forward validation — no exceptions.'
				: '复活条件:必须重新通过完整 walk-forward,无一例外。'}
		</p>
	</section>
</main>
