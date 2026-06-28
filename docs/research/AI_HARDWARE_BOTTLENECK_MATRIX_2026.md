# AI 服务器硬件瓶颈矩阵（2026-2028）

更新日期：2026-06-27

这份矩阵用于把 AI 半导体从“芯片叙事”扩展为“可交付系统叙事”。AI 服务器能不能出货，不只看 GPU/HBM，还看封装、IC substrate、PCB、MLCC、VRM/VPD、液冷、网络光模块、电力并网和融资。

评分口径：`5 = 极强瓶颈 / 强定价权 / 高跟踪优先级`，`1 = 普通周期品或替代路径多`。

## 瓶颈矩阵

| 环节 | 2026 瓶颈强度 | 定价权 | 技术替代风险 | 关键证据 | 读者跟踪指标 |
| --- | ---: | ---: | ---: | --- | --- |
| HBM/HBM4 | 5 | 5 | 3 | HBM 绑定 GPU/ASIC 和先进封装，AI 训练与高吞吐推理仍强依赖高带宽。 | HBM3E/HBM4 合约价、客户锁量、良率、custom HBM |
| CoWoS/先进封装 | 5 | 5 | 2 | AI accelerator 需要 GPU/ASIC + HBM + interposer/substrate 组合交付。 | CoWoS 交期、OSAT capex、interposer/ABF 紧张 |
| IC package substrate / ABF | 5 | 4 | 2 | Ibiden 公布 FY2026-FY2028 约 5000 亿日元高性能 IC package substrate 投资，面向 AI/high-performance servers。 | Ibiden/Shinko/Unimicron/Nan Ya/Kinsus capex、客户预付款、SAP capacity |
| PCB / 高阶系统板 | 4 | 3 | 2 | 台湾 Q1 2026 PCB 产值受 AI server 拉动创高，关键材料如高阶玻纤布、铜箔紧张。 | AI server board ASP、层数、low-loss materials、铜箔/玻纤交期 |
| MLCC / 电源完整性 | 3 | 3 | 2 | Murata 把 AI server baseboard 电容数量上修到 15k-25k；TDK/Samsung 资料显示 AI PSU 进入更高功率和高压场景。 | 高端 MLCC lead time、C0G/高容小型料号、PSU/VRM 认证 |
| VRM / VPD / power module | 4 | 4 | 2 | Infineon AI data center VRM 模块面向 280A、vertical power delivery 和 2.0A/mm2 power density。 | 48V/54V 到 xPU 供电、phase count、VPD 采用率、power module ASP |
| 液冷 / thermal stack | 4 | 4 | 2 | AI rack density 上升推动 direct-to-chip liquid cooling；Vertiv/Schneider 均把 adaptive/direct-to-chip cooling 放在 2026 重点。 | liquid-cooled rack 占比、cold plate、CDU、quick disconnect、PUE |
| AI 网络 / 光模块 | 5 | 5 | 2 | 大规模训练和 agentic inference 使 800G/1.6T/3.2T 光模块、switch ASIC、DSP 和 Ethernet fabric 成为利用率瓶颈。 | 1.6T/3.2T ramp、CPO、硅光、Arista/Coherent/Credo 订单 |
| 电力 / 并网 | 5 | 4 | 1 | IEA 和数据中心公司均指出 AI 电力和并网成为物理约束。 | PPA、grid queue、天然气/核电、UPS/transformer 交期 |
| CXL/NAND/内存层级 | 3 | 3 | 3 | Apple 式 NAND-to-DRAM 专家加载、KV offload、CXL memory pooling 会改变热/温/冷内存分层。 | CXL adoption、SSD endurance、KV offload、NAND attach rate |

## 重要推论

### 1. AI 服务器会从芯片短缺变成系统短缺

2024-2025 市场主要讨论 GPU/HBM。2026-2028 需要讨论“能不能把整台 AI 服务器稳定交付”：基板、PCB、供电、冷却、光模块、连接器、线缆、液冷件、数据中心电力都可能变成排产约束。

### 2. 下游技术效率会压 HBM 容量，但不一定压系统硬件

