# AI 半导体与全球流动性研究档案（2026-2028）

更新日期：2026-06-26

这份档案用于把 AI 半导体、全球流动性、资本开支、地缘政治和技术论文拆成可跟踪的研究对象。它不是投资建议；后续应把关键指标接入 `news_items`、`market_snapshots`、`semi_universe` 和 `/semis` 页面。战略总纲见 `docs/research/FUTURE_COMPETITIVE_MOATS_2026.md`，未来竞争力评分卡见 `docs/research/FUTURE_MOATS_SCORECARD_2026.md`，读者版主文见 `docs/research/AI_SEMIS_GLOBAL_LIQUIDITY_READER_REPORT_2026.md`，论文综合新思路见 `docs/research/AI_SEMIS_PAPER_SYNTHESIS_NEW_IDEAS_2026.md`，内存墙与架构路线见 `docs/research/AI_MEMORY_WALL_ARCHITECTURE_ROADMAP_2026.md`，MLCC 与电源完整性见 `docs/research/AI_MLCC_POWER_INTEGRITY_2026.md`，硬件瓶颈矩阵见 `docs/research/AI_HARDWARE_BOTTLENECK_MATRIX_2026.md`，AI 半导体本地论文库见 `docs/research/papers/ai-semiconductors/`，AI 电力/能源/气候论文库见 `docs/research/papers/ai-energy-climate/`，AI 电力/能源/气候数据新闻源见 `docs/research/data/ai-energy-climate/`，机器可读来源索引见 `docs/research/ai_semis_global_liquidity_sources.csv`。

## 结论先行

- AI 半导体的主线不是单一 GPU，而是“加速器 + HBM + 先进封装 + 网络 + 电力 + 资本市场融资”的系统约束。
- 2026-2028 年最关键瓶颈依次是 HBM/DRAM、CoWoS/先进封装、先进节点产能、光/电互连、数据中心电力和低成本融资。
- MLCC 是 AI 服务器板级供电的 second-order bottleneck：金额小于 HBM，但高端料号、PSU/VRM、xPU/HBM 去耦和 power module 会影响服务器稳定交付。
- 上游设备和材料受益更像“卖铲子”：ASML、AMAT、LRCX、KLAC、TER、MKSI、气体/化学品/材料公司不一定跟单一芯片设计商同步，但受 AI capex 周期驱动。
- 地缘政治会把需求拆成两条链：美国及盟友先进 AI 链，中国国产替代和成熟节点链。出口管制越严格，重复建设越多，行业总体资本强度越高。
- 全球流动性决定估值弹性。AI capex 从资产负债表自筹转向债务、租赁和项目融资后，对美元信用、利率和信用利差更敏感。

## 资料索引

### 行业规模与设备周期

| 来源 | 已提取事实 | 研究用途 |
| --- | --- | --- |
| WSTS Spring 2026 Forecast, `wsts.org/76/Recent-News-Release` | WSTS 将 2026 全球半导体市场预测上调到约 1.51 万亿美元，记忆体是最大增量。该口径很激进，需要用月度 WSTS/SIA 数据交叉验证。 | 判断周期天花板、跟踪 Memory/Logic 剪刀差 |
| SIA, Global Semiconductor Sales Q1 2026 | 2026Q1 全球半导体销售额 2985 亿美元；2026 年被描述为有望达到 1 万亿美元级别。 | 月度需求强度和区域贡献 |
| SIA-Deloitte, `Powering AI` | AI 数据中心机柜价值中半导体占比超过 95%；到 2028 年 AI 数据中心半导体年收入可超过 1.2 万亿美元。 | 拆解 AI rack 的芯片含量 |
| SEMI WWSEMS 2025 | 2025 全球半导体设备销售额 1351 亿美元；测试设备同比 +55%，组装封装设备 +21%。 | 验证先进封装和 HBM 测试强度 |
| SEMI 300mm Fab Outlook 2026 | 300mm fab 设备支出预计 2026 年 1330 亿美元、2027 年 1510 亿美元。 | 判断晶圆厂扩产曲线 |

### 公司与资本开支

