-- #62 本地测试库结构：workflows / events（分区）/ 3 张引用表的列、约束、触发器逐字取自生产（索引取与本清理相关的子集）
-- （2026-10-01 只读 pg_dump --schema-only 与 pg_get_functiondef）。依赖表只保留触发器与外键用到的列。
-- 真实函数：assert_community_write_allowed / enforce_community_write_fence / community_deletion_lock_key /
--           purge_soft_deleted_* / events_created_at_floor_guard。
-- 只在 INSERT/DELETE 时触发的 5 个 events 触发器函数为桩（本清理只 UPDATE events；还原也只 UPDATE），触发器本身照建。
SET client_min_messages = warning;
CREATE TYPE workflow_status AS ENUM ('active', 'disabled', 'archived');
CREATE TYPE run_status AS ENUM ('pending', 'running', 'waiting_approval', 'completed', 'failed', 'cancelled');
CREATE TYPE approval_status AS ENUM ('pending', 'granted', 'denied', 'expired');

CREATE TABLE communities (id uuid PRIMARY KEY, deletion_state text NOT NULL DEFAULT 'active', deletion_fence_generation bigint NOT NULL DEFAULT 0);
CREATE TABLE community_serving_write_leases (id uuid PRIMARY KEY, community_id uuid, owner text, generation bigint, fence_generation bigint, lease_until timestamptz);
CREATE TABLE users (community_id uuid NOT NULL REFERENCES communities(id), pubkey bytea NOT NULL, display_name text, PRIMARY KEY (community_id, pubkey));
CREATE TABLE channels (community_id uuid NOT NULL REFERENCES communities(id), id uuid NOT NULL, name text, PRIMARY KEY (community_id, id));
CREATE TABLE event_mentions (community_id uuid NOT NULL, event_id bytea NOT NULL);

CREATE FUNCTION community_deletion_lock_key(target uuid) RETURNS bigint LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT AS $f$
    SELECT hashtextextended('buzz-community-deletion:' || target::text, 0)
$f$;

CREATE FUNCTION assert_community_write_allowed(target uuid) RETURNS void LANGUAGE plpgsql AS $function$
DECLARE
    lifecycle TEXT; generation BIGINT; executor_community TEXT; executor_generation TEXT;
    serving_community TEXT; serving_lease_id TEXT; serving_owner TEXT; serving_generation TEXT;
    serving_fence_generation TEXT; serving_lease_valid BOOLEAN := false;
BEGIN
    IF current_setting('transaction_isolation') <> 'read committed' THEN
        RAISE EXCEPTION 'community writes require READ COMMITTED isolation' USING ERRCODE = 'invalid_transaction_state';
    END IF;
    IF target IS NULL THEN RETURN; END IF;
    PERFORM pg_advisory_xact_lock_shared(community_deletion_lock_key(target));
    SELECT deletion_state, deletion_fence_generation INTO lifecycle, generation FROM communities WHERE id = target;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'community write rejected: community % is missing', target USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
    executor_community := current_setting('buzz.deletion_executor_community', true);
    executor_generation := current_setting('buzz.deletion_fence_generation', true);
    IF executor_community = target::TEXT AND executor_generation ~ '^[0-9]+$' AND executor_generation::BIGINT = generation THEN
        RETURN;
    END IF;
    serving_community := current_setting('buzz.serving_write_community', true);
    serving_lease_id := current_setting('buzz.serving_write_lease_id', true);
    serving_owner := current_setting('buzz.serving_write_owner', true);
    serving_generation := current_setting('buzz.serving_write_generation', true);
    serving_fence_generation := current_setting('buzz.serving_write_fence_generation', true);
    IF lifecycle IN ('active', 'quiescing') AND serving_community = target::TEXT AND serving_lease_id ~ '^[0-9a-fA-F-]{36}$'
       AND serving_generation ~ '^[0-9]+$' AND serving_fence_generation ~ '^[0-9]+$'
       AND serving_fence_generation::BIGINT = generation THEN
        SELECT EXISTS(SELECT 1 FROM community_serving_write_leases lease
                       WHERE lease.id = serving_lease_id::UUID AND lease.community_id = target AND lease.owner = serving_owner
                         AND lease.generation = serving_generation::BIGINT AND lease.fence_generation = serving_fence_generation::BIGINT
                         AND lease.lease_until >= now()) INTO serving_lease_valid;
        IF serving_lease_valid THEN RETURN; END IF;
    END IF;
    IF lifecycle <> 'active' THEN
        RAISE EXCEPTION 'community write fenced: community % generation %', target, generation USING ERRCODE = 'object_not_in_prerequisite_state';
    END IF;
END
$function$;

