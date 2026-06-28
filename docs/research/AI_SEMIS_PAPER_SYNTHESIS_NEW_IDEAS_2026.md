# AI 半导体论文综合：新的产业思路

更新日期：2026-06-27

资料基础：`docs/research/papers/ai-semiconductors/manifest.csv`，本地开放 PDF 论文库：`docs/research/papers/ai-semiconductors/`。

这份备忘录不做逐篇摘要，而是把论文信号转成产业判断。核心问题：如果 AI 架构继续演进，半导体链条中哪些环节会被重估？

## 总判断

论文给出的方向很清楚：AI 不会停止消耗算力和内存，但它会从“暴力堆 HBM”转向“分层内存 + 压缩缓存 + 混合架构 + 专用互联 + 系统级供电冷却”。这意味着未来三年不是简单的 HBM bull/bear，而是 **HBM 估值锚改变**：

```text
旧框架：模型越大 -> HBM 越多 -> 内存越贵
新框架：tokens 越多 -> 内存层级越复杂 -> 带宽、缓存调度、CXL/NAND、光互联、封装、供电一起重估
```

## 新思路一：HBM 会从“容量资产”变成“带宽与封装资产”

KV cache 压缩论文（TurboQuant、KIVI、KVQuant、XQuant、SAW-INT4、Fier）都在攻击同一件事：长上下文和高并发推理时，KV cache 吃掉太多 HBM。

产业推论：

- HBM 的 **容量溢价** 会受到压缩技术侵蚀。
- HBM 的 **带宽、低功耗、封装贴近 xPU、customer lock-in** 仍然强。
- 2026 HBM 仍紧；2027 后要把“每 token HBM GB”假设下修。
- 未来更该看 HBM4/HBM4E/custom HBM 的良率、带宽、封装协同，而不是只看总 GB 缺口。

投资翻译：内存股估值模型要从 `GB shipped` 改成 `effective bandwidth + advanced package attach + customer lock-in`。

## 新思路二：CXL/NAND 可能成为“KV 仓库”

Beluga、CXL-enabled KV-cache management、TraCT 这组论文说明，长上下文推理不一定把所有 KV cache 都放在 GPU HBM 里。未来可能出现：

```text
Hot KV: HBM
Warm KV: CXL pooled DRAM
Cold KV / expert weights / retrieval state: NAND or SSD tier
```

这和 Apple 的 sparse on-device route 一致：完整模型可以放在 NAND，按 prompt 把需要的专家加载到 DRAM。云端也可能把 KV 或上下文状态分层管理。

产业推论：

- CXL switch、CXL memory module、memory pooling 软件、SSD endurance、controller、NAND QoS 可能成为新增长点。
- HBM 不被完全替代，但会成为最热层，不再承担所有状态。
- 数据中心内存架构可能从“GPU 本地 HBM”变成“rack-scale memory hierarchy”。

新问题：谁能做 AI inference 的内存操作系统？这可能是未来基础设施软件的大机会。

## 新思路三：Attention 不再是单一架构，硬件会异构化

DeepSeek-V3/MLA、TransMLA、Kimi Linear、MiniMax、Mamba、Mamba-2、Gated DeltaNet 都指向同一趋势：纯 full attention 的统治地位被削弱，未来更像混合架构。

可能形态：

```text
少量 global/full attention
+ 多数 latent/linear/recurrent attention
+ MoE experts
+ retrieval/cache manager
+ test-time compute scheduler
```

产业推论：

- 通用 GPU 仍强，但 workload 变得更分裂。
- 推理芯片可能出现更强分工：prefill、decode、retrieval、verification、tool-call scheduling 不再是同一种硬件最优。
- 软件栈更重要：compiler、kernel、serving scheduler、memory manager 会决定硬件利用率。

新问题：如果模型架构从 full attention 转向 hybrid attention，谁的硬件/软件栈适配最快？这比只比较 TFLOPS 更重要。

## 新思路四：光互联会从“网络设备”变成“内存系统外延”

Photonic rails、InfiniteHBD、AI data center photonics 这组论文的核心不是“更快网络”，而是把 datacenter 内部连接变得更像高带宽域。

产业推论：

- 大模型训练和 agentic inference 的瓶颈从单 GPU 转向集群级 memory/communication。
- 1.6T/3.2T optics、silicon photonics、CPO、switch ASIC、DSP、retimer、低功耗 SerDes 会受益。
- 如果 CXL/rack-scale KV cache 成立，互联就不只是传梯度，而是在传状态和内存访问。

新问题：未来 AI data center 的核心资产可能不是单机，而是 high-bandwidth domain。谁能构建这个 domain，谁拿系统级利润。

