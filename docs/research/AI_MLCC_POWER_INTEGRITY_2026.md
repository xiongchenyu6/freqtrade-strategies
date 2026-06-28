# AI 服务器 MLCC 与电源完整性研究笔记（2026-2028）

更新日期：2026-06-27

这份笔记补充 AI 半导体研究中的“隐形瓶颈”：MLCC（multilayer ceramic capacitor，多层陶瓷电容）。如果 HBM 是内存墙，MLCC 对应的是 **power integrity wall**：GPU/ASIC/HBM 的瞬态电流、板级空间、48V/54V/800V 电源架构和高频噪声，会把高端 MLCC 从普通被动元件变成 AI 服务器交付约束。

## 结论

- MLCC 不是所有料号都涨，而是 **AI server-grade 高容、高压、低 ESR/ESL、高可靠性、可贴近 xPU/HBM/VRM 的料号**紧。
- Murata 在 2025 IR Day 中把 AI server baseboard 电容数量上修到 15,000-25,000 颗，并估计 FY25-FY30 平均年增长 30%，FY2030 需求为 FY2025 的 3.3 倍。
- TDK 的 AI data center PSU 资料显示，数据中心 PSU 正从传统 kW 级走向 6-12 kW 及以上，要求 MLCC 有更高电压、更低 ESR、更高可靠性。
- Samsung Electro-Mechanics 指出 AI 服务器 PSU 超过 4 kW，LLC resonant circuit 中单个 PSU 段可能使用 10-80 颗高压 C0G MLCC。
- 投资上，MLCC 是“AI 服务器 BOM 的小金额大约束”：收入弹性不如 HBM，但 lead time、价格、board area 和客户认证会放大高端供应商的议价权。

## 为什么 AI 服务器更吃 MLCC

AI 服务器的 MLCC 增量不是来自“服务器台数”本身，而是来自三件事：

1. **瞬态电流更陡**：GPU/ASIC 在 workload 切换时电流尖峰大，需要大量去耦电容维持电压稳定。
2. **电源链更复杂**：UPS → PSU → IBC → VRM/PoL → xPU/HBM，48V/54V、±400V/+800V、垂直供电（VPD）让多个电压层级需要不同 MLCC。
3. **板级空间更贵**：HBM、光模块、VRM、冷板、连接器都在抢 PCB 面积，推动小尺寸高容 MLCC 和集成化 power module。

## 产业链含义

| 环节 | AI 服务器拉动 | 受益供应商 |
| --- | --- | --- |
| 高容小型 MLCC | xPU/HBM 附近去耦、减小板面积 | Murata、TDK、Samsung Electro-Mechanics、Taiyo Yuden、Yageo、Walsin |
| 高压 C0G MLCC | PSU LLC resonant、snubber、PFC/flying cap | Samsung Electro-Mechanics、TDK、Murata、KYOCERA AVX |
| 软端子/车规级可靠性 | 抗板弯、热循环、长期可靠性 | Murata、TDK、Samsung Electro-Mechanics |
| 电源模块/IBC/VPD | 更靠近 xPU 的二次供电 | Murata、TDK、Vicor、Delta、Lite-On、台达链 |
| 材料与设备 | 陶瓷粉体、镍电极、烧结、薄层堆叠 | 日本/韩国/台湾上游材料和 MLCC 设备链 |

## 和 HBM 的关系

MLCC 与 HBM 同向受益，但估值逻辑不同：

- HBM 是高 ASP、高技术壁垒、强客户绑定。
- MLCC 是低单价、高用量、强可靠性认证、板级不可替代。
- HBM 缺货直接限制 GPU/ASIC 出货；MLCC 缺货会延长主板、PSU、power module 交付周期。
- HBM 的风险是 KV cache 压缩和架构改变；MLCC 的风险是服务器架构标准化、power module 集成、供应商扩产后转为普通周期。

因此，MLCC 是 AI 服务器周期中的 **second-order bottleneck**：不会决定 AI 模型能不能训练，但会决定 AI 服务器能不能稳定、批量、低损耗交付。

## 需要跟踪的指标

| 指标 | 多头信号 | 风险信号 |
| --- | --- | --- |
| AI server-grade MLCC lead time | 16-20 周以上、分配制 | lead time 回落到常态 |
| Murata/TDK/Samsung 高端 MLCC capex | 扩高端线，不扩普通线 | 普通线扩产导致价格回落 |
| PSU/IBC/VPD 架构 | 6-12 kW+ PSU、54V/800V、垂直供电扩散 | 设计标准化降低 MLCC 密度 |
| AI rack power | 单 rack 功率继续上行 | AI 芯片能效改善抵消用量 |
| 高压 C0G/高容小尺寸 ASP | AI/汽车/工业料号提价 | 价格涨幅扩散到普通料号后需求破坏 |
| 供应商 book-to-bill | 高端料号 >1 | 库存和分销商囤货回补结束 |

## 三年判断

### 2026：高端 MLCC 紧张成立

AI 服务器从 GPU board 扩到 rack-scale system，PSU/IBC/VRM 同步升级。Murata 的 15,000-25,000 颗/baseboard 指引说明，MLCC 已经不是边角料，而是板级供电设计的一部分。高端料号的价格和交期有支撑。

### 2027：分化来自架构和扩产

如果 VPD、power module 和更高集成 IBC 普及，单板 MLCC 使用方式会改变：普通分立件可能减少，但模块内高性能 MLCC 和定制电容需求增加。赢家是能进入 power module 和高压/高容认证链的供应商。

### 2028：从短缺交易转向质量/客户绑定

若扩产充分，普通 MLCC 会回到周期品逻辑。但 AI/汽车/工业共用的高可靠料号仍有结构性溢价。届时要看客户认证、材料能力、薄层堆叠、良率、热模拟支持和模块化方案，而不是只看产能。

## 投资框架

MLCC 应该放在 AI 服务器“电力与板级可靠性”篮子里，而不是和 HBM 同一个估值框架。

```text
HBM = 算力内存带宽瓶颈
MLCC = 电源稳定性和板级交付瓶颈
光模块 = 集群互联瓶颈
电网/冷却 = 数据中心物理瓶颈
```

MLCC 最强的投资叙事是：AI rack power 上升、xPU/HBM 瞬态电流上升、板面积受限、power topology 复杂化，使高端 MLCC 的 **单机用量 × 单价 × 认证壁垒** 同时改善。

## 核心来源

- Murata IR Day 2025: https://corporate.murata.com/-/media/corporate/about/newsroom/news/irnews/irnews/2025/1201/2512-e-speach.ashx?cvid=20251204015903000000&la=en
- TDK MLCC Solutions for Data Center Power Systems: https://product.tdk.com/en/techlibrary/applicationnote/mlcc-solution-for-data-center-psu.html
- Samsung Electro-Mechanics high-voltage C0G MLCC: https://www.samsungsem.com/global/newsroom/news/view.do?id=8802
- Samsung Electro-Mechanics high-capacitance MLCC for power: https://weblib.samsungsem.com/product-news/view.do?idx=3722&language=en