| 环节 | 公司/来源 | 已提取事实 | 观察点 |
| --- | --- | --- | --- |
| AI 加速器 | NVIDIA FY2026 10-K、FY2027 Q1 IR | FY2026 收入 2159 亿美元，数据中心收入同比 +68%；FY2027 Q1 收入 816 亿美元，数据中心 752 亿美元。 | Blackwell/GB 系列供给、毛利率、网络收入 |
| Foundry | TSMC 2025 annual report、2026Q1 transcript | N2 已在 2025Q4 高量产，HPC/AI 与智能手机共同驱动 N2 family。 | N2/N2P/A16 ramp、CoWoS 扩产节奏 |
| Lithography | ASML 2025 annual report、2026Q1 presentation | AI 推动先进逻辑和记忆体所需曝光次数；High-NA EUV 目标在 2027-2028 客户导入。 | EUV/High-NA 订单、DUV 管制风险 |
| Memory/HBM | Micron FY2026 Q2/Q3 | FY2026 capex 超 250 亿美元；FY2027 capex 继续上台阶；数据中心收入在 FY2026 Q3 年化超 1000 亿美元，供给紧张预计延续。 | HBM 合约、DRAM/NAND 供给纪律 |
| 云需求 | Microsoft FY2026 Q3 | 单季 capex 319 亿美元，约三分之二用于 GPU/CPU 等短寿资产。 | Azure/OpenAI backlog、融资租赁 |
| 云需求 | Alphabet 2026Q1/Q4 2025 | 2026Q1 capex 357 亿美元；全年 capex 指引 1750-1850 亿美元。 | TPU/GPU mix、Cloud backlog |
| 云需求 | Amazon 2025 shareholder letter、2026Q1 | AWS AI 收入 run-rate 超 150 亿美元，芯片业务 run-rate 超 200 亿美元；2026 capex 约 2000 亿美元。 | Trainium 价格性能、AWS 电力容量 |
| 云需求 | Meta 2026Q1 | 2026 capex 指引上调到 1250-1450 亿美元，反映组件涨价和未来数据中心容量。 | Superintelligence Labs、GPU 成本 |

### 全球流动性与宏观资金面

| 来源 | 已提取事实 | 解读 |
| --- | --- | --- |
| BIS Global Liquidity Indicators end-2025 | 全球美元外币信用余额 14.3 万亿美元，同比 +8.5%；欧元外币信用 4.9 万亿欧元，同比 +11%。 | 离岸美元信用重新扩张，利好高久期科技估值，但也提高美元 funding shock 风险。 |
| Federal Reserve H.4.1 2026-06-25 | 2026-06-24 美联储总资产约 6.736 万亿美元。 | 仍需跟踪 QT/再投资规则与 TGA/RRP 对风险资产流动性的影响。 |
| ECB Weekly Financial Statement 2026-06-23 | 2026-06-19 Eurosystem 总资产约 6.120 万亿欧元。 | 欧元区资产负债表继续影响欧洲半导体和工业股折现率。 |
| 中国人民银行/人民日报 2026-06 | 2026 年前五个月社融增量 17.48 万亿元；5 月末社融存量 458.81 万亿元，同比 +7.7%。 | 中国链条更依赖政策信用与国产替代投资，不完全同步美元 AI capex 周期。 |

### 政策与地缘政治

| 来源 | 已提取事实 | 影响 |
| --- | --- | --- |
| BIS advanced computing/SME controls | 美国 2022/2023 管制限制先进 AI 芯片、超算用途和半导体制造设备对华出口。 | 限制先进节点与高端加速器流向，强化 TSMC/ASML/EDA 的政策溢价。 |
| BIS 2024 semiconductor package | 新增对 24 类设备、3 类软件工具、HBM 和 140 个实体的限制。 | HBM 直接进入战略管制对象，记忆体链条地缘风险上升。 |
| BIS 2025 AI Diffusion rescission | 2025 年撤销 AI Diffusion Rule，但发布针对海外 AI 芯片、华为 Ascend 和 diversion 的新指引。 | 从“一刀切配额”转向更细的合规和执法框架。 |
| BIS 2026 H200/MI325X China review | 对 H200、MI325X 等对华出口改为满足安全条件后的 case-by-case 审查。 | 给部分供应恢复空间，但不改变先进 AI 受控基调。 |
| Netherlands 2024/2025 controls | 荷兰扩大先进半导体制造设备出口许可，覆盖 DUV、测量与检测设备等。 | ASML 和计量检测环节受政策约束，供应链复制成本上升。 |
| MOFCOM gallium/germanium/graphite/rare earth controls | 中国对镓、锗、石墨及稀土相关物项实施许可证管理，官方强调不是禁运。 | 材料端成为反制工具；需要跟踪审批速度和实际出口量。 |

