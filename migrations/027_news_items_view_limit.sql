-- 027: widen public news feed view for /globe.
-- The globe needs breadth across source cities; 200 latest rows can be crowded out
-- by high-volume feeds, so expose the same curated table with a larger read cap.
BEGIN;
CREATE OR REPLACE VIEW api.news_items AS
  SELECT published_at, source, category, title, link FROM quant.news_items
  ORDER BY published_at DESC NULLS LAST LIMIT 1000;
GRANT SELECT ON api.news_items TO anon, authenticated;
COMMIT;