## 新思路五：Chiplet/封装会成为 AI 设计自由度

Mozart chiplet codesign 和先进封装研究的共同含义：未来 AI accelerator 不一定靠单一巨大 die，而是靠 chiplet、HBM、interposer、substrate、die-to-die link、thermal 和 power 的协同。

产业推论：

- CoWoS/SoIC/2.5D/3D、ABF/SAP substrate、KGD testing、EDA 3DIC、thermal-aware design 会成为核心。
- 芯片设计公司会更依赖封装和 substrate 能力。
- 未来可能出现“chiplet marketplace”，但高端 AI 仍受良率、互联、软件和客户认证限制。

新问题：先进封装不只是产能瓶颈，也是产品架构本身。

## 新思路六：Reasoning hardware 可能不是传统 inference hardware

RPU/Reasoning Processing Unit 和 test-time compute 方向提醒我们：推理不是固定矩阵乘法。reasoning workload 有不同特征：

- 长上下文。
- 多分支生成。
- verification / self-consistency。
- tool calls。
- memory lookup。
- 动态算力分配。

产业推论：

- 只优化 dense GEMM 的芯片未必最适合 agentic reasoning。
- scheduler、cache、branch management、KV sharing、verification accelerator 可能变成新硬件/系统模块。
- 推理服务器可能拆成 prefill nodes、decode nodes、retrieval memory nodes、verification nodes。

新问题：AI data center 可能从 homogeneous GPU cluster 变成 heterogeneous reasoning factory。

## 新思路七：MLCC/VRM/液冷反而更确定

内存压缩会影响 HBM 容量需求，但不必然降低板级供电、MLCC、VRM、液冷、光模块需求。原因是效率提升通常会释放更多 tokens 和并发，系统总功率和瞬态电流仍然上行。

产业推论：

- MLCC、高端 PCB、ABF substrate、VRM/VPD、liquid cooling 是“系统交付瓶颈”，不完全受 KV 压缩冲击。
- 如果 AI 推理进入更高并发，供电和散热的稳定性反而更重要。
- 这些环节金额小于 GPU/HBM，但更适合作为“AI 服务器真实出货”的跟踪指标。

新问题：如果 HBM 估值被技术压缩，系统级瓶颈资产可能成为更稳的二阶受益者。

## 新思路八：端侧 AI 的内存逻辑和云端完全不同

Apple sparse on-device model 的启发是：端侧 AI 不会简单变成“手机装超大 DRAM”。它可能走：

```text
NAND 存完整模型
DRAM 加载当前专家
NPU 执行小激活参数
adapter/LoRA 做个性化
```

产业推论：

- 端侧 AI 对 HBM 基本不是直接需求。
- 对 NAND、LPDDR、NPU、controller、memory compression、OS-level model scheduling 更重要。
- 手机/PC AI 需求不能直接外推到 HBM。

新问题：端侧 AI 受益链更接近 Apple ecosystem、NAND/LPDDR、NPU、battery/thermal，不是云端 GPU/HBM 链的简单复制。

## 最值得继续挖的方向

### 1. KV Cache Index

建立一个 KV cache 技术指数：

- bits per KV element。
- cache hit/retrieval ratio。
- context length。
- batch size。
- quality loss。
- serving overhead。

目的：量化每篇论文对 HBM GB/token 假设的冲击。

### 2. Memory Hierarchy Map

建立 AI inference memory hierarchy：

```text
HBM -> GPU DRAM -> CXL DRAM -> host DRAM -> NAND/SSD -> object store
```

目的：判断哪些公司从 off-HBM memory 获益。

### 3. Reasoning Factory Architecture

把 agentic inference 拆成：

- prefill。
- decode。
- retrieval。
- tool call。
- verification。
- memory compaction。

目的：判断硬件是否会从 homogeneous GPU cluster 转向 specialized node cluster。

### 4. Power Integrity Tracker

把 MLCC/VRM/PCB/ABF/liquid cooling 和 rack power 绑定：

- rack kW。
- board current。
- MLCC count。
- PSU kW。
- liquid cooled rack share。

目的：找比 GPU 订单更早的 AI server 出货信号。

## 对读者的最终判断

论文没有告诉我们“HBM 会不会崩”。它告诉我们更重要的一件事：**AI 基础设施正在从单一芯片竞争，转向 memory hierarchy、系统互联、封装、供电、冷却、调度软件的整体竞争。**

所以未来三年的研究框架应该从：

```text
谁卖 GPU？
```

升级为：

```text
谁能让更多 tokens 在更低成本、更高可靠性、更大规模的数据中心里流动？
```

这个问题的答案，才是 AI 半导体真正的新思路。