## 产业链拆解

### 1. 原材料、气体、化学品、晶圆

关键对象：硅晶圆、光刻胶、电子特气、CMP 材料、湿电子化学品、前驱体、镓/锗/稀土等关键矿物。

要跟踪的指标：

- 光刻胶、ArF/KrF、EUV resist 供应与价格。
- 电子特气和前驱体产能利用率。
- 中国关键材料出口许可证数量、审批周期和实际出口量。
- 供应商：LIN、ENTG、DD、WFR/SUMCO、JSR、TOK、ADEKA、Merck KGaA、Air Liquide。

### 2. 设备与量测

AI 需求首先传导到先进逻辑、HBM DRAM 和先进封装设备。

- 光刻：ASML EUV/High-NA、DUV immersion。
- 沉积/刻蚀/清洗：AMAT、LRCX、TEL、ASM。
- 量测检测：KLAC、Onto、Nova。
- 测试与探针：TER、Advantest、FormFactor。

重点判断：如果 HBM 和先进封装是瓶颈，测试、封装、量测的弹性可能高于传统前道设备。

### 3. EDA/IP 与设计

EDA 是所有先进芯片的隐形税。SNPS、CDNS、Siemens EDA、ARM 受益于 AI ASIC、chiplet 和定制加速器扩散。

重点跟踪：

- Hyperscaler 自研 ASIC 数量。
- ARM Neoverse、RISC-V、chiplet IP 授权。
- EDA 对 2nm/GAA、3DIC、thermal-aware design 的支持。

### 4. Foundry、先进节点与先进封装

TSMC 是核心，Samsung/Intel Foundry 是战略冗余。未来三年不是单纯看晶圆，而要看“晶圆 + CoWoS/SoIC/2.5D/3D 封装 + HBM 配套”。

瓶颈信号：

- CoWoS 月产能、interposer、substrate 和 ABF 价格。
- N2/N2P/A16 ramp。
- Samsung/Intel 能否承接非 NVIDIA AI ASIC。
- OSAT：ASE/ASX、AMKR、JCET。

### 5. Memory/HBM、NAND、存储

推理时代把瓶颈从训练算力扩展到 KV cache、带宽、容量和存储 IO。

- HBM3E/HBM4 价格、合约锁量和良率。
- DRAM wafer allocation 是否挤压 PC/mobile。
- NAND 在推理、向量库、checkpoint、缓存中的增量需求。
- 供应商：SK hynix、Micron、Samsung。

### 6. 网络、互连、光模块

大模型训练和 agentic inference 提高东西向流量，网络从配套件变成系统性能瓶颈。

- Ethernet vs InfiniBand、Ultra Ethernet 进度。
- 800G/1.6T 光模块、CPO、硅光。
- 交换芯片、DSP、光器件：AVGO、MRVL、ANET、COHR、CRDO、LITE。

### 7. 服务器、数据中心、电力

AI 半导体需求最终受电力、冷却、土地、并网、施工劳动力和融资制约。

- IEA 预计数据中心电耗从 2024 年约 415 TWh 到 2030 年接近翻倍；AI-focused data centers 增长更快。
- 观察 AWS/Microsoft/Google/Meta 是否从“GPU 缺货”转成“电力/并网/水/许可”缺口。
- 服务器厂商：SMCI、DELL、HPE、Foxconn、Quanta、Wiwynn。

## 前沿论文与技术路线