CREATE FUNCTION enforce_community_write_fence() RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF TG_OP = 'INSERT' THEN PERFORM assert_community_write_allowed(NEW.community_id);
    ELSIF TG_OP = 'DELETE' THEN PERFORM assert_community_write_allowed(OLD.community_id);
    ELSIF OLD.community_id IS NOT DISTINCT FROM NEW.community_id THEN PERFORM assert_community_write_allowed(OLD.community_id);
    ELSIF OLD.community_id IS NULL THEN PERFORM assert_community_write_allowed(NEW.community_id);
    ELSIF NEW.community_id IS NULL THEN PERFORM assert_community_write_allowed(OLD.community_id);
    ELSIF OLD.community_id < NEW.community_id THEN
        PERFORM assert_community_write_allowed(OLD.community_id); PERFORM assert_community_write_allowed(NEW.community_id);
    ELSE
        PERFORM assert_community_write_allowed(NEW.community_id); PERFORM assert_community_write_allowed(OLD.community_id);
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END
$function$;

CREATE FUNCTION purge_soft_deleted_buzz_mesh_status() RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL AND NEW.kind = 30003
       AND NEW.d_tag LIKE 'buzz-mesh-member-status:%' AND NEW.tags @> '[["k", "buzz-mesh-status"]]'::jsonb THEN
        DELETE FROM events WHERE community_id = NEW.community_id AND created_at = NEW.created_at AND id = NEW.id;
        DELETE FROM event_mentions WHERE community_id = NEW.community_id AND event_id = NEW.id;
    END IF;
    RETURN NULL;
END;
$function$;

CREATE FUNCTION purge_soft_deleted_nip_rs() RETURNS trigger LANGUAGE plpgsql AS $function$
BEGIN
    IF OLD.deleted_at IS NULL AND NEW.deleted_at IS NOT NULL AND NEW.kind = 30078 AND NEW.d_tag ~ '^read-state:[0-9a-f]{32}$' THEN
        -- 生产版本另有 tags 基数检查；kind 30620 在第一层条件即被排除，与本清理无关。
        PERFORM set_config('buzz.nip_rs_hard_delete', 'on', true);
        DELETE FROM events WHERE community_id = NEW.community_id AND created_at = NEW.created_at AND id = NEW.id;
        DELETE FROM event_mentions WHERE community_id = NEW.community_id AND event_id = NEW.id;
    END IF;
    RETURN NULL;
END;
$function$;

CREATE FUNCTION events_created_at_floor_guard() RETURNS trigger LANGUAGE plpgsql AS $function$
DECLARE
    floor_secs numeric := nullif(current_setting('buzz.created_at_floor', true), '')::numeric;
BEGIN
    IF floor_secs IS NOT NULL AND floor_secs > 0 AND NEW.channel_id IS NOT NULL
       AND NEW.created_at < clock_timestamp() - make_interval(secs => floor_secs) THEN
        RAISE EXCEPTION 'events.created_at % is more than % s before commit time %; below the replica-fence floor',
            NEW.created_at, floor_secs, clock_timestamp() USING ERRCODE = 'check_violation';
    END IF;
    RETURN NULL;
END
$function$;

-- 桩（INSERT/DELETE 专用触发器）
CREATE FUNCTION enqueue_push_match_job() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RETURN NULL; END $f$;
CREATE FUNCTION refresh_channel_ttl_after_event_insert() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RETURN NULL; END $f$;
CREATE FUNCTION guard_channel_roster_snapshot() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RETURN NEW; END $f$;
CREATE FUNCTION guard_nip_rs_watermark() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RETURN NEW; END $f$;
CREATE FUNCTION guard_nip_rs_hard_delete() RETURNS trigger LANGUAGE plpgsql AS $f$ BEGIN RETURN OLD; END $f$;

