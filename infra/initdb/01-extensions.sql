-- Extensions required by Quanta.
-- TimescaleDB powers the kline / funding hypertables added in phase 1.
CREATE EXTENSION IF NOT EXISTS timescaledb;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;
