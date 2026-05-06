// Bilingual glossary of metrics referenced by chart cards across the app.
// Each <ChartInfo metric="X"> looks up X here and renders a popover with
// the same four sections (what / why / read / rules) so beginners learn a
// consistent shape across the whole dashboard.
//
// Adding a new metric? Provide entries in both `zh` and `en`. Keep `plain`
// to ~1 sentence, `why` to ~1 sentence, and `rules` to 2-4 short bullets.

export type MetricCopy = {
	name: string;
	plain: string; // What it is — definition in plain language
	why: string; // Why it matters — investor-relevant interpretation
	rules?: string[]; // Optional rules of thumb / thresholds
	formula?: string; // Optional formula for the curious
};

export type MetricEntry = {
	zh: MetricCopy;
	en: MetricCopy;
};

export const METRICS: Record<string, MetricEntry> = {
	calmar: {
		zh: {
			name: 'Calmar 比率',
			plain: '年化收益 ÷ 最大回撤 — 每承受 1% 的回撤痛苦能换来多少 % 的收益。',
			why: '同时关心赚钱速度和最坏时刻。单看收益会高估那些大起大落的策略；Calmar 更接近真实持仓体感。',
			rules: ['> 3 优秀', '1–3 可接受', '< 1 通常不值得跑'],
			formula: 'Calmar = 年化收益% ÷ |最大回撤%|'
		},
		en: {
			name: 'Calmar Ratio',
			plain: 'Annualized return ÷ max drawdown — return earned per unit of pain.',
			why: 'Punishes both slow growth and big crashes. Tracks lived experience better than profit alone.',
			rules: ['> 3 excellent', '1–3 acceptable', '< 1 usually not worth running'],
			formula: 'Calmar = annualized return % ÷ |max drawdown %|'
		}
	},
	sortino: {
		zh: {
			name: 'Sortino 比率',
			plain: '收益相对下行波动的比率 — 像 Sharpe，但只惩罚向下波动。',
			why: '正常的"上涨波动"不该算风险。Sortino 比 Sharpe 更贴合投资者真实的损失厌恶心理。',
			rules: ['> 2 优秀', '1–2 可接受', '< 1 偏弱'],
			formula: 'Sortino = (收益 − 无风险利率) ÷ 下行偏差'
		},
		en: {
			name: 'Sortino Ratio',
			plain: 'Return divided by *downside* volatility — Sharpe, but it only counts losses.',
			why: 'Upside volatility shouldn’t count as risk. Sortino tracks loss-aversion more honestly than Sharpe.',
			rules: ['> 2 excellent', '1–2 acceptable', '< 1 weak'],
			formula: 'Sortino = (return − risk-free) ÷ downside deviation'
		}
	},
	sharpe: {
		zh: {
			name: 'Sharpe 比率',
			plain: '收益减去无风险利率，再除以总波动率 — 风险调整后的收益。',
			why: '行业标准的"风险换收益"指标，但它把上涨和下跌的波动都当作风险。',
			rules: ['> 1.5 很好', '0.5–1.5 一般', '< 0.5 通常不值得'],
			formula: 'Sharpe = (收益 − 无风险利率) ÷ 收益标准差'
		},
		en: {
			name: 'Sharpe Ratio',
			plain: 'Excess return divided by total volatility — the industry-standard risk-adjusted return.',
			why: 'Widely understood, but treats upside swings as "risk" the same as downside swings.',
			rules: ['> 1.5 great', '0.5–1.5 average', '< 0.5 usually not worth it'],
			formula: 'Sharpe = (return − risk-free) ÷ stdev(returns)'
		}
	},
	profitFactor: {
		zh: {
			name: '利润因子 (Profit Factor)',
			plain: '所有盈利交易之和 ÷ 所有亏损交易之和的绝对值。',
			why: '直接告诉你"赢的钱"是"输的钱"的几倍。低于 1 就是净亏。',
			rules: ['> 2 优秀', '1.3–2 可接受', '1–1.3 边际', '< 1 净亏'],
			formula: 'PF = 盈利总额 ÷ |亏损总额|'
		},
		en: {
			name: 'Profit Factor',
			plain: 'Sum of winning trades ÷ absolute value of sum of losing trades.',
			why: 'Tells you directly how many times your winners cover your losers. Below 1 is net loss.',
			rules: ['> 2 excellent', '1.3–2 acceptable', '1–1.3 marginal', '< 1 net loss'],
			formula: 'PF = gross wins ÷ |gross losses|'
		}
	},
	maxDrawdown: {
		zh: {
			name: '最大回撤 (Max Drawdown)',
			plain: '资金从历史最高点到之后最低点的最大跌幅。',
			why: '你账户最痛的一段。决定了多少人能扛住不平仓 — 很多策略死于回撤而不是收益。',
			rules: ['< 10% 温和', '10–25% 普通', '25–40% 痛', '> 40% 大概率扛不住']
		},
		en: {
			name: 'Max Drawdown',
			plain: 'Largest peak-to-trough drop in account equity.',
			why: 'The worst pain you would have endured. Most strategies die from drawdown, not from low return.',
			rules: ['< 10% mild', '10–25% normal', '25–40% painful', '> 40% likely unholdable']
		}
	},
	winRate: {
		zh: {
			name: '胜率 (Win Rate)',
			plain: '盈利交易数 ÷ 总交易数。',
			why: '心理上让你舒服的指标，但单独看会骗人 — 高胜率配大亏损同样亏钱。要和利润因子一起看。',
			rules: ['> 60% 高胜率', '45–60% 中等', '< 45% 必须配高赔率']
		},
		en: {
			name: 'Win Rate',
			plain: 'Winning trades ÷ total trades.',
			why: 'Psychologically comforting but misleading alone — high win rate + big losses still loses money. Read with Profit Factor.',
			rules: ['> 60% high', '45–60% medium', '< 45% needs big winners to compensate']
		}
	},
	totalProfit: {
		zh: {
			name: '总收益 %',
			plain: '回测期间累积的百分比收益。',
			why: '最直观的指标，但忽略了风险。两个 +50% 的策略，可能一个最大回撤 5%，另一个 40%。'
		},
		en: {
			name: 'Total Profit %',
			plain: 'Cumulative percentage return over the backtest period.',
			why: 'The most intuitive number, but blind to risk. Two strategies at +50% can have wildly different max drawdowns.'
		}
	},
	avgProfit: {
		zh: {
			name: '单笔平均收益 %',
			plain: '所有交易的平均盈亏百分比。',
			why: '判断"边际"够不够覆盖手续费滑点。单笔 0.1% 在交易费 0.05% 的环境下基本是噪音。'
		},
		en: {
			name: 'Avg Profit per Trade %',
			plain: 'Mean profit% across all trades.',
			why: 'Tells if your edge is large enough to cover fees + slippage. 0.1% per trade in a 0.05% fee market is mostly noise.'
		}
	},
	tradeCount: {
		zh: {
			name: '交易次数',
			plain: '回测期间总开仓次数。',
			why: '样本量。不到 30 笔的"好结果"基本是噪音。统计上至少 100+ 笔才有参考价值。',
			rules: ['< 30 样本不足', '30–100 参考', '100–500 较可靠', '> 500 充分']
		},
		en: {
			name: 'Trade Count',
			plain: 'Total trades opened during the backtest.',
			why: 'Sample size. Fewer than 30 trades is mostly noise; you want 100+ for any statistical confidence.',
			rules: ['< 30 too few', '30–100 indicative', '100–500 fairly reliable', '> 500 robust']
		}
	},
	timeframe: {
		zh: {
			name: '周期 (Timeframe)',
			plain: '每根 K 线的时间窗口 — 1m / 15m / 1h / 1d 等。',
			why: '低周期产生更多交易但噪音多、对手续费敏感；高周期信号干净但反应慢。每个策略有它最适合的周期。'
		},
		en: {
			name: 'Timeframe',
			plain: 'Width of each candlestick — 1m / 15m / 1h / 1d, etc.',
			why: 'Lower TF = more trades but noisier and fee-sensitive; higher TF = cleaner signal but slower reaction. Strategies have natural sweet spots.'
		}
	},
	walkForward: {
		zh: {
			name: '滚动验证 (Walk-Forward)',
			plain: '把历史切成多个连续窗口，用前一段优化参数，再到下一段验证 — 模拟真实"先训练后实盘"的场景。',
			why: '只看一次回测可能是过拟合。Walk-Forward 检查策略在不同市场环境下还能不能赚钱。'
		},
		en: {
			name: 'Walk-Forward',
			plain: 'Split history into rolling train/test windows: optimize on the past, validate on the next slice.',
			why: 'A single backtest may be over-fit. Walk-Forward checks whether the edge survives across different market regimes.'
		}
	},
	hyperoptEpoch: {
		zh: {
			name: 'Hyperopt Epoch',
			plain: '一次参数尝试 — 优化器选了一组超参数跑了一遍回测。',
			why: '查看 epoch 分布能看出参数空间形状：扁平 = 鲁棒，尖峰 = 过拟合风险高。'
		},
		en: {
			name: 'Hyperopt Epoch',
			plain: 'One parameter trial — the optimizer picked a parameter set and ran one backtest.',
			why: 'The epoch distribution reveals the parameter space shape: flat = robust, sharp peak = likely over-fit.'
		}
	},
	fearGreed: {
		zh: {
			name: '恐慌贪婪指数 (Fear & Greed)',
			plain: '0–100 综合情绪指标 — 0=极度恐惧，100=极度贪婪。',
			why: '反向指标。极度恐惧时往往是底部区域；极度贪婪时往往是顶部区域。Smart DCA 用它做仓位倍率。',
			rules: ['0–25 极度恐惧 (加仓)', '25–45 恐惧', '45–55 中性', '55–75 贪婪', '75–100 极度贪婪 (减仓)']
		},
		en: {
			name: 'Fear & Greed Index',
			plain: '0–100 composite sentiment gauge — 0=extreme fear, 100=extreme greed.',
			why: 'Contrarian signal. Extreme fear ≈ market bottom zones; extreme greed ≈ market top zones. Smart DCA scales position size with it.',
			rules: ['0–25 extreme fear (scale in)', '25–45 fear', '45–55 neutral', '55–75 greed', '75–100 extreme greed (scale out)']
		}
	},
	leaderboard: {
		zh: {
			name: '排行榜',
			plain: '按某个指标对策略 / 因子 / 交易对从好到差排序。',
			why: '快速找到当前榜首和垫底，决定下一步深入研究哪些。'
		},
		en: {
			name: 'Leaderboard',
			plain: 'Strategies / factors / pairs sorted from best to worst on a given metric.',
			why: 'Quickly spot the current winners and laggards to decide where to drill in.'
		}
	},
	scatter: {
		zh: {
			name: '散点图',
			plain: '每个点 = 一次回测，X 轴 / Y 轴 = 两个指标。',
			why: '找两个指标之间的相关性。右上角通常是"两边都好"的甜点区。'
		},
		en: {
			name: 'Scatter Plot',
			plain: 'One dot per backtest run; X / Y axes are two metrics.',
			why: 'Reveals correlation between metrics. Top-right quadrant is usually the "both good" sweet spot.'
		}
	},
	cdf: {
		zh: {
			name: '累积分布 (CDF)',
			plain: 'X 轴是值，Y 轴是累积百分比 — 例如 "70% 的运行回撤 < X"。',
			why: '比直方图更容易读"中位数 / 长尾"。S 形左偏 = 大多数样本表现好；右偏 = 表现差。'
		},
		en: {
			name: 'Cumulative Distribution (CDF)',
			plain: 'X = the value, Y = cumulative percentage — e.g. "70% of runs had drawdown < X".',
			why: 'Easier to read median / tail than a histogram. Left-skewed S-curve = most samples are good; right-skewed = most are bad.'
		}
	},
	distribution: {
		zh: {
			name: '分布图 (Histogram)',
			plain: '把数值分桶，统计每个桶里的样本数。',
			why: '看数据形状：单峰 / 双峰 / 长尾。多峰意味着可能有不同的市场状态共存。'
		},
		en: {
			name: 'Distribution (Histogram)',
			plain: 'Bin the values and count samples per bin.',
			why: 'Reveals shape: unimodal / bimodal / long-tailed. Multiple peaks suggest distinct market regimes mixed together.'
		}
	},
	equityCurve: {
		zh: {
			name: '资金曲线 (Equity Curve)',
			plain: '账户余额随时间变化的曲线，每笔交易后更新。',
			why: '一图看懂策略表现：稳步上升 = 健康，断崖式下跌 = 风险事件，长期横盘 = 失去边际。理想状态是一条平滑右上方的曲线。'
		},
		en: {
			name: 'Equity Curve',
			plain: 'Account balance over time, updated after each trade.',
			why: 'The most honest summary chart: steady rise = healthy, sharp drops = risk events, long flatlines = lost edge. The ideal is a smooth line tilting up-right.'
		}
	},
	monteCarlo: {
		zh: {
			name: '蒙特卡洛模拟 (Monte Carlo)',
			plain: '把历史交易随机重排上千次，看在不同顺序下账户曲线的范围。',
			why: '回测结果可能是"运气好的顺序"。MC 显示同样的策略在最坏 5% 情况下可能会怎样 — 心理上准备最坏情况。',
			rules: ['p5 = 最差 5% 情况', 'p50 = 中位数', 'p95 = 最好 5% 情况']
		},
		en: {
			name: 'Monte Carlo Simulation',
			plain: 'Randomly reshuffle the historical trade sequence thousands of times to see the range of equity curves.',
			why: 'Your backtest may have benefited from a lucky order. MC shows what the same trades look like in the worst 5% — primes you for the downside.',
			rules: ['p5 = worst 5% scenario', 'p50 = median', 'p95 = best 5% scenario']
		}
	},
	expectancy: {
		zh: {
			name: '期望值 (Expectancy)',
			plain: '每笔交易的平均盈亏期望 = 胜率 × 平均盈利 − 败率 × 平均亏损。',
			why: '把胜率和盈亏比合在一起。正值 = 长期赚钱；负值 = 长期亏损 (即使胜率高也无效)。',
			formula: 'E = WR × 平均盈利 − (1 − WR) × |平均亏损|'
		},
		en: {
			name: 'Expectancy',
			plain: 'Expected profit per trade = win rate × avg win − loss rate × avg loss.',
			why: 'Combines win rate and risk/reward into a single number. Positive = profitable long-term; negative = unprofitable even with high win rate.',
			formula: 'E = WR × avg_win − (1 − WR) × |avg_loss|'
		}
	},
	streak: {
		zh: {
			name: '连胜 / 连亏 (Streak)',
			plain: '连续盈利或连续亏损的最长交易序列。',
			why: '判断你心理上能不能扛过去。连续 10 笔亏损看似不可能，但在 100 笔交易里出现的概率比你想象的高得多。',
			rules: ['策略要能承受 2× 历史最长连亏', '心理准备 = 实盘成功的关键']
		},
		en: {
			name: 'Win/Loss Streak',
			plain: 'Longest consecutive run of winning or losing trades.',
			why: 'Tells you what your psychology has to survive. A 10-trade losing streak feels impossible but is more likely than you think over 100 trades.',
			rules: ['Plan capital for 2× the historical worst streak', 'Mental prep = key to live success']
		}
	},
	exitReason: {
		zh: {
			name: '出场原因 (Exit Reason)',
			plain: '每笔交易最终的离场原因 — ROI / stoploss / 信号离场 / custom_exit 等。',
			why: '分析利润是从哪里来的。如果 90% 利润来自 ROI、止损只触发亏损，说明胜出靠固定目标；如果 custom_exit 占主导，自定义逻辑是核心。'
		},
		en: {
			name: 'Exit Reason',
			plain: 'Why each trade closed — ROI hit / stoploss / signal exit / custom_exit / etc.',
			why: 'Tells you where the edge actually comes from. If 90% of profit is from ROI hits and stoploss only fires losses, the winners come from fixed targets, not signals.'
		}
	},
	enterTag: {
		zh: {
			name: '入场标签 (Enter Tag)',
			plain: '策略给每笔开仓打的标签 — 标识"是哪个信号触发了入场"。',
			why: '区分策略里不同的入场逻辑。某些信号可能赚钱，某些一直亏；按 enter_tag 拆开看就知道哪些子策略可以保留、哪些应该剪掉。'
		},
		en: {
			name: 'Enter Tag',
			plain: 'A label the strategy attaches to each opened trade — "which signal triggered this entry?"',
			why: 'Lets you separate different entry logics inside one strategy. Some signals print, others bleed; splitting by enter_tag tells you which to keep and which to cut.'
		}
	},
	holdingTime: {
		zh: {
			name: '持仓时间 (Holding Time)',
			plain: '每笔交易从开仓到平仓的时长。',
			why: '过短 = 抓不到趋势/被噪音洗出；过长 = 资金占用低效。和周期一致才合理 (15m 策略持仓数小时合理，持仓数天则可疑)。'
		},
		en: {
			name: 'Holding Time',
			plain: 'How long each trade stays open from entry to exit.',
			why: 'Too short = noise-shaken / trend missed; too long = capital tied up. Should match your timeframe — 15m strategy holding hours is fine, holding days is suspicious.'
		}
	},
	calendar: {
		zh: {
			name: '盈亏日历 (PnL Calendar)',
			plain: '把每天/每月的盈亏画成绿/红方块的日历视图。',
			why: '一眼识别"赚钱季节"和"危险窗口"。某些月份持续亏损可能意味着策略对该季节的市场结构不适应。'
		},
		en: {
			name: 'PnL Calendar',
			plain: 'Daily/monthly profit shown as green/red cells in a calendar layout.',
			why: 'Spot "good seasons" and "danger windows" instantly. Months that bleed consistently often mean the strategy doesn’t fit that season’s market structure.'
		}
	},
	rollingWinRate: {
		zh: {
			name: '滚动胜率 (Rolling Win Rate)',
			plain: '过去 N 笔交易的胜率，随时间滑动更新。',
			why: '判断策略是否在退化。如果胜率从 60% 慢慢滑到 45%，说明边际正在消失，应该考虑停掉或重新优化。'
		},
		en: {
			name: 'Rolling Win Rate',
			plain: 'Win rate over the last N trades, sliding through time.',
			why: 'Detects edge decay. If win rate drifts from 60% down to 45%, the strategy is losing its edge — time to retire or re-optimize.'
		}
	},
	portfolio: {
		zh: {
			name: '策略组合视图 (Portfolio View)',
			plain: '按状态 (live/dryrun/research) 或交易模式 (spot/futures) 拆分的策略集合。',
			why: '看清当前资金分配 — live 太少说明研究多但落地少；dryrun 太多说明在拖延上线决策。'
		},
		en: {
			name: 'Portfolio View',
			plain: 'Strategies grouped by status (live/dryrun/research) or trading mode (spot/futures).',
			why: 'Reveals capital allocation: too few "live" means too much research and too little execution; too many "dryrun" means you are deferring deployment decisions.'
		}
	}
};

export function getMetric(id: string, lang: 'zh' | 'en'): MetricCopy | null {
	const entry = METRICS[id];
	if (!entry) return null;
	return entry[lang];
}
