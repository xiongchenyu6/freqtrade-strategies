# AI Semiconductor Paper Library

更新日期：2026-06-27

这个目录保存 AI 半导体研究使用的开放论文 PDF。来源清单见 `manifest.csv`，下载状态见 `download_log.csv`。

## 当前覆盖

- Memory wall and AI processor bottlenecks
- KV cache compression and retrieval
- LLM serving systems
- Attention kernels and low precision
- MLA, linear attention, SSM, MoE architecture shifts
- CXL memory pooling and KV-cache disaggregation
- Compute-in-memory and near-memory compute
- Chiplet accelerator codesign
- Photonic and high-bandwidth datacenter interconnect
- Reasoning-specific inference hardware

## 下载状态

当前 manifest 29 条，其中 28 个开放 PDF 已下载，1 个页面型来源没有直接 PDF 链接。

重复运行：

```bash
python scripts/download_ai_semis_papers.py
```

脚本会跳过已存在且大于 1 KB 的 PDF，并刷新 `download_log.csv`。

## 研究用途

这批论文用于支撑：

- `docs/research/AI_SEMIS_PAPER_SYNTHESIS_NEW_IDEAS_2026.md`
- `docs/research/AI_MEMORY_WALL_ARCHITECTURE_ROADMAP_2026.md`
- `docs/research/AI_HARDWARE_BOTTLENECK_MATRIX_2026.md`
- `docs/research/AI_SEMIS_GLOBAL_LIQUIDITY_READER_REPORT_2026.md`
