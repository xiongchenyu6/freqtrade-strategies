-- 030: enrich the value-chain bottleneck matrix with verified 2026 data points.
-- Source: deep-research run (2026-06-28), adversarially verified (3-0 votes, high confidence).
-- Only 6 of 10 segments had a current figure survive verification; PCB / liquid cooling /
-- AI networking / CXL-NAND remain open gaps (status_2026 left NULL — honest, not fabricated).
-- Apply: ssh oracle-arm-002 "sudo runuser -u postgres -- psql -d api -v ON_ERROR_STOP=1" < migrations/030_semi_segments_status.sql
BEGIN;

ALTER TABLE quant.semi_segments ADD COLUMN IF NOT EXISTS status_2026 text;
ALTER TABLE quant.semi_segments ADD COLUMN IF NOT EXISTS source_url  text;

UPDATE quant.semi_segments SET
  status_2026 = 'HBM3E 2026 实质售罄、报价上调 ~20%；Micron 2026 全年产能已锁；HBM4 末季放量 ~$500/颗，SK Hynix 占 NVIDIA HBM4 约 2/3',
  source_url  = 'https://www.trendforce.com/news/2025/12/24/news-samsung-sk-hynix-reportedly-plan-20-hbm3e-price-hike-for-2026-as-nvidia-h200-asic-demand-rises/'
  WHERE id = 1;

UPDATE quant.semi_segments SET
  status_2026 = '晶圆需求 370k→670k→~1.0M（2024→25→26）；产能 ~75–80k → 120–130k WPM（2026 末）；交期 52–78 周（满载）；NVIDIA 占 ~60%，前三客户 >85%',
  source_url  = 'https://siliconanalysts.com/analysis/foundry-allocation-status-q1-2026'
  WHERE id = 2;

UPDATE quant.semi_segments SET
  status_2026 = 'ABF 载板自 1H2026 重回供不应求；Ibiden FY2026–28 投 ~¥5000 亿（~$3.3B）扩 AI 级高性能载板（FY2027 量产，~2.5×）',
  source_url  = 'https://www.digitimes.com/news/a20251218PD207/abf-substrate-packaging-expansion-ai-gpu-capacity.html'
  WHERE id = 3;

UPDATE quant.semi_segments SET
  status_2026 = 'NVIDIA GB200 单板用 ~6,500 颗 MLCC；NVL72 整柜 ~44 万颗；下一代 Rubin 预估 ~12,000 颗/板',
  source_url  = 'https://insights.trendforce.com/p/mlcc-silicon-capacitor-power-integrity'
  WHERE id = 5;

UPDATE quant.semi_segments SET
  status_2026 = '12V→48V 把电流降 4×、I²R 损耗降 16×（核心物理驱动）；MPS 在 H100 设计中取代 Vicor',
  source_url  = 'https://newsletter.semianalysis.com/p/energizing-ai-power-delivery-competition'
  WHERE id = 6;

UPDATE quant.semi_segments SET
  status_2026 = '数据中心用电 ~415 TWh（2024）→ ~945 TWh（2030，IEA 基准）≈ 翻倍、~15%/年；地理高度聚集 → 并网成物理瓶颈',
  source_url  = 'https://www.iea.org/reports/energy-and-ai/energy-demand-from-ai'
  WHERE id = 9;

CREATE OR REPLACE VIEW api.semi_segments AS
SELECT id, segment, segment_zh, bottleneck, pricing_power, sub_risk,
       note_zh, track_metric, tickers, trend_tags, status_2026, source_url
FROM quant.semi_segments ORDER BY id;

GRANT SELECT ON api.semi_segments TO anon, authenticated, service_role;

COMMIT;
