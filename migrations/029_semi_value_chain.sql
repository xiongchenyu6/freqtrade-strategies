-- 029: deepen /semis from a coarse 5-tier stock list into a system-level value chain.
-- Two additions:
--   1. quant.semi_segments — the AI-server value-chain bottleneck matrix (system narrative,
--      not just chips). Static research data seeded here from
--      docs/research/AI_HARDWARE_BOTTLENECK_MATRIX_2026.md (scores 1-5: bottleneck strength,
--      pricing power, substitution risk) + tracking metric + representative tickers + trend tags.
--   2. semi_universe.stage / .trends — fine value-chain stage + technology-trend tags per ticker
--      (populated by nautilus_equity/semi_analysis.py), so the stock momentum view can group by
--      the real supply-chain stage and filter by trend.
-- Apply: ssh oracle-arm-002 "sudo runuser -u postgres -- psql -d api -v ON_ERROR_STOP=1" < migrations/029_semi_value_chain.sql
BEGIN;

-- 1) fine stage + trend tags on the stock universe ------------------------------------------
ALTER TABLE quant.semi_universe ADD COLUMN IF NOT EXISTS stage  text;
ALTER TABLE quant.semi_universe ADD COLUMN IF NOT EXISTS trends text[];

-- DROP + CREATE (not CREATE OR REPLACE): the live view's column order/set differs from the
-- original migration (012 appended market_cap), and CREATE OR REPLACE forbids reordering. The
-- view has no SQL dependents (PostgREST reads it at request time), so a drop is safe; re-GRANT below.
DROP VIEW IF EXISTS api.semi_universe;
CREATE VIEW api.semi_universe AS
SELECT symbol, name, tier, stage, trends, role, market_cap, last_price,
       ret_1w, ret_1m, ret_3m, ret_6m, ret_1y, ret_ytd,
       rs_vs_nvda, rs_vs_smh, corr_nvda, beta_nvda, vol_annual, from_52w_high,
       mom_score, alpha_score, alpha_note, updated_at
FROM quant.semi_universe;
GRANT SELECT ON api.semi_universe TO anon, authenticated, service_role;

-- 2) system-level value-chain bottleneck matrix ---------------------------------------------
CREATE TABLE IF NOT EXISTS quant.semi_segments (
    id            int PRIMARY KEY,         -- stable display order (upstream → downstream)
    segment       text NOT NULL,           -- en key
    segment_zh    text NOT NULL,
    bottleneck    int  NOT NULL CHECK (bottleneck    BETWEEN 1 AND 5),  -- 2026 瓶颈强度
    pricing_power int  NOT NULL CHECK (pricing_power BETWEEN 1 AND 5),  -- 定价权
    sub_risk      int  NOT NULL CHECK (sub_risk      BETWEEN 1 AND 5),  -- 技术替代风险
    note_zh       text NOT NULL,           -- 关键证据 (verbatim research note)
    track_metric  text NOT NULL,           -- 读者跟踪指标
    tickers       text[] NOT NULL DEFAULT '{}',  -- representative public tickers
    trend_tags    text[] NOT NULL DEFAULT '{}'
);