-- ===== 以下取自生产 pg_dump --schema-only（去掉 public. 前缀）。events 的主键与索引去掉 ONLY：
-- 生产各分区都已挂上 events_p*_pkey（只读核对 pg_index），单表 dump 只含父表 ONLY 定义。=====
CREATE TABLE events (
    community_id uuid NOT NULL, id bytea NOT NULL, pubkey bytea NOT NULL, created_at timestamp with time zone NOT NULL,
    kind integer NOT NULL, tags jsonb NOT NULL, content text NOT NULL, sig bytea NOT NULL,
    received_at timestamp with time zone DEFAULT now() NOT NULL, channel_id uuid, deleted_at timestamp with time zone,
    d_tag text, not_before bigint, delivered_at bigint,
    search_tsv tsvector GENERATED ALWAYS AS (
      CASE WHEN (kind = 30179) THEN NULL::tsvector ELSE
        CASE WHEN (kind = 30350) THEN NULL::tsvector ELSE
          CASE WHEN (kind = ANY (ARRAY[0, 9, 40002, 45001, 45003])) THEN to_tsvector('simple'::regconfig, content) ELSE NULL::tsvector END
        END
      END) STORED
) PARTITION BY RANGE (created_at);
CREATE TABLE events_p_past   PARTITION OF events FOR VALUES FROM (MINVALUE) TO ('2026-01-01 00:00:00+00');
CREATE TABLE events_p2026_01 PARTITION OF events FOR VALUES FROM ('2026-01-01 00:00:00+00') TO ('2026-02-01 00:00:00+00');
CREATE TABLE events_p2026_02 PARTITION OF events FOR VALUES FROM ('2026-02-01 00:00:00+00') TO ('2026-03-01 00:00:00+00');
CREATE TABLE events_p2026_03 PARTITION OF events FOR VALUES FROM ('2026-03-01 00:00:00+00') TO ('2026-04-01 00:00:00+00');
CREATE TABLE events_p2026_04 PARTITION OF events FOR VALUES FROM ('2026-04-01 00:00:00+00') TO ('2026-05-01 00:00:00+00');
CREATE TABLE events_p2026_05 PARTITION OF events FOR VALUES FROM ('2026-05-01 00:00:00+00') TO ('2026-06-01 00:00:00+00');
CREATE TABLE events_p2026_06 PARTITION OF events FOR VALUES FROM ('2026-06-01 00:00:00+00') TO ('2026-07-01 00:00:00+00');
CREATE TABLE events_p_future PARTITION OF events FOR VALUES FROM ('2026-07-01 00:00:00+00') TO (MAXVALUE);

