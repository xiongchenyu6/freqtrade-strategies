-- 025: market news feed — the REAL "news-driven" layer (learned from World Monitor's
-- aggregation pattern; our own implementation, AGPL-free, market-relevant sources only).
-- game box fetches curated RSS every 20 min → here → web reads our API (CF/CN-proof).
-- Apply: ssh oracle-arm-002 sudo runuser -u postgres -- psql -d api -f - < migrations/025_news_items.sql
BEGIN;
CREATE TABLE IF NOT EXISTS quant.news_items (
  id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
  fetched_at   timestamptz NOT NULL DEFAULT now(),
  published_at timestamptz,
  source       text NOT NULL,             -- 'CoinDesk' | 'Fed' | ...
  category     text NOT NULL,             -- 'crypto' | 'macro' | 'equity'
  title        text NOT NULL,
  link         text NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS news_items_pub_idx ON quant.news_items (published_at DESC NULLS LAST);
GRANT SELECT, INSERT, DELETE ON quant.news_items TO quant;
CREATE OR REPLACE VIEW api.news_items AS
  SELECT published_at, source, category, title, link FROM quant.news_items
  ORDER BY published_at DESC NULLS LAST LIMIT 200;
GRANT SELECT ON api.news_items TO anon, authenticated;
COMMIT;
