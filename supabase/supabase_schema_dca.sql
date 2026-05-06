-- Run this in Supabase SQL editor to create the DCA logging table

create table if not exists dca_log (
    id bigserial primary key,
    timestamp timestamptz not null default now(),
    mode text not null,                  -- 'dry_run' or 'live'
    base_usdt numeric not null,
    multiplier numeric not null,
    amount_usdt numeric not null,
    fng_value integer,
    cycle_score numeric,
    news_score numeric,
    kol_score numeric,
    cycle_signal text,
    explain jsonb,
    order_result jsonb
);

create index if not exists idx_dca_log_ts on dca_log (timestamp desc);
create index if not exists idx_dca_log_mode on dca_log (mode);