CREATE TABLE workflows (
    community_id uuid NOT NULL, id uuid DEFAULT gen_random_uuid() NOT NULL, name character varying(255) NOT NULL,
    owner_pubkey bytea NOT NULL, channel_id uuid, definition jsonb NOT NULL, definition_hash bytea NOT NULL,
    status workflow_status DEFAULT 'active'::workflow_status NOT NULL, enabled boolean DEFAULT true NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL, updated_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE workflow_runs (
    community_id uuid NOT NULL, id uuid DEFAULT gen_random_uuid() NOT NULL, workflow_id uuid NOT NULL,
    status run_status DEFAULT 'pending'::run_status NOT NULL, trigger_event_id bytea, current_step integer DEFAULT 0 NOT NULL,
    execution_trace jsonb DEFAULT '[]'::jsonb NOT NULL, trigger_context jsonb, started_at timestamp with time zone,
    completed_at timestamp with time zone, error_message text, created_at timestamp with time zone DEFAULT now() NOT NULL, error_code text
);
CREATE TABLE workflow_approvals (
    community_id uuid NOT NULL, token bytea NOT NULL, workflow_id uuid NOT NULL, run_id uuid NOT NULL,
    step_id character varying(64) NOT NULL, step_index integer NOT NULL, approver_spec text NOT NULL,
    status approval_status DEFAULT 'pending'::approval_status NOT NULL, approver_pubkey bytea, note text,
    granted_at timestamp with time zone, denied_at timestamp with time zone, expires_at timestamp with time zone NOT NULL,
    created_at timestamp with time zone DEFAULT now() NOT NULL
);
CREATE TABLE scheduled_workflow_fires (
    community_id uuid NOT NULL, workflow_id uuid NOT NULL, scheduled_for timestamp with time zone NOT NULL,
    claimed_at timestamp with time zone DEFAULT now() NOT NULL, workflow_run_id uuid
);
ALTER TABLE events ADD CONSTRAINT events_pkey PRIMARY KEY (community_id, created_at, id);
ALTER TABLE ONLY scheduled_workflow_fires ADD CONSTRAINT scheduled_workflow_fires_pkey PRIMARY KEY (community_id, workflow_id, scheduled_for);
ALTER TABLE ONLY workflow_approvals ADD CONSTRAINT workflow_approvals_pkey PRIMARY KEY (community_id, token);
ALTER TABLE ONLY workflow_runs ADD CONSTRAINT workflow_runs_pkey PRIMARY KEY (community_id, id);
ALTER TABLE ONLY workflows ADD CONSTRAINT workflows_pkey PRIMARY KEY (community_id, id);
CREATE INDEX idx_events_addressable ON events USING btree (community_id, kind, pubkey, channel_id, deleted_at);
CREATE INDEX idx_events_community_deleted ON events USING btree (community_id, deleted_at);
CREATE INDEX idx_events_parameterized ON events USING btree (community_id, kind, pubkey, d_tag, created_at DESC, id) WHERE ((d_tag IS NOT NULL) AND (deleted_at IS NULL));
CREATE INDEX idx_events_search_tsv ON events USING gin (search_tsv);
CREATE INDEX idx_events_tags_gin ON events USING gin (tags jsonb_path_ops);
CREATE INDEX idx_workflows_channel_active ON workflows USING btree (community_id, channel_id, status, enabled);
CREATE INDEX idx_workflows_enabled ON workflows USING btree (enabled, status) WHERE enabled;
CREATE TRIGGER community_write_fence_events BEFORE INSERT OR DELETE OR UPDATE ON events FOR EACH ROW EXECUTE FUNCTION enforce_community_write_fence();
CREATE TRIGGER community_write_fence_scheduled_workflow_fires BEFORE INSERT OR DELETE OR UPDATE ON scheduled_workflow_fires FOR EACH ROW EXECUTE FUNCTION enforce_community_write_fence();
CREATE TRIGGER community_write_fence_workflow_approvals BEFORE INSERT OR DELETE OR UPDATE ON workflow_approvals FOR EACH ROW EXECUTE FUNCTION enforce_community_write_fence();
CREATE TRIGGER community_write_fence_workflow_runs BEFORE INSERT OR DELETE OR UPDATE ON workflow_runs FOR EACH ROW EXECUTE FUNCTION enforce_community_write_fence();
CREATE TRIGGER community_write_fence_workflows BEFORE INSERT OR DELETE OR UPDATE ON workflows FOR EACH ROW EXECUTE FUNCTION enforce_community_write_fence();
CREATE CONSTRAINT TRIGGER events_created_at_floor AFTER INSERT OR UPDATE OF created_at, channel_id ON events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION events_created_at_floor_guard();
CREATE TRIGGER events_enqueue_push_match AFTER INSERT ON events FOR EACH ROW EXECUTE FUNCTION enqueue_push_match_job();
CREATE CONSTRAINT TRIGGER events_refresh_channel_ttl AFTER INSERT ON events DEFERRABLE INITIALLY DEFERRED FOR EACH ROW EXECUTE FUNCTION refresh_channel_ttl_after_event_insert();
CREATE TRIGGER trg_events_guard_channel_roster_snapshot BEFORE INSERT ON events FOR EACH ROW EXECUTE FUNCTION guard_channel_roster_snapshot();
CREATE TRIGGER trg_events_guard_nip_rs_hard_delete BEFORE DELETE ON events FOR EACH ROW WHEN (((old.kind = 30078) AND (old.d_tag ~ '^read-state:[0-9a-f]{32}$'::text))) EXECUTE FUNCTION guard_nip_rs_hard_delete();
CREATE TRIGGER trg_events_nip_rs_watermark BEFORE INSERT ON events FOR EACH ROW EXECUTE FUNCTION guard_nip_rs_watermark();
CREATE TRIGGER trg_events_purge_soft_deleted_buzz_mesh_status AFTER UPDATE OF deleted_at ON events FOR EACH ROW EXECUTE FUNCTION purge_soft_deleted_buzz_mesh_status();
CREATE TRIGGER trg_events_purge_soft_deleted_nip_rs AFTER UPDATE OF deleted_at ON events FOR EACH ROW EXECUTE FUNCTION purge_soft_deleted_nip_rs();
ALTER TABLE events ADD CONSTRAINT events_community_id_fkey FOREIGN KEY (community_id) REFERENCES communities(id);
ALTER TABLE ONLY scheduled_workflow_fires ADD CONSTRAINT scheduled_workflow_fires_community_id_workflow_id_fkey FOREIGN KEY (community_id, workflow_id) REFERENCES workflows(community_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY scheduled_workflow_fires ADD CONSTRAINT scheduled_workflow_fires_community_id_workflow_run_id_fkey FOREIGN KEY (community_id, workflow_run_id) REFERENCES workflow_runs(community_id, id);
ALTER TABLE ONLY workflow_approvals ADD CONSTRAINT workflow_approvals_community_id_run_id_fkey FOREIGN KEY (community_id, run_id) REFERENCES workflow_runs(community_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY workflow_approvals ADD CONSTRAINT workflow_approvals_community_id_workflow_id_fkey FOREIGN KEY (community_id, workflow_id) REFERENCES workflows(community_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY workflow_runs ADD CONSTRAINT workflow_runs_community_id_workflow_id_fkey FOREIGN KEY (community_id, workflow_id) REFERENCES workflows(community_id, id) ON DELETE CASCADE;
ALTER TABLE ONLY workflows ADD CONSTRAINT workflows_community_id_channel_id_fkey FOREIGN KEY (community_id, channel_id) REFERENCES channels(community_id, id);
ALTER TABLE ONLY workflows ADD CONSTRAINT workflows_community_id_fkey FOREIGN KEY (community_id) REFERENCES communities(id);
ALTER TABLE ONLY workflows ADD CONSTRAINT workflows_community_id_owner_pubkey_fkey FOREIGN KEY (community_id, owner_pubkey) REFERENCES users(community_id, pubkey);
