-- R-144 C：生产库结构快照（只含 schema，不含任何数据）
-- 来源：上线前本地运行库（27 张表，R-143 时点）
-- 用途：tests/test_r144_schema_guard.py 用它模拟「老库」，跑 init_db() 后断言模型每一列都存在。
-- ⚠ 不要随手刷新这份快照：它代表「从哪个版本升级」的起点；
--   只有明确不再支持从该版本升级时，才替换为新快照。

CREATE TABLE ai_prompts (
	id INTEGER NOT NULL, 
	"key" VARCHAR(40) NOT NULL, 
	version INTEGER NOT NULL, 
	content TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	note TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_prompt_version UNIQUE ("key", version)
);
CREATE TABLE app_kv (
	"key" VARCHAR(60) NOT NULL, 
	value TEXT NOT NULL, 
	PRIMARY KEY ("key")
);
CREATE TABLE background_tasks (
	id INTEGER NOT NULL, 
	kind VARCHAR(50) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	progress INTEGER NOT NULL, 
	payload TEXT NOT NULL, 
	error TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, note VARCHAR(255) NOT NULL DEFAULT '', result TEXT NOT NULL DEFAULT '', 
	PRIMARY KEY (id)
);
CREATE TABLE chat_conversations (
	id INTEGER NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE chat_messages (
	id INTEGER NOT NULL, 
	conversation_id INTEGER, 
	role VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(conversation_id) REFERENCES chat_conversations (id) ON DELETE CASCADE
);
CREATE TABLE creator_account_snapshots (
	id INTEGER NOT NULL, 
	account_id INTEGER NOT NULL, 
	snapshot_date VARCHAR(10) NOT NULL, 
	nickname VARCHAR(100) NOT NULL, 
	followers INTEGER NOT NULL, 
	likes_total INTEGER NOT NULL, 
	posts_total INTEGER NOT NULL, 
	following INTEGER NOT NULL, 
	raw TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_acct_snap UNIQUE (account_id, snapshot_date), 
	FOREIGN KEY(account_id) REFERENCES creator_accounts (id)
);
CREATE TABLE creator_accounts (
	id INTEGER NOT NULL, 
	creator_id INTEGER NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	nickname VARCHAR(100) NOT NULL, 
	home_link VARCHAR(500) NOT NULL, 
	platform_user_id VARCHAR(200) NOT NULL, 
	avatar_path VARCHAR(255) NOT NULL, 
	avatar_url VARCHAR(1000) NOT NULL, 
	extra_config TEXT NOT NULL, 
	enabled BOOLEAN NOT NULL, 
	sync_frequency VARCHAR(10) NOT NULL, 
	last_sync_at DATETIME, 
	sync_status VARCHAR(20) NOT NULL, 
	sync_message TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id)
);
CREATE TABLE creators (
	id INTEGER NOT NULL, 
	kind VARCHAR(10) NOT NULL, 
	parent_id INTEGER, 
	name VARCHAR(100) NOT NULL, 
	note TEXT NOT NULL, 
	is_current BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(parent_id) REFERENCES creators (id)
);
CREATE TABLE draft_discussions (
	id INTEGER NOT NULL, 
	draft_id INTEGER NOT NULL, 
	round INTEGER NOT NULL, 
	actor VARCHAR(20) NOT NULL, 
	kind VARCHAR(20) NOT NULL, 
	content TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(draft_id) REFERENCES drafts (id) ON DELETE CASCADE
);
CREATE TABLE drafts (
	id INTEGER NOT NULL, 
	creator_id INTEGER, 
	video_id INTEGER, 
	title VARCHAR(255) NOT NULL, 
	cover_text VARCHAR(100) NOT NULL, 
	script TEXT NOT NULL, 
	platform_shells TEXT NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	original_script TEXT NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, source_ref TEXT NOT NULL DEFAULT '{}', tags TEXT NOT NULL DEFAULT '[]', prompt_version INTEGER NOT NULL DEFAULT 0, persona_version INTEGER NOT NULL DEFAULT 0, quality TEXT NOT NULL DEFAULT '{}', 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id), 
	FOREIGN KEY(video_id) REFERENCES videos (id)
);
CREATE TABLE feedback (
	id INTEGER NOT NULL, 
	draft_id INTEGER NOT NULL, 
	liked BOOLEAN, 
	rating INTEGER, 
	comment TEXT NOT NULL, 
	hook_score INTEGER, 
	pace_score INTEGER, 
	ending_score INTEGER, 
	style_score INTEGER, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(draft_id) REFERENCES drafts (id)
);
CREATE TABLE hot_topics (
	id INTEGER NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	heat VARCHAR(50) NOT NULL, 
	url VARCHAR(500) NOT NULL, 
	raw TEXT NOT NULL, 
	topic_date VARCHAR(10) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_hot UNIQUE (platform, title, topic_date)
);
CREATE TABLE metrics_snapshots (
	id INTEGER NOT NULL, 
	video_id INTEGER NOT NULL, 
	snapshot_date VARCHAR(10) NOT NULL, 
	plays INTEGER NOT NULL, 
	likes INTEGER NOT NULL, 
	favorites INTEGER NOT NULL, 
	comments INTEGER NOT NULL, 
	followers_gained INTEGER NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_metrics UNIQUE (video_id, snapshot_date), 
	FOREIGN KEY(video_id) REFERENCES videos (id)
);
CREATE TABLE notifications (
	id INTEGER NOT NULL, 
	kind VARCHAR(30) NOT NULL, 
	status VARCHAR(10) NOT NULL, 
	title VARCHAR(200) NOT NULL, 
	message TEXT NOT NULL, 
	target VARCHAR(255) NOT NULL, 
	read BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE persona_checks (
	id INTEGER NOT NULL, 
	creator_id INTEGER, 
	mode VARCHAR(20) NOT NULL, 
	source_count INTEGER NOT NULL, 
	coverage FLOAT NOT NULL, 
	semantic FLOAT, 
	passed BOOLEAN NOT NULL, 
	fallback BOOLEAN NOT NULL, 
	detail TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id)
);
CREATE TABLE persona_tags (
	id INTEGER NOT NULL, 
	creator_id INTEGER, 
	label VARCHAR(100) NOT NULL, 
	description TEXT NOT NULL, 
	category VARCHAR(20) NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	version INTEGER NOT NULL, 
	created_at DATETIME NOT NULL, dimension VARCHAR(30) NOT NULL DEFAULT '', 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id)
);
CREATE TABLE pipeline_runs (
	id INTEGER NOT NULL, 
	run_date VARCHAR(10) NOT NULL, 
	status VARCHAR(20) NOT NULL, 
	candidates_count INTEGER NOT NULL, 
	generated_count INTEGER NOT NULL, 
	error TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE platform_post_comments (
	id INTEGER NOT NULL, 
	post_id INTEGER NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	text TEXT NOT NULL, 
	user_nick VARCHAR(100) NOT NULL, 
	created_at DATETIME NOT NULL, likes INTEGER NOT NULL DEFAULT 0, 
	PRIMARY KEY (id), 
	FOREIGN KEY(post_id) REFERENCES platform_posts (id)
);
CREATE TABLE platform_post_stats (
	id INTEGER NOT NULL, 
	post_id INTEGER NOT NULL, 
	stat_date VARCHAR(10) NOT NULL, 
	plays INTEGER NOT NULL, 
	likes INTEGER NOT NULL, 
	favorites INTEGER NOT NULL, 
	shares INTEGER NOT NULL, 
	comments INTEGER NOT NULL, 
	extra TEXT NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_post_stat UNIQUE (post_id, stat_date), 
	FOREIGN KEY(post_id) REFERENCES platform_posts (id)
);
CREATE TABLE platform_posts (
	id INTEGER NOT NULL, 
	account_id INTEGER NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	platform_post_id VARCHAR(200) NOT NULL, 
	title VARCHAR(500) NOT NULL, 
	"desc" TEXT NOT NULL, 
	tags TEXT NOT NULL, 
	cover_url VARCHAR(1000) NOT NULL, 
	cover_path VARCHAR(255) NOT NULL, 
	video_url VARCHAR(1000) NOT NULL, 
	publish_time DATETIME, 
	raw TEXT NOT NULL, 
	local_video_id INTEGER, 
	work_id INTEGER, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, is_ad BOOLEAN NOT NULL DEFAULT 0, ad_price INTEGER, 
	PRIMARY KEY (id), 
	CONSTRAINT uq_platform_post UNIQUE (platform, platform_post_id), 
	FOREIGN KEY(account_id) REFERENCES creator_accounts (id), 
	FOREIGN KEY(local_video_id) REFERENCES videos (id), 
	FOREIGN KEY(work_id) REFERENCES works (id)
);
CREATE TABLE prompt_evals (
	id INTEGER NOT NULL, 
	"key" VARCHAR(40) NOT NULL, 
	candidate_version INTEGER NOT NULL, 
	base_version INTEGER NOT NULL, 
	candidate_score FLOAT NOT NULL, 
	base_score FLOAT NOT NULL, 
	supported BOOLEAN NOT NULL, 
	reason TEXT NOT NULL, 
	detail TEXT NOT NULL, 
	created_at DATETIME NOT NULL, 
	PRIMARY KEY (id)
);
CREATE TABLE sync_jobs (
	id INTEGER NOT NULL, 
	job_type VARCHAR(20) NOT NULL, 
	scope VARCHAR(20) NOT NULL, 
	creator_id INTEGER, 
	account_id INTEGER, 
	post_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	message TEXT NOT NULL, 
	stats TEXT NOT NULL, 
	started_at DATETIME NOT NULL, 
	finished_at DATETIME, 
	created_at DATETIME NOT NULL, progress_total INTEGER NOT NULL DEFAULT 0, progress_done INTEGER NOT NULL DEFAULT 0, progress_note VARCHAR(255) NOT NULL DEFAULT '', 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id), 
	FOREIGN KEY(account_id) REFERENCES creator_accounts (id), 
	FOREIGN KEY(post_id) REFERENCES platform_posts (id)
);
CREATE TABLE topic_candidates (
	id INTEGER NOT NULL, 
	run_date VARCHAR(10) NOT NULL, 
	hot_topic_id INTEGER, 
	title VARCHAR(255) NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	score INTEGER NOT NULL, 
	reason TEXT NOT NULL, 
	draft_id INTEGER, 
	created_at DATETIME NOT NULL, slot VARCHAR(10) NOT NULL DEFAULT '', 
	PRIMARY KEY (id), 
	FOREIGN KEY(hot_topic_id) REFERENCES hot_topics (id), 
	FOREIGN KEY(draft_id) REFERENCES drafts (id)
);
CREATE TABLE topic_ideas (
	id INTEGER NOT NULL, 
	source VARCHAR(20) NOT NULL, 
	platform VARCHAR(20) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	detail TEXT NOT NULL, 
	post_id INTEGER, 
	post_title VARCHAR(500) NOT NULL, 
	creator_id INTEGER, 
	snapshot_date VARCHAR(10) NOT NULL, 
	used BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, likes INTEGER NOT NULL DEFAULT 0, 
	PRIMARY KEY (id), 
	FOREIGN KEY(post_id) REFERENCES platform_posts (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id)
);
CREATE TABLE transcripts (
	id INTEGER NOT NULL, 
	video_id INTEGER NOT NULL, 
	source_text TEXT NOT NULL, 
	transcript_text TEXT NOT NULL, 
	corrected_text TEXT NOT NULL, 
	asr_status VARCHAR(20) NOT NULL, 
	created_at DATETIME NOT NULL, asr_provider VARCHAR(20) NOT NULL DEFAULT '', asr_model VARCHAR(100) NOT NULL DEFAULT '', 
	PRIMARY KEY (id), 
	FOREIGN KEY(video_id) REFERENCES videos (id)
);
CREATE TABLE videos (
	id INTEGER NOT NULL, 
	filename VARCHAR(255) NOT NULL, 
	title VARCHAR(255) NOT NULL, 
	cover_path VARCHAR(255) NOT NULL, 
	platforms TEXT NOT NULL, 
	creator_id INTEGER, 
	platform_post_id VARCHAR(200) NOT NULL, 
	work_id INTEGER, 
	status VARCHAR(20) NOT NULL, 
	planned_publish_at DATETIME, 
	published_at DATETIME, 
	is_ad BOOLEAN NOT NULL, 
	main_topics TEXT NOT NULL, 
	tags TEXT NOT NULL, 
	tags_confirmed BOOLEAN NOT NULL, 
	created_at DATETIME NOT NULL, ad_price INTEGER, 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id), 
	FOREIGN KEY(work_id) REFERENCES works (id)
);
CREATE TABLE works (
	id INTEGER NOT NULL, 
	creator_id INTEGER, 
	title VARCHAR(500) NOT NULL, 
	cover_path VARCHAR(255) NOT NULL, 
	created_at DATETIME NOT NULL, 
	updated_at DATETIME NOT NULL, 
	PRIMARY KEY (id), 
	FOREIGN KEY(creator_id) REFERENCES creators (id)
);
CREATE INDEX ix_ai_prompts_key ON ai_prompts ("key");
CREATE INDEX ix_background_tasks_kind ON background_tasks (kind);
CREATE INDEX ix_chat_messages_conversation_id ON chat_messages (conversation_id);
CREATE INDEX ix_creator_account_snapshots_account_id ON creator_account_snapshots (account_id);
CREATE INDEX ix_creator_account_snapshots_snapshot_date ON creator_account_snapshots (snapshot_date);
CREATE INDEX ix_creator_accounts_creator_id ON creator_accounts (creator_id);
CREATE INDEX ix_creator_accounts_platform ON creator_accounts (platform);
CREATE INDEX ix_creators_is_current ON creators (is_current);
CREATE INDEX ix_creators_parent_id ON creators (parent_id);
CREATE INDEX ix_draft_discussions_draft_id ON draft_discussions (draft_id);
CREATE INDEX ix_drafts_creator_id ON drafts (creator_id);
CREATE INDEX ix_drafts_video_id ON drafts (video_id);
CREATE INDEX ix_feedback_draft_id ON feedback (draft_id);
CREATE INDEX ix_hot_topics_platform ON hot_topics (platform);
CREATE INDEX ix_hot_topics_topic_date ON hot_topics (topic_date);
CREATE INDEX ix_metrics_snapshots_snapshot_date ON metrics_snapshots (snapshot_date);
CREATE INDEX ix_metrics_snapshots_video_id ON metrics_snapshots (video_id);
CREATE INDEX ix_notifications_created_at ON notifications (created_at);
CREATE INDEX ix_notifications_kind ON notifications (kind);
CREATE INDEX ix_notifications_read ON notifications (read);
CREATE INDEX ix_persona_checks_creator_id ON persona_checks (creator_id);
CREATE INDEX ix_persona_tags_creator_id ON persona_tags (creator_id);
CREATE INDEX ix_persona_tags_label ON persona_tags (label);
CREATE UNIQUE INDEX ix_pipeline_runs_run_date ON pipeline_runs (run_date);
CREATE INDEX ix_platform_post_comments_post_id ON platform_post_comments (post_id);
CREATE INDEX ix_platform_post_stats_post_id ON platform_post_stats (post_id);
CREATE INDEX ix_platform_post_stats_stat_date ON platform_post_stats (stat_date);
CREATE INDEX ix_platform_posts_account_id ON platform_posts (account_id);
CREATE INDEX ix_platform_posts_local_video_id ON platform_posts (local_video_id);
CREATE INDEX ix_platform_posts_platform ON platform_posts (platform);
CREATE INDEX ix_platform_posts_platform_post_id ON platform_posts (platform_post_id);
CREATE INDEX ix_platform_posts_publish_time ON platform_posts (publish_time);
CREATE INDEX ix_platform_posts_work_id ON platform_posts (work_id);
CREATE INDEX ix_prompt_evals_key ON prompt_evals ("key");
CREATE INDEX ix_sync_jobs_job_type ON sync_jobs (job_type);
CREATE INDEX ix_topic_candidates_run_date ON topic_candidates (run_date);
CREATE INDEX ix_topic_ideas_creator_id ON topic_ideas (creator_id);
CREATE INDEX ix_topic_ideas_platform ON topic_ideas (platform);
CREATE INDEX ix_topic_ideas_snapshot_date ON topic_ideas (snapshot_date);
CREATE INDEX ix_topic_ideas_used ON topic_ideas (used);
CREATE INDEX ix_transcripts_video_id ON transcripts (video_id);
CREATE INDEX ix_videos_creator_id ON videos (creator_id);
CREATE UNIQUE INDEX ix_videos_filename ON videos (filename);
CREATE INDEX ix_videos_platform_post_id ON videos (platform_post_id);
CREATE INDEX ix_videos_work_id ON videos (work_id);
CREATE INDEX ix_works_creator_id ON works (creator_id);
CREATE UNIQUE INDEX ux_platform_posts_local_platform ON platform_posts(local_video_id, platform) WHERE local_video_id IS NOT NULL;
