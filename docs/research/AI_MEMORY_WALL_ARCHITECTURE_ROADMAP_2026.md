# AI 架构路线图与内存墙重估（2026-2028）

更新日期：2026-06-26

配套论文雷达：`docs/research/ai_memory_wall_papers.csv`

本地论文库：`docs/research/papers/ai-semiconductors/`。当前已下载开放 PDF 28 篇，下载清单见 `docs/research/papers/ai-semiconductors/manifest.csv`。

这份报告回答一个更核心的问题：AI 的技术路线会不会突破内存墙，从而改变 HBM/DRAM/LPDDR/NAND 的需求和估值？结论不是简单的“内存利空”或“内存继续涨”，而是：**内存需求会从“堆容量”转向“买带宽、买封装、买能效、买可调度性”；HBM 的容量溢价会被技术压缩，但高带宽和先进封装的战略价值仍会维持。**

## 先把问题拆清楚

AI 的“内存墙”不是一个问题，而是五类问题：

| 场景 | 内存压力来源 | 主要瓶颈 | 最可能的解决方向 | 对 HBM 的影响 |
| --- | --- | --- | --- | --- |
| 训练 | 参数、梯度、优化器状态、激活 | 容量 + 带宽 + 通信 | FP8/FP4、ZeRO、MoE、重计算、网络优化 | HBM 仍强，技术只降低单位训练成本 |
| Prefill | 长 prompt 一次性吃入 | 带宽 + attention 计算 | FlashAttention、稀疏/线性 attention、prompt 压缩 | 需求从容量转向有效带宽 |
| Decode | 每 token 读取权重和 KV cache | KV cache 容量 + 带宽 | KV 量化、MLA、PagedAttention、近内存计算 | 对 HBM 容量最利空 |
| Agent 长上下文 | 多轮工具调用、长历史、RAG | KV cache 和并发 | retrieval cache、cache eviction、TurboQuant、linear attention | 降低每会话 HBM，但扩大可用需求 |
| 端侧 AI | 手机/PC DRAM 有限、功耗有限 | active weights + 延迟 | 2-bit QAT、adapter、NAND-to-DRAM 专家加载 | 对云 HBM 替代有限，但压低端侧 DRAM 假设 |

投资含义：不能再用“AI 越多 -> HBM GB 越多 -> 内存股一直涨”这个线性模型。应该改成：

```text
AI 内存需求 = token 量 × context 长度 × 并发 × 每 token 内存占用 ÷ 压缩/架构效率
HBM 收入 = 有效带宽需求 × HBM 供给稀缺度 × 先进封装约束 × 客户锁量能力
```

其中，分母正在被论文和工程快速改变。

## 最新论文和工程路线：哪些真的会动到内存市场

### 1. KV cache 压缩：最直接打 HBM 容量需求

自回归推理时，模型每生成一个 token，都要保留之前 token 的 Key/Value。上下文越长、并发越高，KV cache 越快吃掉显存。2024-2026 年最密集的突破集中在这里。

关键论文/技术：

- **TurboQuant, Google Research, ICLR 2026**：Google 称可把 KV cache 至少压缩 6 倍，attention 相关计算最高加速 8 倍，且几乎无精度损失。
- **KIVI**：2-bit KV cache 量化，证明 KV 不必一直以高精度保存。
- **KVQuant**：动态压缩激活，支持更长上下文或更大 batch。
- **XQuant**：不直接缓存完整 K/V，而缓存低 bit 中间输入，再重算 K/V，本质是用更多计算换更少内存。
- **SAW-INT4**：把 4-bit KV 量化做成系统协同问题，强调 fused kernel 和真实 serving 约束。
- **vLLM/PagedAttention**：不改变模型结构，但显著降低 KV cache 碎片化，提高显存利用率。

判断：这一路线对 HBM **容量需求**最利空，但对 **总 AI 需求**不一定利空。原因是成本下降会让更多应用打开长上下文、多 agent 和高并发。类似云计算历史上的虚拟化：单 VM 更省资源，但总服务器需求没有消失。

对内存估值：如果 2026-2027 年 TurboQuant/INT4 KV 进入主流 serving 框架，HBM 的“每 token 需要多少 GB”假设必须下修，内存股的估值逻辑会从“容量短缺”切到“带宽、良率、锁单、封装能力”。

### 2. 架构级压缩：从根上减少需要缓存的东西

比 KV cache 量化更重要的是模型结构变化。它不是把大缓存压小，而是减少模型本来需要保存的缓存。

关键路线：

- **MLA / DeepSeek-V3**：Multi-head Latent Attention 通过低秩 latent KV 状态减少缓存。DeepSeek 的路线证明，先进模型可以在架构层面压缩 KV，而不是只靠部署时量化。
- **TransMLA**：尝试把 MLA 思路迁移到已有 MHA 模型，若成立，会降低架构切换成本。
- **Kimi Linear**：混合线性 attention，报告最多 75% KV cache 降低和 1M context 下最高 6x decoding throughput。
- **MiniMax-01 / MiniMax-M1**：Lightning attention + MoE，目标是百万 token context 和推理时计算扩展。
- **Mamba / Mamba-2 / Gated DeltaNet / Gated DeltaNet-2**：用固定大小 recurrent state 替代无界 KV cache，理论上能把 decode memory 做成常数级。

