-- 在 ClickHouse 中执行一次即可（或依赖 collector 启动时的 init）
CREATE DATABASE IF NOT EXISTS binance_futures;

CREATE TABLE IF NOT EXISTS binance_futures.futures_book_ticker
(
    symbol LowCardinality(String),
    bid_price Float64,
    bid_qty Float64,
    ask_price Float64,
    ask_qty Float64,
    update_id Int64,
    event_time DateTime64(3, 'UTC'),
    trans_time DateTime64(3, 'UTC'),
    recv_time DateTime64(3, 'UTC'),
    ingest_date Date MATERIALIZED toDate(recv_time)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ingest_date)
ORDER BY (symbol, recv_time)
TTL recv_time + toIntervalDay(120);

CREATE TABLE IF NOT EXISTS binance_futures.futures_depth_update
(
    symbol LowCardinality(String),
    first_update_id Int64,
    final_update_id Int64,
    prev_final_update_id Int64,
    bids_json String,
    asks_json String,
    event_time DateTime64(3, 'UTC'),
    trans_time DateTime64(3, 'UTC'),
    recv_time DateTime64(3, 'UTC'),
    stream LowCardinality(String) DEFAULT '',
    ingest_date Date MATERIALIZED toDate(recv_time)
)
ENGINE = MergeTree
PARTITION BY toYYYYMM(ingest_date)
ORDER BY (symbol, recv_time)
TTL recv_time + toIntervalDay(120);