-- Idempotent reseed (research data — overwrite on each apply).
DELETE FROM quant.semi_segments;
INSERT INTO quant.semi_segments
  (id, segment, segment_zh, bottleneck, pricing_power, sub_risk, note_zh, track_metric, tickers, trend_tags) VALUES
 (1, 'HBM',              'HBM / 高带宽内存',  5,5,3,
   'HBM 绑定 GPU/ASIC 和先进封装，AI 训练与高吞吐推理仍强依赖高带宽。',
   'HBM3E/HBM4 合约价、客户锁量、良率、custom HBM',
   '{MU,"000660.KS","005930.KS"}', '{HBM,memory-wall,custom-HBM}'),
 (2, 'Advanced packaging','CoWoS / 先进封装', 5,5,2,
   'AI accelerator 需要 GPU/ASIC + HBM + interposer/substrate 组合交付。',
   'CoWoS 交期、OSAT capex、interposer/ABF 紧张',
   '{TSM,ASX,AMKR}', '{CoWoS,chiplet,hybrid-bonding,advanced-packaging}'),
 (3, 'IC substrate',     'IC 载板 / ABF',     5,4,2,
   'Ibiden 公布 FY2026-FY2028 约 5000 亿日元高性能 IC package substrate 投资，面向 AI/high-performance servers。',
   'Ibiden/Shinko/Unimicron/Nan Ya/Kinsus capex、客户预付款、SAP capacity',
   '{"4062.T","6967.T","3037.TW"}', '{ABF-substrate,advanced-packaging}'),
 (4, 'PCB',              'PCB / 高阶系统板',  4,3,2,
   '台湾 Q1 2026 PCB 产值受 AI server 拉动创高，关键材料如高阶玻纤布、铜箔紧张。',
   'AI server board ASP、层数、low-loss materials、铜箔/玻纤交期',
   '{}', '{low-loss-pcb,high-layer}'),
 (5, 'MLCC',             'MLCC / 电源完整性', 3,3,2,
   'Murata 把 AI server baseboard 电容数量上修到 15k-25k；TDK/Samsung 资料显示 AI PSU 进入更高功率和高压场景。',
   '高端 MLCC lead time、C0G/高容小型料号、PSU/VRM 认证',
   '{"6981.T","6762.T","2327.TW"}', '{MLCC,power-integrity}'),
 (6, 'VRM / VPD',        'VRM / 垂直供电',    4,4,2,
   'Infineon AI data center VRM 模块面向 280A、vertical power delivery 和 2.0A/mm2 power density。',
   '48V/54V 到 xPU 供电、phase count、VPD 采用率、power module ASP',
   '{IFNNY,MPWR,VICR}', '{VRM,vertical-power,power-integrity}'),
 (7, 'Liquid cooling',   '液冷 / 散热栈',     4,4,2,
   'AI rack density 上升推动 direct-to-chip liquid cooling；Vertiv/Schneider 均把 adaptive/direct-to-chip cooling 放在 2026 重点。',
   'liquid-cooled rack 占比、cold plate、CDU、quick disconnect、PUE',
   '{VRT,NVT,"SBGSY"}', '{liquid-cooling,thermal}'),
 (8, 'AI networking',    'AI 网络 / 光模块',  5,5,2,
   '大规模训练和 agentic inference 使 800G/1.6T/3.2T 光模块、switch ASIC、DSP 和 Ethernet fabric 成为利用率瓶颈。',
   '1.6T/3.2T ramp、CPO、硅光、Arista/Coherent/Credo 订单',
   '{ANET,COHR,CRDO,LITE,"300308.SZ"}', '{optical,CPO,silicon-photonics,800G-1.6T}'),
 (9, 'Power & grid',     '电力 / 并网',       5,4,1,
   'IEA 和数据中心公司均指出 AI 电力和并网成为物理约束。',
   'PPA、grid queue、天然气/核电、UPS/transformer 交期',
   '{VRT,GEV,ETN,CEG}', '{datacenter-power,grid}'),
 (10,'CXL / NAND tier',  'CXL / NAND 内存层级',3,3,3,
   'Apple 式 NAND-to-DRAM 专家加载、KV offload、CXL memory pooling 会改变热/温/冷内存分层。',
   'CXL adoption、SSD endurance、KV offload、NAND attach rate',
   '{MU,SNDK,MRVL}', '{CXL,NAND,KV-offload,memory-wall}');

CREATE OR REPLACE VIEW api.semi_segments AS
SELECT id, segment, segment_zh, bottleneck, pricing_power, sub_risk,
       note_zh, track_metric, tickers, trend_tags
FROM quant.semi_segments ORDER BY id;

GRANT SELECT ON api.semi_segments TO anon, authenticated, service_role;
GRANT SELECT, INSERT, UPDATE, DELETE ON quant.semi_segments TO quant;

COMMIT;