TurboQuant、MLA、linear attention、Apple sparse on-device model 会降低每 token HBM 占用。但如果推理成本下降释放更多 token 和更高并发，板级供电、网络、光模块、冷却和电力仍可能继续紧。

### 3. 价格弹性最强的是“客户认证 + 交付周期长”的环节

HBM、CoWoS、IC substrate、AI networking、VRM/VPD 和高端 MLCC 都不是开关式产能。客户认证、良率爬坡、材料供应和可靠性验证会让这些环节拥有更强价格弹性。

### 4. 普通周期品要和 AI 高端料号分开看

MLCC、PCB、DRAM、NAND、铜箔、连接器都有普通周期品属性。真正有 AI 溢价的是进入高功率、高频、高可靠、低损耗、低 ESR/ESL、高层数、高客户认证门槛的料号。

## 三年观察路径

### 2026：瓶颈扩散

HBM、CoWoS、AI networking、电力仍是主瓶颈；MLCC、VRM/VPD、PCB、IC substrate 开始进入读者视野。看点是 capex 是否从芯片厂扩散到板级、供电和冷却。

### 2027：产能释放与真实短板暴露

HBM4、CoWoS、substrate、PCB、液冷、VRM 扩产逐步落地。若 AI 需求真实，瓶颈会滚动迁移；若需求不足，最先承压的是普通料号和缺少客户绑定的扩产。

### 2028：从“短缺”转向“系统 ROI”

真正的赢家是能持续绑定高端客户、提高良率、提供系统级方案的供应商。只靠产能扩张、没有客户锁单、没有高端料号认证的公司会回到普通周期品估值。

## 读者看板建议

| 看板指标 | 更新频率 | 数据源 |
| --- | --- | --- |
| HBM 合约价与产能 | 季度 | Micron/SK hynix/Samsung 财报 |
| CoWoS/OSAT capex | 季度 | TSMC/ASE/Amkor 财报 |
| IC substrate capex | 季度 | Ibiden/Shinko/Unimicron/Nan Ya |
| 高端 PCB 材料紧张度 | 月度 | TPCA/PCB industry survey |
| MLCC lead time | 月度 | Murata/TDK/Samsung SEM/Yageo channel checks |
| VRM/VPD adoption | 季度 | Infineon/MPS/Vicor/NVIDIA platform disclosures |
| 液冷 rack 占比 | 季度 | Vertiv/Schneider/Dell/SMCI |
| 光模块速率迁移 | 月度 | Coherent/Lumentum/Innolight/Credo/Arista |
| 电力并网 | 月度 | utility interconnection queues、PPA announcements |

## 核心来源

- Ibiden high-performance IC package substrate investment: https://www.ibiden.com/company/2026/02/notice-regarding-capital-investment-plan-for-high-performance-ic-package-substrates.html
- Ibiden FY2025 financial results: https://www.ibiden.com/ir/items/en_kessannsetsumeiFY2025.pdf
- Taiwan Q1 2026 PCB output survey: https://iconnect007.com/article/150517/taiwan-q1-2026-pcb-output-hits-record-nt2456-billion-on-ai-server-demand/150514/aep
- Infineon AI data center VRM: https://www.infineon.com/technology/ai/we-power-ai/vrm
- Murata IR Day 2025 MLCC: https://corporate.murata.com/-/media/corporate/about/newsroom/news/irnews/irnews/2025/1201/2512-e-speach.ashx?cvid=20251204015903000000&la=en
- TDK data center PSU MLCC: https://product.tdk.com/en/techlibrary/applicationnote/mlcc-solution-for-data-center-psu.html
- Vertiv 2026 cooling outlook: https://www.vertiv.com/en-emea/about/news-and-events/news-releases/2026/vertiv-expects-powering-up-for-ai-digital-twins-and-adaptive-liquid-cooling-to-shape-data-center-design-and-operations/
- Schneider direct-to-chip cooling: https://blog.se.com/datacenter/2026/01/16/rethinking-data-center-cooling-ai-direct-to-chip-liquid-cooling/
