-- Run in Supabase SQL editor to create Deribit snapshots table

create table if not exists deribit_snapshots (
    id bigserial primary key,
    timestamp timestamptz not null default now(),
    spot_price numeric not null,
    total_candidates integer not null,
    top_candidates jsonb not null
);

create index if not exists idx_deribit_ts on deribit_snapshots (timestamp desc);