| 方向 | 核心论文/资料 | 对半导体的含义 |
| --- | --- | --- |
| 推理时计算 | `Scaling LLM Test-Time Compute Optimally...`，ICLR 2025 | 质量提升越来越依赖 inference-time tokens，推理算力和内存需求上升。 |
| 长上下文与 KV cache | `PagedAttention/vLLM`、`KIVI 2bit KV Cache`、`Optimization Pathways for Long-Context Agentic LLM Inference` | HBM 容量、带宽和软件调度成为成本核心；压缩技术会降低单位 token 成本，但通常也扩大可用需求。 |
| Attention 加速 | `FlashAttention-3` | 通过减少 HBM 读写、利用 FP8 和 Hopper 异步机制提升利用率；软件优化可延长硬件代际寿命。 |
| MoE/稀疏激活 | `DeepSeek-V3 Technical Report` | 671B 总参数、37B token 激活说明训练与推理可通过稀疏化降成本，但网络和内存调度更复杂。 |
| Benchmark | MLPerf Inference v5.0 | Llama 2 70B、Llama 3.1 405B、128k context 进入主流 benchmark，说明行业 benchmark 正向大模型推理迁移。 |
| 能源 | IEA `Energy and AI`、`Key Questions on Energy and AI` | 电力从 ESG 话题变成产能瓶颈；高能效芯片、冷却、选址和电网成为半导体需求变量。 |

## MLCC 与电源完整性

AI 服务器的被动元件不能再按普通消费电子逻辑看。Murata 在 2025 IR Day 中把 AI server baseboard 电容数量上修到 15,000-25,000 颗，并估计 FY25-FY30 需求年增 30%；TDK 和 Samsung Electro-Mechanics 的资料也显示，AI data center PSU 正从传统 kW 级进入 6-12 kW+、>4 kW 高压高可靠场景。

投资含义：

- 高端 MLCC 受益来自 AI rack power、xPU/HBM 瞬态电流、48V/54V/800V 电源架构和板级空间约束。
- 普通 MLCC 仍是周期品，不应把 AI 服务器叙事外推到全部料号。
- 重点跟踪 Murata、TDK、Samsung Electro-Mechanics、Taiyo Yuden、Yageo、Walsin 的高容小型、高压 C0G、软端子和 power module 认证。
- MLCC 应放在“电力与板级可靠性”篮子：它不是 HBM 替代品，而是 AI 服务器稳定交付的底层约束。

## 三年驱动判断

### 基准情景：AI capex 维持高位，但约束从芯片转向系统

2026 年仍是供给驱动：HBM、CoWoS、先进节点和网络供不应求。2027 年开始，先进封装和 HBM 产能释放，单位 token 成本下降，推理需求扩张吸收供给。2028 年分化更明显：拥有真实需求、低融资成本和电力资源的 hyperscaler 继续扩张；缺乏 monetization 的项目被资本市场淘汰。

### 牛市情景：推理需求非线性扩张

如果 agent、代码、视频、多模态和企业自动化形成稳定收入，推理 tokens 增速超过硬件效率提升，HBM/网络/电力仍长期紧张。受益顺序：HBM > 封装/测试 > 网络/光模块 > 先进设备 > foundry > 加速器设计。

### 压力情景：融资、监管或电力先卡住

若利率上行、信用利差扩大、AI 收入不及折旧增长，hyperscaler capex 会放缓。此时设计商订单先承压，设备和材料因 backlog 滞后，最后传导到晶圆厂资本开支。地缘冲突升级会提高库存和重复建设，但也会打断最高端链条的效率。

## 数据落地计划

1. 在 `strategies/news_collector.py` 增加半导体和全球流动性源：SIA、SEMI、WSTS、BIS、Fed H.4.1、ECB WFS、PBOC/人民银行、BIS export controls、Government.nl、MOFCOM。
2. 在 `news_items` 增加标签：`ai_semis`、`liquidity`、`export_controls`、`datacenter_power`、`hbm`、`advanced_packaging`。
3. 在 `market_snapshots` 增加指标：Fed total assets、ECB assets、BIS dollar credit、China TSF/M2、hyperscaler capex、SEMI equipment billings、SIA monthly sales。
4. 在 `/semis` 页面增加“供应链热度”和“新闻覆盖率”：每个节点显示最近 7/30 天新闻数量、政策风险、capex 变动。
5. 增加一个研究看板：`/research/ai-semis-liquidity`，分为产业链、资金面、政策、论文、结论五栏。

## 待补缺口