判断：纯 SSM/RNN 还没有完全取代 Transformer，但**混合架构正在变成主流方向**。未来 frontier model 很可能不是纯 full attention，而是：

```text
少量 full/global attention 层 + 多数 linear/latent/sparse attention 层 + MoE/adapter
```

这意味着 HBM 需求不会消失，但长上下文的 KV cache 曲线可能从“线性爆炸”变成“受控增长”。

对内存估值：这是比量化更结构性的风险。如果 2027 年主流闭源/开源模型都开始采用 MLA、linear attention 或 hybrid SSM，市场需要给 HBM 容量需求打折。但它同时会提高网络、调度、编译器、kernel、低精度硬件的重要性。

### 3. Apple 路线：端侧 AI 不等于端侧大内存

用户提到 Apple 很关键。Apple 不是简单把超大模型塞进手机 DRAM，而是在绕开 DRAM 限制。

Apple 2025 技术报告显示：on-device 模型使用 KV-cache sharing 和 2-bit quantization-aware training，server model 使用 Parallel-Track MoE 和 global-local attention。Apple 2026 第三代 Foundation Models 更明确：20B on-device sparse 模型只激活 1-4B 参数，把完整模型放在 NAND 中，每个 prompt 选择专家加载到 DRAM，并周期性重选。

这背后的产业含义：

- 端侧 AI 会推动 **NAND/flash、统一内存带宽、NPU、软件调度**，不一定等同于手机 DRAM/HBM 暴增。
- 小模型、adapter、LoRA、专家加载会让“每个功能一套完整模型”的内存假设失效。
- Apple 的路线是“以软件和系统控制内存”，不是“用更多内存解决所有问题”。

对内存估值：端侧 AI 对 LPDDR、NAND、控制器、NPU 有支撑，但它不能直接外推成 HBM 超级周期。云端高吞吐推理和训练才是 HBM 的核心。

### 4. 近内存计算与替代内存：HBM 税会被攻击

软件在压 KV cache，硬件也在攻击 HBM 的成本结构。

Qualcomm 2026 Dragonfly/HBC 路线很典型：它把 memory 和 compute die 融合，宣称 AI250 HBC Gen 1 每 rack 有 7.4 PB/s effective memory bandwidth，目标是绕开 HBM 的 2.5D 封装和成本。官方也明确把 HBC 定义为解决 inference decode memory wall 的架构。

这类路线包括：

- LPDDR + 近内存计算：更低功耗、更大容量、更便宜，但生态和通用性待验证。
- CXL memory pooling：让系统在 HBM 之外接更多共享 DRAM，适合 KV offload、prefill/decode 分离。
- HBM + compute-in-memory / near-data processing：在 HBM 或 CXL 侧减少数据搬运。

判断：短期替代不了 NVIDIA/AMD/TPU 的 HBM 主链，尤其训练和高端 prefill 仍需要极高带宽。但中期会对 **inference-only** 市场形成价格锚。如果某些 agentic inference 工作负载可在 HBC/LPDDR/CXL 上跑得足够好，HBM 的边际定价权会被削弱。

## 内存价格会如何绑定

### 2026：HBM 仍然强，原因不是没人研究压缩

2026 年 HBM 强势仍成立，原因有四个：

1. 训练和 frontier prefill 仍需要最高带宽。
2. HBM4/HBM4E 良率、封装、base die、CoWoS/SoIC 都不是一夜扩出来。
3. NVIDIA/AMD/ASIC 设计已绑定 HBM 路线，客户订单和验证周期长。
4. 推理需求在爆发，效率提升会先转化为更多 tokens 和更长 context。

所以 2026 不能因为 TurboQuant 或 Apple 就简单做空 HBM。

### 2027：价格弹性开始变大

2027 年是关键分水岭。若出现三件事，HBM 价格会从“供不应求”转向“结构分化”：

- HBM4/HBM4E 供应释放，Samsung/SK hynix/Micron 都进入稳定量产。
- KV cache 压缩成为 vLLM、TensorRT-LLM、Triton、MLX 等框架默认选项。
- 主流模型从 full attention 转向 MLA/linear/hybrid attention。

届时，高端 HBM 仍有溢价，但普通 HBM3E/部分 DRAM 的涨价逻辑会被削弱。市场会从买“所有内存”切换到买“能跟上 NVIDIA/ASIC roadmap 的 HBM、封装和定制 memory”。

### 2028：内存进入重新估值

到 2028 年，内存市场可能分成三类：

