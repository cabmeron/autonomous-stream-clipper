-- PostgreSQL Schema for Autonomous Twitch Stream Clipper
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS triage_clips (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    channel_name VARCHAR(64) NOT NULL,
    video_url TEXT NOT NULL,
    thumbnail_url TEXT,
    duration_seconds NUMERIC(5, 2) NOT NULL,
    cut_start NUMERIC(6, 2) NOT NULL,
    cut_end NUMERIC(6, 2) NOT NULL,
    chat_velocity_peak NUMERIC(6, 2),
    spike_ratio NUMERIC(5, 2),
    ocr_pnl_delta NUMERIC(12, 2),
    ocr_multiplier NUMERIC(8, 2),
    heuristic_score INTEGER NOT NULL,
    suggested_title VARCHAR(255) NOT NULL,
    suggested_caption TEXT NOT NULL,
    transcript_json JSONB,
    status VARCHAR(32) DEFAULT 'pending_triage',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_triage_clips_status ON triage_clips(status);
CREATE INDEX IF NOT EXISTS idx_triage_clips_created ON triage_clips(created_at DESC);
