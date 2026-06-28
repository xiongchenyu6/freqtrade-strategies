# AI Energy and Climate Paper Library

更新日期：2026-06-27

这个目录保存 AI 电力、能源、气候和数据中心负载研究使用的开放 PDF。来源清单见 `manifest.csv`，下载状态见 `download_log.csv`。

## 当前覆盖

- IEA `Energy and AI`
- LBNL U.S. data center electricity usage scenarios
- EPRI AI/data center electricity demand scenarios
- IEA-4E data center energy-use model review
- AI data center grid impacts
- Inference energy and carbon cost
- AI water footprint
- Green AI and model-training carbon accounting

## 下载状态

当前 manifest 13 条，其中 12 个开放 PDF 已下载，1 个 NREL 来源在当前环境无法解析，保留 source URL 供后续补抓。

重复运行：

```bash
python scripts/download_ai_semis_papers.py docs/research/papers/ai-energy-climate/manifest.csv
```

## 研究用途

这批资料用于把 AI 半导体研究扩展到：

- 数据中心电力需求
- 电网接入与 interconnection queue
- PPA、天然气、核电和可再生能源供给
- 液冷、PUE、water footprint
- AI efficiency rebound / Jevons effect
- climate and policy constraints