| 类别 | 需求弹性 | 估值逻辑 |
| --- | --- | --- |
| HBM4E/Custom HBM/先进封装绑定 | 高 | 仍是战略资产，取决于客户锁单和良率 |
| 普通 DRAM/DDR/部分 LPDDR | 中 | 受端侧 AI、服务器扩容支撑，但周期性更强 |
| NAND/flash/CXL memory tier | 上升 | 受 Apple 式专家加载、RAG、冷/温 KV、memory pooling 支撑 |

非共识判断：**AI 可能不再单纯推高所有内存价格，而是把内存价值从“容量”重新分配到“带宽 + 层级 + 调度 + 封装”。**

## Jevons 悖论：效率提升到底利空还是利多？

这是判断内存股最关键的一步。

效率提升有两种结果：

1. **替代效应**：同样任务需要更少 HBM，内存需求下降。
2. **规模效应**：成本降低后，更多任务被创造出来，总 token、上下文和并发暴增，内存需求反而上升。

我们判断：

- 2026：规模效应更强。压缩技术刚部署，AI 应用还在扩张，效率提升主要释放需求。
- 2027：两者拉锯。若供应释放 + 压缩普及，HBM 价格弹性上升。
- 2028：取决于 ROI。若 agent、代码、视频、多模态、企业流程 automation 真正变现，规模效应继续；若 monetization 不足，替代效应会主导，内存估值下修。

## 对产业链的重新排序

### 更受益

- HBM4/HBM4E/custom HBM 良率领先者。
- 先进封装：CoWoS、SoIC、interposer、ABF、OSAT、测试。
- 网络/光模块：效率提升会扩大 tokens 和集群并发。
- 编译器和 serving 软件：vLLM、TensorRT-LLM、MLX、Triton、kernel fusion。
- NAND/CXL/内存层级管理：如果 Apple 式 NAND-to-DRAM 专家加载扩散。

### 受挑战

- 只押普通 DRAM 容量扩张的叙事。
- 把所有 AI capex 都等同于 HBM 的估值模型。
- 没有先进封装、没有客户锁单、没有定制 HBM 能力的二线内存供应。
- 只擅长 full attention 推理但没有 KV 压缩、低精度和调度生态的硬件。

## 我们的三年判断

### 基准判断

内存墙不会被“一项技术”彻底打破，但会被一组技术持续削弱。HBM 不会被替代掉，但 HBM 的投资逻辑会从“只看 GB 缺口”转为“看 bandwidth、customization、packaging、customer lock-in 和 software stack”。

### 最重要的观察点

1. TurboQuant/INT4 KV 是否进入主流 serving 框架默认路径。
2. 2027 年主流模型是否采用 MLA/linear/hybrid attention。
3. Apple 20B sparse-on-device 路线是否被 Android/PC 阵营模仿。
4. Qualcomm HBC、CXL memory pooling 是否拿到真实 hyperscaler inference 工作负载。
5. HBM4E/custom HBM 是否继续供不应求，还是供给提前释放。

### 投资结论

2026 仍然不能轻易看空 HBM，因为供给、封装、客户锁单和训练需求都还在支撑。但从 2027 开始，必须给内存股估值加入“技术压缩折价”。最危险的是把 2025-2026 的 HBM 供不应求线性外推到 2028。

更好的框架是：

```text
短期：HBM 仍是瓶颈，价格强。
中期：KV 压缩和混合架构降低每 token 内存，价格弹性上升。
长期：价值转向 memory hierarchy、custom HBM、near-memory compute、NAND/CXL、软件调度。
```

这才是读者需要抓住的 AI 发展脉络：**AI 不会停止吃内存，但会越来越聪明地吃内存。内存市场不会消失，估值锚会改变。**

## 核心来源

- Apple Third Generation Foundation Models: https://machinelearning.apple.com/research/introducing-third-generation-of-apple-foundation-models
- Apple Foundation Models Tech Report 2025: https://machinelearning.apple.com/research/apple-foundation-models-tech-report-2025
- Google TurboQuant: https://research.google/blog/turboquant-redefining-ai-efficiency-with-extreme-compression/
- TurboQuant OpenReview: https://openreview.net/forum?id=tO3ASKZlok
- KIVI: https://arxiv.org/abs/2402.02750
- vLLM / PagedAttention: https://arxiv.org/abs/2309.06180
- FlashAttention-3: https://arxiv.org/abs/2407.08608
- DeepSeek-V3: https://arxiv.org/abs/2412.19437
- TransMLA: https://arxiv.org/abs/2502.07864
- Kimi Linear: https://arxiv.org/abs/2510.26692
- MiniMax-01: https://arxiv.org/abs/2501.08313
- Mamba: https://arxiv.org/abs/2312.00752
- Gated DeltaNet-2: https://arxiv.org/abs/2605.22791
- Qualcomm Dragonfly AI Accelerators / HBC: https://www.qualcomm.com/data-center/expertise/ai-accelerators
- SK hynix HBM4: https://news.skhynix.com/sk-hynix-completes-worlds-first-hbm4-development-and-readies-mass-production/
- Samsung HBM4: https://news.samsung.com/global/samsung-ships-industry-first-commercial-hbm4-with-ultimate-performance-for-ai-computing