- WSTS 1.51 万亿美元预测与 SIA “2026 约 1 万亿美元”口径存在明显差异，需要下载 WSTS Blue Book/forecast PDF 核对产品分类和是否包含特殊统计口径。
- SK hynix、Samsung、ASE、Amkor、Broadcom、AMD、Arista、Coherent、Credo 还需要逐家抽取最新财报中的 AI/HBM/packaging/networking 口径。
- 需要把 hyperscaler capex 拆成 cash capex、finance leases、land/power、GPU/CPU/networking，避免把全部 capex 等同于芯片订单。
- 中国关键材料出口管制要跟踪许可证和海关实际出口量，不能只看政策文本。
- 前沿论文需要建立 BibTeX/CSV 索引，字段包括 `topic`、`bottleneck`、`hardware implication`、`source_url`、`confidence`。

## 核心来源链接

- WSTS Recent News Release: https://www.wsts.org/76/Recent-News-Release
- SIA Q1 2026 sales: https://www.semiconductors.org/global-semiconductor-sales-increase-25-from-q4-2025-to-q1-2026/
- SIA-Deloitte AI rack report: https://www.semiconductors.org/new-report-finds-semiconductors-account-for-95-of-an-ai-data-server-racks-value-encompassing-the-full-stack-of-chip-technologies/
- SEMI 2025 equipment billings: https://www.semi.org/en/SEMI-Reports-Global-Semiconductor-Equipment-Billings-Reached-135-Billion-in-2025
- SEMI 300mm Fab Outlook: https://www.semi.org/en/semi-press-release/semi-projects-double-digit-growth-in-global-300mm-fab-equipment-spending-for-2026-and-2027
- NVIDIA FY2026 annual report: https://investor.nvidia.com/files/doc_financials/2026/q4/10K-NVDA.pdf
- TSMC annual reports: https://investor.tsmc.com/english/annual-reports
- ASML annual report: https://www.asml.com/investors/annual-report/2025
- Micron investor relations: https://investors.micron.com/
- Microsoft FY2026 Q3 earnings: https://www.microsoft.com/en-us/investor/events/fy-2026/earnings-fy-2026-q3
- Alphabet Q1 2026 earnings: https://abc.xyz/investor/events/event-details/2026/2026-Q1-Earnings-Call-2026-nW8kCrBAKS/default.aspx
- Amazon Q1 2026 earnings: https://ir.aboutamazon.com/news-release/news-release-details/2026/Amazon-com-Announces-First-Quarter-Results/default.aspx
- Meta Q1 2026 earnings: https://investor.atmeta.com/investor-news/press-release-details/2026/Meta-Reports-First-Quarter-2026-Results/default.aspx
- BIS Global Liquidity Indicators: https://www.bis.org/statistics/gli2604.htm
- Federal Reserve H.4.1: https://www.federalreserve.gov/releases/h41/current/
- ECB weekly financial statements: https://www.ecb.europa.eu/press/annual-reports-financial-statements/wfs/html/index.en.html
- People's Daily PBOC TSF report: https://paper.people.com.cn/rmrb/pc/content/202606/15/content_30163056.html
- BIS export controls page: https://www.bis.gov/press-release/bis-updated-public-information-page-export-controls-imposed-advanced-computing-semiconductor
- Netherlands semiconductor export controls: https://www.government.nl/latest/news/2025/01/15/klever-export-controls-on-advanced-semiconductor-manufacturing-equipment-to-be-tightened
- MOFCOM gallium/germanium remarks: https://english.mofcom.gov.cn/News/PressConference/art/2023/art_36fb2d80e4b4453891bb8fc83e2b3c4e.html
- MLPerf Inference v5.0: https://mlcommons.org/2025/04/mlperf-inference-v5-0-results/
- IEA Energy and AI: https://www.iea.org/reports/energy-and-ai/energy-demand-from-ai
- ICLR 2025 test-time compute paper: https://proceedings.iclr.cc/paper_files/paper/2025/file/1b623663fd9b874366f3ce019fdfdd44-Paper-Conference.pdf
- FlashAttention-3: https://arxiv.org/abs/2407.08608
- DeepSeek-V3 technical report: https://arxiv.org/abs/2412.19437
- KIVI KV cache quantization: https://arxiv.org/abs/2402.02750
- vLLM/PagedAttention: https://arxiv.org/abs/2309.06180
