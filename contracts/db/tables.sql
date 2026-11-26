-- Franca database schema: source file.
--
-- This file is the hand-written part of the schema. When build_schema.py is run,
-- the column macros below are expanded, the generated views and triggers are added,
-- and the result is written to schema.sql. schema.sql is the file used by the app and Alembic.
--
-- Column macros (written at the end of a column line, before the comma):
--   @TS     UTC timestamp, ISO 8601 with milliseconds and Z: 2026-11-11T08:30:00.000Z
--   @DAY    calendar day: 2026-11-11
--   @TIME   local clock time: 07:30
--   @BOOL   0 or 1
--   @SHA    SHA-256 as 64 lower-case hex characters
--   @LEVEL  a level of the course ladder
--   @UUID   a UUID in its 36-character text form, made on the device
--
-- Naming:
--   * Table names start with the name of their module.
--   * The rows in tables ending in _v are pack content for one pack version.
--   * Primary keys are <table>_id, except in association tables.
--   * Times are UTC. A learner's local day is worked out from their time zone
--     and day_starts_hour. It is stored as @DAY where a rule depends on it.
--
-- Every table is STRICT, so column types are checked by SQLite.

-- =====================================================================
-- identity: learners, sign-in, preferences, reminders, audit log
--
-- Any number of learners can have an account (decision of 21 November 2026).
-- Learners sign in with Google (OpenID Connect). A passkey can be added as a
-- second way in. New learners join by an invitation from the owner.
-- =====================================================================

CREATE TABLE identity_learner (
    learner_id        INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    display_name      TEXT    NOT NULL CHECK (length(display_name) BETWEEN 1 AND 60),
    role              TEXT    NOT NULL DEFAULT 'learner' CHECK (role IN ('owner', 'learner')),
    status            TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'disabled')),
    -- English is the support language (decision of 10 November 2026).
    -- Content has _en columns only; another value needs a translation table first.
    support_language  TEXT    NOT NULL DEFAULT 'en' CHECK (support_language = 'en'),
    timezone          TEXT    NOT NULL DEFAULT 'Europe/Brussels' CHECK (length(timezone) BETWEEN 3 AND 64),
    day_starts_hour   INTEGER NOT NULL DEFAULT 4 CHECK (day_starts_hour BETWEEN 0 AND 23),
    created_at        TEXT    NOT NULL @TS,
    CHECK (role <> 'owner' OR status = 'active')   -- the owner cannot be locked out
) STRICT;
-- The owner is the one learner who can install packs and work through Te controleren.
CREATE UNIQUE INDEX identity_learner_one_owner ON identity_learner (role) WHERE role = 'owner';

-- Sign-in through an outside identity provider. subject is the provider's stable id for
-- the person (the OpenID Connect sub claim); the e-mail address can change and is not a key.
CREATE TABLE identity_external_identity (
    external_identity_id INTEGER PRIMARY KEY,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    provider          TEXT    NOT NULL CHECK (provider IN ('google')),
    subject           TEXT    NOT NULL CHECK (length(subject) BETWEEN 1 AND 255),
    email             TEXT    NOT NULL CHECK (email LIKE '%_@_%' AND length(email) <= 320),
    email_verified    INTEGER NOT NULL @BOOL,
    created_at        TEXT    NOT NULL @TS,
    last_used_at      TEXT    @TS,
    UNIQUE (provider, subject),
    UNIQUE (learner_id, provider),
    CHECK (email_verified = 1)
) STRICT;

-- The owner invites a person by e-mail address. The first Google sign-in with that verified
-- address within the time limit creates the learner. The app stores addresses after Unicode NFC
-- and casefold; the CHECK below covers ASCII letters only. An invitation always makes a learner:
-- the owner role is not handed over by invitation. Before a new invitation to the same address,
-- the app revokes an expired one, since the index below treats it as still open. An accepted
-- invitation is purged 30 days after acceptance (retention_expired).
CREATE TABLE identity_invitation (
    invitation_id     INTEGER PRIMARY KEY,
    email_norm        TEXT    NOT NULL CHECK (email_norm LIKE '%_@_%' AND email_norm = lower(email_norm) AND length(email_norm) <= 320),
    role              TEXT    NOT NULL DEFAULT 'learner' CHECK (role = 'learner'),
    invited_by_learner_id INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    created_at        TEXT    NOT NULL @TS,
    expires_at        TEXT    NOT NULL @TS,
    accepted_at       TEXT    @TS,
    accepted_learner_id INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    revoked_at        TEXT    @TS,
    CHECK (expires_at > created_at),
    CHECK (julianday(expires_at) - julianday(created_at) <= 14.0001),
    CHECK (accepted_learner_id IS NULL OR accepted_at IS NOT NULL),
    CHECK (accepted_at IS NULL OR revoked_at IS NULL),
    CHECK (accepted_at IS NULL OR (accepted_at >= created_at AND accepted_at <= expires_at)),
    CHECK (revoked_at IS NULL OR revoked_at >= created_at)
) STRICT;
CREATE INDEX identity_invitation_email ON identity_invitation (email_norm);
CREATE INDEX identity_invitation_invited_by ON identity_invitation (invited_by_learner_id);
CREATE INDEX identity_invitation_accepted ON identity_invitation (accepted_learner_id);
-- One open invitation per address.
CREATE UNIQUE INDEX identity_invitation_one_open ON identity_invitation (email_norm) WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE TABLE identity_passkey (
    credential_id     BLOB    PRIMARY KEY CHECK (length(credential_id) BETWEEN 16 AND 1023),
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    public_key        BLOB    NOT NULL,
    sign_count        INTEGER NOT NULL DEFAULT 0 CHECK (sign_count >= 0),
    transports        TEXT,
    aaguid            BLOB    CHECK (aaguid IS NULL OR length(aaguid) = 16),
    backup_eligible   INTEGER NOT NULL DEFAULT 0 @BOOL,
    backed_up         INTEGER NOT NULL DEFAULT 0 @BOOL,
    label             TEXT    CHECK (label IS NULL OR length(label) <= 60),
    created_at        TEXT    NOT NULL @TS,
    last_used_at      TEXT    @TS
) STRICT;
CREATE INDEX identity_passkey_learner ON identity_passkey (learner_id);

-- Recovery codes are stored as Argon2id hashes, not as plain text.
CREATE TABLE identity_recovery_code (
    recovery_code_id  INTEGER PRIMARY KEY,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    code_hash         TEXT    NOT NULL UNIQUE CHECK (code_hash LIKE '$argon2id$%'),
    created_at        TEXT    NOT NULL @TS,
    used_at           TEXT    @TS
) STRICT;
CREATE INDEX identity_recovery_code_learner ON identity_recovery_code (learner_id);

-- A sign-in session expires 30 days after it was last used (decision of 11 November 2026):
-- expires_at is moved forward when the session is used.
-- There is a 256-bit random token in the session cookie. The token is not stored; its SHA-256 hash is.
CREATE TABLE identity_auth_session (
    auth_session_id   INTEGER PRIMARY KEY,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    token_hash        BLOB    NOT NULL UNIQUE CHECK (length(token_hash) = 32),
    device_kind       TEXT    NOT NULL CHECK (device_kind IN ('desktop', 'tablet', 'phone')),
    user_agent        TEXT    CHECK (user_agent IS NULL OR length(user_agent) <= 200),
    created_at        TEXT    NOT NULL @TS,
    last_seen_at      TEXT    NOT NULL @TS,
    expires_at        TEXT    NOT NULL @TS,
    revoked_at        TEXT    @TS,
    -- The passkey the learner signed in with, if any. Its sessions are ended when the passkey is removed.
    passkey_credential_id BLOB REFERENCES identity_passkey ON DELETE SET NULL,
    CHECK (expires_at > created_at),
    CHECK (last_seen_at >= created_at),
    CHECK (julianday(expires_at) - julianday(last_seen_at) <= 30.0001)
) STRICT;
CREATE INDEX identity_auth_session_learner ON identity_auth_session (learner_id);
CREATE INDEX identity_auth_session_expires ON identity_auth_session (expires_at);
CREATE INDEX identity_auth_session_passkey ON identity_auth_session (passkey_credential_id);

-- One row per learner. Settings that belong to one course are on study_enrolment.
CREATE TABLE identity_preferences (
    learner_id        INTEGER PRIMARY KEY REFERENCES identity_learner ON DELETE CASCADE,
    english_layer     INTEGER NOT NULL DEFAULT 1 @BOOL,
    line_controls     TEXT    NOT NULL DEFAULT 'on_focus' CHECK (line_controls IN ('on_focus', 'every_line')),
    font              TEXT    NOT NULL DEFAULT 'atkinson_hyperlegible' CHECK (font IN ('atkinson_hyperlegible', 'system', 'dyslexia')),
    text_scale        REAL    NOT NULL DEFAULT 1.0 CHECK (text_scale BETWEEN 0.8 AND 2.0),
    line_spacing      REAL    NOT NULL DEFAULT 1.5 CHECK (line_spacing BETWEEN 1.2 AND 2.5),
    theme             TEXT    NOT NULL DEFAULT 'system' CHECK (theme IN ('system', 'light', 'dark', 'high_contrast')),
    reduced_motion    TEXT    NOT NULL DEFAULT 'system' CHECK (reduced_motion IN ('system', 'on', 'off')),
    handwriting       INTEGER NOT NULL DEFAULT 1 @BOOL,
    typo_tolerance    TEXT    NOT NULL DEFAULT 'accents_strict' CHECK (typo_tolerance IN ('strict', 'accents_strict', 'lenient')),
    library_captions  TEXT    NOT NULL DEFAULT 'target' CHECK (library_captions IN ('target', 'english', 'both', 'none')),
    session_mode      TEXT    NOT NULL DEFAULT 'standard' CHECK (session_mode IN ('short', 'standard', 'extended')),
    break_minutes     INTEGER NOT NULL DEFAULT 45 CHECK (break_minutes BETWEEN 15 AND 120),
    updated_at        TEXT    NOT NULL @TS
) STRICT;

-- Optional daily reminder: one row per weekday the learner chose (1 = Monday).
CREATE TABLE identity_reminder (
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    weekday           INTEGER NOT NULL CHECK (weekday BETWEEN 1 AND 7),
    local_time        TEXT    NOT NULL @TIME,
    last_sent_on      TEXT    @DAY,
    PRIMARY KEY (learner_id, weekday)
) STRICT, WITHOUT ROWID;

CREATE TABLE identity_push_subscription (
    push_subscription_id INTEGER PRIMARY KEY,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    endpoint          TEXT    NOT NULL UNIQUE CHECK (endpoint LIKE 'https://%'),
    p256dh            BLOB    NOT NULL,
    auth_secret       BLOB    NOT NULL,
    created_at        TEXT    NOT NULL @TS,
    last_success_at   TEXT    @TS,
    failure_count     INTEGER NOT NULL DEFAULT 0 CHECK (failure_count >= 0)
) STRICT;
CREATE INDEX identity_push_subscription_learner ON identity_push_subscription (learner_id);

-- Security events (OWASP ASVS V7). There are no secrets or answer text in the detail column. Kept for one year.
CREATE TABLE identity_audit_event (
    audit_event_id    INTEGER PRIMARY KEY,
    learner_id        INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    event             TEXT    NOT NULL CHECK (event IN (
                          'sign_in', 'sign_in_failed', 'sign_out', 'passkey_added', 'passkey_removed',
                          'recovery_code_used', 'recovery_codes_replaced', 'share_changed',
                          'data_exported', 'learner_deleted', 'pack_installed', 'pack_rolled_back',
                          'handover_claimed', 'invitation_created', 'invitation_revoked', 'invitation_accepted',
                          'learner_disabled', 'learner_enabled', 'ai_limit_changed', 'ai_limit_reached')),
    detail            TEXT    CHECK (detail IS NULL OR (json_valid(detail) AND length(detail) <= 2000)),
    at                TEXT    NOT NULL @TS
) STRICT;
CREATE INDEX identity_audit_event_learner ON identity_audit_event (learner_id);
CREATE INDEX identity_audit_event_at ON identity_audit_event (at);

-- =====================================================================
-- catalogue: reference tables filled by a migration (app level)
-- =====================================================================

CREATE TABLE catalogue_licence (
    licence_code      TEXT    PRIMARY KEY CHECK (length(licence_code) BETWEEN 2 AND 40),
    name              TEXT    NOT NULL,
    url               TEXT,
    shareable         INTEGER NOT NULL @BOOL
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_activity_type (
    activity_type     TEXT    PRIMARY KEY CHECK (activity_type GLOB '[a-z]*' AND activity_type NOT GLOB '*[^a-z0-9_]*'),
    name_en           TEXT    NOT NULL,
    strand            TEXT    NOT NULL CHECK (strand IN ('input', 'output', 'language_focus', 'fluency', 'feedback')),
    response          TEXT    NOT NULL CHECK (response IN ('none', 'recognition', 'production')),
    needs_microphone  INTEGER NOT NULL DEFAULT 0 @BOOL,
    needs_handwriting INTEGER NOT NULL DEFAULT 0 @BOOL,
    auto_graded       INTEGER NOT NULL DEFAULT 0 @BOOL,
    game              INTEGER NOT NULL DEFAULT 0 @BOOL   -- one of the games in the course design section Games and puzzles
) STRICT, WITHOUT ROWID;

-- Interface element keys. The name that is shown is taken from the pack (catalogue_element_name_v).
-- name_en is used where the pack has no name, and for the English layer.
CREATE TABLE catalogue_ui_element (
    element_key       TEXT    PRIMARY KEY CHECK (element_key GLOB '[a-z]*' AND element_key NOT GLOB '*[^a-z0-9_]*'),
    name_en           TEXT    NOT NULL,
    description       TEXT    NOT NULL
) STRICT, WITHOUT ROWID;

-- What kind of thing an item is, which says which content table describes it.
-- A pack's own item types (the middle part of an item key) are mapped onto these.
CREATE TABLE catalogue_item_kind (
    kind              TEXT    PRIMARY KEY CHECK (kind NOT GLOB '*[^a-z_]*'),
    description       TEXT    NOT NULL
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_error_type (
    error_type        TEXT    PRIMARY KEY CHECK (error_type NOT GLOB '*[^a-z_]*'),
    name_en           TEXT    NOT NULL
) STRICT, WITHOUT ROWID;

-- =====================================================================
-- catalogue: stable tables (kept across pack versions)
-- =====================================================================

CREATE TABLE catalogue_pack (
    pack_id           INTEGER PRIMARY KEY,
    language          TEXT    NOT NULL UNIQUE CHECK (language GLOB '[a-z][a-z]' OR language GLOB '[a-z][a-z][a-z]'),
    name_en           TEXT    NOT NULL,
    script            TEXT    NOT NULL CHECK (script GLOB '[A-Z][a-z][a-z][a-z]'),
    direction         TEXT    NOT NULL CHECK (direction IN ('ltr', 'rtl')),
    created_at        TEXT    NOT NULL @TS
) STRICT;

CREATE TABLE catalogue_variety (
    variety_id        INTEGER PRIMARY KEY,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    code              TEXT    NOT NULL CHECK (length(code) BETWEEN 2 AND 20),
    name_en           TEXT    NOT NULL,
    productive        INTEGER NOT NULL @BOOL,
    receptive_from    TEXT    @LEVEL,
    UNIQUE (pack_id, code),
    UNIQUE (pack_id, variety_id)
) STRICT;

CREATE TABLE catalogue_pack_version (
    pack_version_id   INTEGER PRIMARY KEY,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    version           TEXT    NOT NULL CHECK (version GLOB '[0-9]*.[0-9]*.[0-9]*' AND version NOT GLOB '*[^0-9.]*'
                                                  AND length(version) - length(replace(version, '.', '')) = 2),
    content_sha256    TEXT    NOT NULL @SHA,
    signature         BLOB    NOT NULL,
    distribution      TEXT    NOT NULL CHECK (distribution IN ('private', 'shareable')),
    status            TEXT    NOT NULL DEFAULT 'importing' CHECK (status IN ('importing', 'active', 'retired', 'failed')),
    built_at          TEXT    NOT NULL @TS,
    imported_at       TEXT    NOT NULL @TS,
    activated_at      TEXT    @TS,
    retired_at        TEXT    @TS,
    UNIQUE (pack_id, version),
    CHECK ((status = 'importing') OR (status = 'failed') OR activated_at IS NOT NULL),
    CHECK ((status = 'retired') = (retired_at IS NOT NULL))
) STRICT;
CREATE UNIQUE INDEX catalogue_pack_version_one_active ON catalogue_pack_version (pack_id) WHERE status = 'active';

-- One row per item key. Rows are added on import and are not deleted, because learner
-- data is linked to item_id. Whether an item is in the active version is worked out from
-- the content tables (view catalogue_item_live), so a rollback needs no change here.
CREATE TABLE catalogue_item (
    item_id           INTEGER PRIMARY KEY,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    item_key          TEXT    NOT NULL CHECK (length(item_key) BETWEEN 5 AND 200 AND item_key NOT GLOB '*[^a-z0-9:#_-]*'),
    kind              TEXT    NOT NULL REFERENCES catalogue_item_kind,
    UNIQUE (pack_id, item_key)
) STRICT;
CREATE INDEX catalogue_item_pack_kind ON catalogue_item (pack_id, kind);
CREATE INDEX catalogue_item_kind_fk ON catalogue_item (kind);

-- Media files are stored on disk by hash (media/ab/cd/<sha256>), not in the database.
-- One asset row can be used by several pack versions and by the library.
CREATE TABLE catalogue_media_asset (
    sha256            TEXT    PRIMARY KEY @SHA,
    mime              TEXT    NOT NULL CHECK (mime IN (
                          'audio/ogg', 'audio/mpeg', 'audio/mp4', 'audio/wav', 'video/mp4', 'video/webm',
                          'image/webp', 'image/png', 'image/jpeg', 'image/svg+xml', 'application/epub+zip',
                          'text/vtt', 'application/pdf')),
    byte_size         INTEGER NOT NULL CHECK (byte_size > 0),
    duration_ms       INTEGER CHECK (duration_ms IS NULL OR duration_ms > 0),
    width             INTEGER CHECK (width IS NULL OR width > 0),
    height            INTEGER CHECK (height IS NULL OR height > 0),
    licence_code      TEXT    NOT NULL REFERENCES catalogue_licence,
    rights_scope      TEXT    NOT NULL CHECK (rights_scope IN ('private', 'shareable')),
    attribution       TEXT,
    source_url        TEXT,
    synthetic_voice   INTEGER NOT NULL DEFAULT 0 @BOOL,
    added_at          TEXT    NOT NULL @TS
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_media_asset_licence ON catalogue_media_asset (licence_code);

-- =====================================================================
-- catalogue: pack content, with rows for one pack version each (_v)
-- =====================================================================

-- Course settings (spec/course-config.schema.json).
CREATE TABLE catalogue_course_config_v (
    pack_version_id   INTEGER PRIMARY KEY REFERENCES catalogue_pack_version ON DELETE CASCADE,
    bridge_min        INTEGER NOT NULL CHECK (bridge_min BETWEEN 0 AND 6),
    bridge_max        INTEGER NOT NULL CHECK (bridge_max BETWEEN 1 AND 10),
    bridge_max_seconds INTEGER NOT NULL CHECK (bridge_max_seconds BETWEEN 30 AND 180),
    recall_below      REAL    NOT NULL CHECK (recall_below > 0 AND recall_below < 1),
    lapses_in_30_days INTEGER NOT NULL CHECK (lapses_in_30_days >= 1),
    warmup_skip_within_hours INTEGER NOT NULL CHECK (warmup_skip_within_hours >= 0),
    offer_review_first_above INTEGER NOT NULL CHECK (offer_review_first_above >= 1),
    warmup_target_seconds INTEGER NOT NULL CHECK (warmup_target_seconds > 0),
    warmup_limit_seconds INTEGER NOT NULL,
    reminders_max     INTEGER NOT NULL CHECK (reminders_max BETWEEN 0 AND 4),
    reminder_seconds  INTEGER NOT NULL CHECK (reminder_seconds BETWEEN 5 AND 60),
    fewer_new_above   REAL    NOT NULL CHECK (fewer_new_above > 0 AND fewer_new_above < 1),
    no_new_lesson_above REAL  NOT NULL CHECK (no_new_lesson_above > 0 AND no_new_lesson_above < 1),
    new_items_factor_when_reduced REAL NOT NULL CHECK (new_items_factor_when_reduced > 0 AND new_items_factor_when_reduced < 1),
    mix_recall_low    REAL    NOT NULL CHECK (mix_recall_low > 0 AND mix_recall_low < 1),
    mix_recall_high   REAL    NOT NULL CHECK (mix_recall_high > 0 AND mix_recall_high < 1),
    mix_skip_above    REAL    NOT NULL CHECK (mix_skip_above > 0 AND mix_skip_above < 1),
    mix_skip_within_hours INTEGER NOT NULL CHECK (mix_skip_within_hours >= 0),
    mix_updates_per_item_per_day INTEGER NOT NULL CHECK (mix_updates_per_item_per_day >= 1),
    mix_recognition_only_on_failure INTEGER NOT NULL @BOOL,
    CHECK (bridge_min <= bridge_max),
    CHECK (warmup_limit_seconds >= warmup_target_seconds),
    CHECK (fewer_new_above < no_new_lesson_above),
    CHECK (mix_recall_low < mix_recall_high AND mix_recall_high <= mix_skip_above)
) STRICT;

CREATE TABLE catalogue_preteach_limit_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    level             TEXT    NOT NULL @LEVEL,
    max_items         INTEGER NOT NULL CHECK (max_items BETWEEN 0 AND 8),
    PRIMARY KEY (pack_version_id, level)
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_listening_rule_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    level             TEXT    NOT NULL @LEVEL,
    listens_without_text INTEGER NOT NULL CHECK (listens_without_text BETWEEN 0 AND 3),
    extra_listen_offered INTEGER NOT NULL DEFAULT 0 @BOOL,
    transliteration_listen INTEGER NOT NULL DEFAULT 0 @BOOL,
    transcript_from   INTEGER NOT NULL CHECK (transcript_from BETWEEN 1 AND 4),
    highlight_words   INTEGER NOT NULL DEFAULT 0 @BOOL,
    english_from      INTEGER NOT NULL CHECK (english_from BETWEEN 1 AND 4),
    english_mode      TEXT    NOT NULL CHECK (english_mode IN ('per-line', 'per-line-and-switch', 'off', 'target-language-definitions')),
    slower_speed      INTEGER NOT NULL DEFAULT 1 @BOOL,
    PRIMARY KEY (pack_version_id, level),
    CHECK (transcript_from > listens_without_text)
) STRICT, WITHOUT ROWID;

-- Interface names and strings in the pack's language (ui.yaml).
CREATE TABLE catalogue_element_name_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    element_key       TEXT    NOT NULL REFERENCES catalogue_ui_element,
    name_tl           TEXT    NOT NULL CHECK (length(name_tl) BETWEEN 1 AND 40),
    PRIMARY KEY (pack_version_id, element_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_element_name_v_element ON catalogue_element_name_v (element_key);

CREATE TABLE catalogue_ui_string_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    string_key        TEXT    NOT NULL CHECK (string_key NOT GLOB '*[^a-z0-9_.]*'),
    message_icu       TEXT    NOT NULL,
    PRIMARY KEY (pack_version_id, string_key)
) STRICT;

CREATE TABLE catalogue_glossary_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    term_key          TEXT    NOT NULL CHECK (term_key NOT GLOB '*[^a-z0-9_-]*'),
    term_tl           TEXT    NOT NULL,
    term_en           TEXT    NOT NULL,
    explanation_en    TEXT    NOT NULL,
    explanation_tl    TEXT,
    PRIMARY KEY (pack_version_id, term_key)
) STRICT;

-- Course tree: level, stage, unit, lesson and domain module nodes.
CREATE TABLE catalogue_course_node_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    parent_item_id    INTEGER,
    node_type         TEXT    NOT NULL CHECK (node_type IN ('level', 'stage', 'unit', 'lesson', 'module')),
    position          INTEGER NOT NULL CHECK (position >= 0),
    level             TEXT    @LEVEL,
    title_tl          TEXT    NOT NULL,
    title_en          TEXT    NOT NULL,
    estimated_minutes INTEGER CHECK (estimated_minutes IS NULL OR estimated_minutes > 0),
    lesson_role       TEXT    CHECK (lesson_role IN ('core', 'fluency', 'culture', 'capstone', 'checkpoint', 'recap')),
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, parent_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id),
    UNIQUE (pack_version_id, parent_item_id, position),
    CHECK ((node_type = 'lesson') = (lesson_role IS NOT NULL)),
    CHECK (parent_item_id IS NULL OR parent_item_id <> item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_course_node_v_item ON catalogue_course_node_v (item_id);
CREATE UNIQUE INDEX catalogue_course_node_v_root_position ON catalogue_course_node_v (pack_version_id, position) WHERE parent_item_id IS NULL;

-- Lesson-only fields (spec/lesson.schema.json).
CREATE TABLE catalogue_lesson_v (
    pack_version_id   INTEGER NOT NULL,
    item_id           INTEGER NOT NULL,
    recap_of_item_id  INTEGER,
    prediction_tl     TEXT,
    prediction_en     TEXT,
    prediction_multiple INTEGER @BOOL,
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, recap_of_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id),
    CHECK ((prediction_tl IS NULL) = (prediction_multiple IS NULL))
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_lesson_v_recap ON catalogue_lesson_v (pack_version_id, recap_of_item_id);

CREATE TABLE catalogue_prediction_option_v (
    pack_version_id   INTEGER NOT NULL,
    lesson_item_id    INTEGER NOT NULL,
    option_no         INTEGER NOT NULL CHECK (option_no >= 0),
    text_tl           TEXT    NOT NULL,
    text_en           TEXT,
    is_answer         INTEGER NOT NULL @BOOL,
    feedback_tl       TEXT,
    feedback_en       TEXT,
    PRIMARY KEY (pack_version_id, lesson_item_id, option_no),
    FOREIGN KEY (pack_version_id, lesson_item_id) REFERENCES catalogue_lesson_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_lesson_return_v (
    pack_version_id   INTEGER NOT NULL,
    lesson_item_id    INTEGER NOT NULL,
    node_item_id      INTEGER NOT NULL,
    PRIMARY KEY (pack_version_id, lesson_item_id, node_item_id),
    FOREIGN KEY (pack_version_id, lesson_item_id) REFERENCES catalogue_lesson_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, node_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_lesson_return_v_node ON catalogue_lesson_return_v (pack_version_id, node_item_id);

-- The items linked to a lesson, by role: taught, taught before the input (preteach), built on,
-- or shown without being taught (exposure_only).
CREATE TABLE catalogue_lesson_item_v (
    pack_version_id   INTEGER NOT NULL,
    lesson_item_id    INTEGER NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    relation          TEXT    NOT NULL CHECK (relation IN ('teaches', 'preteach', 'builds_on', 'exposure_only')),
    weight            TEXT    CHECK (weight IN ('core', 'support')),
    position          INTEGER NOT NULL CHECK (position >= 0),
    taught_in_item_id INTEGER,
    prompt_target     TEXT,
    prompt_transliteration TEXT,
    prompt_cue_en     TEXT,
    PRIMARY KEY (pack_version_id, lesson_item_id, item_id),
    FOREIGN KEY (pack_version_id, lesson_item_id) REFERENCES catalogue_lesson_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, taught_in_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id),
    CHECK ((relation = 'builds_on') = (weight IS NOT NULL)),
    CHECK ((relation = 'exposure_only') = (taught_in_item_id IS NOT NULL)),
    CHECK (relation = 'builds_on' OR (prompt_target IS NULL AND prompt_transliteration IS NULL AND prompt_cue_en IS NULL))
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_lesson_item_v_item ON catalogue_lesson_item_v (item_id);
CREATE INDEX catalogue_lesson_item_v_taught_in ON catalogue_lesson_item_v (pack_version_id, taught_in_item_id);

-- Activities. Fields that differ by activity type are in payload, checked against the
-- pack JSON Schema at build time and not used in SQL conditions (see the data model document).
CREATE TABLE catalogue_activity_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    lesson_item_id    INTEGER,
    step              TEXT    CHECK (step IN ('warm-up', 'input', 'notice', 'practise', 'your-turn', 'wrap-up')),
    position          INTEGER NOT NULL CHECK (position >= 0),
    activity_type     TEXT    NOT NULL REFERENCES catalogue_activity_type,
    purpose           TEXT    NOT NULL CHECK (purpose IN ('lesson', 'practice', 'placement', 'checkpoint', 'level_exam', 'tour')),
    grammar_item_id   INTEGER REFERENCES catalogue_item,
    media_sha256      TEXT    REFERENCES catalogue_media_asset,
    prompt_tl         TEXT,
    prompt_en         TEXT,
    payload           TEXT    CHECK (payload IS NULL OR json_valid(payload)),
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, lesson_item_id) REFERENCES catalogue_lesson_v (pack_version_id, item_id),
    CHECK ((lesson_item_id IS NULL) = (step IS NULL)),
    CHECK ((purpose = 'lesson') = (lesson_item_id IS NOT NULL))
) STRICT;
CREATE INDEX catalogue_activity_v_item ON catalogue_activity_v (item_id);
CREATE INDEX catalogue_activity_v_lesson ON catalogue_activity_v (pack_version_id, lesson_item_id, position);
CREATE INDEX catalogue_activity_v_type ON catalogue_activity_v (activity_type);
CREATE INDEX catalogue_activity_v_grammar ON catalogue_activity_v (grammar_item_id);
CREATE INDEX catalogue_activity_v_media ON catalogue_activity_v (media_sha256);

-- Items used in an activity, and which of them the learner has to produce.
CREATE TABLE catalogue_activity_use_v (
    pack_version_id   INTEGER NOT NULL,
    activity_item_id  INTEGER NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    production_target INTEGER NOT NULL DEFAULT 0 @BOOL,
    PRIMARY KEY (pack_version_id, activity_item_id, item_id),
    FOREIGN KEY (pack_version_id, activity_item_id) REFERENCES catalogue_activity_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_activity_use_v_item ON catalogue_activity_use_v (item_id);

CREATE TABLE catalogue_accepted_answer_v (
    pack_version_id   INTEGER NOT NULL,
    activity_item_id  INTEGER NOT NULL,
    slot              INTEGER NOT NULL DEFAULT 0 CHECK (slot >= 0),
    answer_no         INTEGER NOT NULL CHECK (answer_no >= 0),
    answer_text       TEXT    NOT NULL CHECK (length(answer_text) >= 1),
    variety_id        INTEGER REFERENCES catalogue_variety,
    preferred         INTEGER NOT NULL DEFAULT 0 @BOOL,
    PRIMARY KEY (pack_version_id, activity_item_id, slot, answer_no),
    FOREIGN KEY (pack_version_id, activity_item_id) REFERENCES catalogue_activity_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_accepted_answer_v_variety ON catalogue_accepted_answer_v (variety_id);
CREATE UNIQUE INDEX catalogue_accepted_answer_v_one_preferred ON catalogue_accepted_answer_v (pack_version_id, activity_item_id, slot) WHERE preferred = 1;

-- Lexicon.
CREATE TABLE catalogue_lexeme_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    lemma             TEXT    NOT NULL CHECK (length(lemma) >= 1),
    upos              TEXT    NOT NULL CHECK (upos IN ('ADJ', 'ADP', 'ADV', 'AUX', 'CCONJ', 'DET', 'INTJ', 'NOUN',
                                                    'NUM', 'PART', 'PRON', 'PROPN', 'SCONJ', 'VERB', 'X')),
    frequency_rank    INTEGER CHECK (frequency_rank IS NULL OR frequency_rank > 0),
    level             TEXT    @LEVEL,
    added_for_course  INTEGER NOT NULL DEFAULT 0 @BOOL,
    review_status     TEXT    NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft', 'native_checked')),
    PRIMARY KEY (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_lexeme_v_item ON catalogue_lexeme_v (item_id);
CREATE INDEX catalogue_lexeme_v_lemma ON catalogue_lexeme_v (pack_version_id, lemma);

-- Grammatical features with Universal Dependencies names, for example Gender=Com.
-- A word that takes both de and het has two rows.
CREATE TABLE catalogue_lexeme_feature_v (
    pack_version_id   INTEGER NOT NULL,
    lexeme_item_id    INTEGER NOT NULL,
    feature           TEXT    NOT NULL CHECK (feature GLOB '[A-Z]*' AND feature NOT GLOB '*[^A-Za-z]*'),
    value             TEXT    NOT NULL CHECK (value GLOB '[A-Z0-9]*' AND value NOT GLOB '*[^A-Za-z0-9]*'),
    PRIMARY KEY (pack_version_id, lexeme_item_id, feature, value),
    FOREIGN KEY (pack_version_id, lexeme_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_sense_v (
    pack_version_id   INTEGER NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    lexeme_item_id    INTEGER NOT NULL,
    sense_no          INTEGER NOT NULL CHECK (sense_no >= 1),
    gloss_en          TEXT    NOT NULL,
    definition_tl     TEXT,
    register          TEXT    NOT NULL DEFAULT 'neutral' CHECK (register IN ('neutral', 'informal', 'formal', 'vulgar', 'dated', 'technical')),
    variety_id        INTEGER REFERENCES catalogue_variety,
    level             TEXT    @LEVEL,
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, lexeme_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id) ON DELETE CASCADE,
    UNIQUE (pack_version_id, lexeme_item_id, sense_no)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_sense_v_item ON catalogue_sense_v (item_id);
CREATE INDEX catalogue_sense_v_variety ON catalogue_sense_v (variety_id);

CREATE TABLE catalogue_sense_example_v (
    pack_version_id   INTEGER NOT NULL,
    sense_item_id     INTEGER NOT NULL,
    example_no        INTEGER NOT NULL CHECK (example_no >= 1),
    text_tl           TEXT    NOT NULL,
    text_en           TEXT    NOT NULL,
    audio_sha256      TEXT    REFERENCES catalogue_media_asset,
    PRIMARY KEY (pack_version_id, sense_item_id, example_no),
    FOREIGN KEY (pack_version_id, sense_item_id) REFERENCES catalogue_sense_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_sense_example_v_audio ON catalogue_sense_example_v (audio_sha256);

CREATE TABLE catalogue_picture_v (
    pack_version_id   INTEGER NOT NULL,
    sense_item_id     INTEGER NOT NULL,
    image_sha256      TEXT    NOT NULL REFERENCES catalogue_media_asset,
    alt_en            TEXT    NOT NULL,
    alt_tl            TEXT,
    PRIMARY KEY (pack_version_id, sense_item_id, image_sha256),
    FOREIGN KEY (pack_version_id, sense_item_id) REFERENCES catalogue_sense_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_picture_v_image ON catalogue_picture_v (image_sha256);

CREATE TABLE catalogue_deck_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    deck_key          TEXT    NOT NULL CHECK (deck_key NOT GLOB '*[^a-z0-9-]*'),
    title_tl          TEXT    NOT NULL,
    title_en          TEXT    NOT NULL,
    PRIMARY KEY (pack_version_id, deck_key)
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_deck_item_v (
    pack_version_id   INTEGER NOT NULL,
    deck_key          TEXT    NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    position          INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (pack_version_id, deck_key, item_id),
    FOREIGN KEY (pack_version_id, deck_key) REFERENCES catalogue_deck_v (pack_version_id, deck_key) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_deck_item_v_item ON catalogue_deck_item_v (item_id);

-- Paradigm cells defined by the pack, for example present.2sg.inverted, past.pl or plural.
CREATE TABLE catalogue_paradigm_cell_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    cell_key          TEXT    NOT NULL CHECK (cell_key NOT GLOB '*[^a-z0-9._-]*'),
    upos              TEXT    NOT NULL,
    form_type         TEXT    NOT NULL CHECK (form_type NOT GLOB '*[^a-z_]*'),
    ud_feats          TEXT,
    label_tl          TEXT    NOT NULL,
    label_en          TEXT    NOT NULL,
    position          INTEGER NOT NULL CHECK (position >= 0),
    PRIMARY KEY (pack_version_id, cell_key)
) STRICT, WITHOUT ROWID;

-- Inflected forms. A cell can have more than one variant (zei, zegde), and a variant can
-- be limited to one variety. A form that does not exist is a row with nonexistent = 1.
CREATE TABLE catalogue_form_v (
    pack_version_id   INTEGER NOT NULL,
    lexeme_item_id    INTEGER NOT NULL,
    cell_key          TEXT    NOT NULL,
    variant_no        INTEGER NOT NULL DEFAULT 1 CHECK (variant_no >= 1),
    form              TEXT,
    variety_id        INTEGER REFERENCES catalogue_variety,
    nonexistent       INTEGER NOT NULL DEFAULT 0 @BOOL,
    PRIMARY KEY (pack_version_id, lexeme_item_id, cell_key, variant_no),
    FOREIGN KEY (pack_version_id, lexeme_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, cell_key) REFERENCES catalogue_paradigm_cell_v (pack_version_id, cell_key),
    CHECK ((nonexistent = 1 AND form IS NULL AND variant_no = 1) OR (nonexistent = 0 AND form IS NOT NULL))
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_form_v_form ON catalogue_form_v (pack_version_id, form);
CREATE INDEX catalogue_form_v_cell ON catalogue_form_v (pack_version_id, cell_key);
CREATE INDEX catalogue_form_v_variety ON catalogue_form_v (variety_id);

CREATE TABLE catalogue_verb_class_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    class_key         TEXT    NOT NULL CHECK (class_key NOT GLOB '*[^a-z_]*'),
    label_tl          TEXT    NOT NULL,
    label_en          TEXT    NOT NULL,
    PRIMARY KEY (pack_version_id, class_key)
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_verb_v (
    pack_version_id   INTEGER NOT NULL,
    lexeme_item_id    INTEGER NOT NULL,
    class_key         TEXT    NOT NULL,
    stem              TEXT    NOT NULL,
    vowel_pattern     TEXT,
    separable_particle TEXT,
    subject           TEXT    NOT NULL DEFAULT 'any' CHECK (subject IN ('any', 'third_person', 'impersonal')),
    chart_rank        INTEGER CHECK (chart_rank IS NULL OR chart_rank > 0),
    review_status     TEXT    NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft', 'native_checked')),
    PRIMARY KEY (pack_version_id, lexeme_item_id),
    FOREIGN KEY (pack_version_id, lexeme_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, class_key) REFERENCES catalogue_verb_class_v (pack_version_id, class_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_verb_v_class ON catalogue_verb_v (pack_version_id, class_key);

-- Auxiliaries for the perfect: one row per auxiliary, so a verb with hebben and zijn has two.
CREATE TABLE catalogue_verb_auxiliary_v (
    pack_version_id   INTEGER NOT NULL,
    verb_item_id      INTEGER NOT NULL,
    auxiliary_item_id INTEGER NOT NULL,
    condition_en      TEXT,
    example_tl        TEXT,
    example_en        TEXT,
    PRIMARY KEY (pack_version_id, verb_item_id, auxiliary_item_id),
    FOREIGN KEY (pack_version_id, verb_item_id) REFERENCES catalogue_verb_v (pack_version_id, lexeme_item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, auxiliary_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_verb_auxiliary_v_aux ON catalogue_verb_auxiliary_v (pack_version_id, auxiliary_item_id);

-- Pronunciation per variety and speaker.
CREATE TABLE catalogue_speaker_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    speaker_key       TEXT    NOT NULL CHECK (speaker_key NOT GLOB '*[^a-z0-9-]*'),
    display_name      TEXT    NOT NULL,
    variety_id        INTEGER NOT NULL REFERENCES catalogue_variety,
    voice_kind        TEXT    NOT NULL CHECK (voice_kind IN ('recorded', 'synthetic')),
    PRIMARY KEY (pack_version_id, speaker_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_speaker_v_variety ON catalogue_speaker_v (variety_id);

CREATE TABLE catalogue_pronunciation_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    pronunciation_no  INTEGER NOT NULL CHECK (pronunciation_no >= 1),
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    variety_id        INTEGER NOT NULL REFERENCES catalogue_variety,
    speaker_key       TEXT,
    ipa               TEXT,
    audio_sha256      TEXT    REFERENCES catalogue_media_asset,
    PRIMARY KEY (pack_version_id, pronunciation_no),
    FOREIGN KEY (pack_version_id, speaker_key) REFERENCES catalogue_speaker_v (pack_version_id, speaker_key),
    CHECK (ipa IS NOT NULL OR audio_sha256 IS NOT NULL),
    CHECK ((audio_sha256 IS NULL) = (speaker_key IS NULL))
) STRICT, WITHOUT ROWID;
CREATE UNIQUE INDEX catalogue_pronunciation_v_unique ON catalogue_pronunciation_v (pack_version_id, item_id, variety_id, ifnull(speaker_key, ''));
CREATE INDEX catalogue_pronunciation_v_item ON catalogue_pronunciation_v (item_id);
CREATE INDEX catalogue_pronunciation_v_variety ON catalogue_pronunciation_v (variety_id);
CREATE INDEX catalogue_pronunciation_v_speaker ON catalogue_pronunciation_v (pack_version_id, speaker_key);
CREATE INDEX catalogue_pronunciation_v_audio ON catalogue_pronunciation_v (audio_sha256);

-- Chunks and formulas.
CREATE TABLE catalogue_chunk_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    text_tl           TEXT    NOT NULL,
    gloss_en          TEXT    NOT NULL,
    literal_en        TEXT,
    function_en       TEXT,
    register          TEXT    NOT NULL DEFAULT 'neutral' CHECK (register IN ('neutral', 'informal', 'formal', 'vulgar', 'dated', 'technical')),
    level             TEXT    @LEVEL,
    PRIMARY KEY (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_chunk_v_item ON catalogue_chunk_v (item_id);

CREATE TABLE catalogue_chunk_part_v (
    pack_version_id   INTEGER NOT NULL,
    chunk_item_id     INTEGER NOT NULL,
    position          INTEGER NOT NULL CHECK (position >= 0),
    surface           TEXT    NOT NULL,
    lexeme_item_id    INTEGER,
    PRIMARY KEY (pack_version_id, chunk_item_id, position),
    FOREIGN KEY (pack_version_id, chunk_item_id) REFERENCES catalogue_chunk_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, lexeme_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_chunk_part_v_lexeme ON catalogue_chunk_part_v (pack_version_id, lexeme_item_id);

-- Grammar graph, explanations and rules.
CREATE TABLE catalogue_grammar_point_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    title_tl          TEXT    NOT NULL,
    title_en          TEXT    NOT NULL,
    level             TEXT    @LEVEL,
    review_status     TEXT    NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft', 'native_checked')),
    PRIMARY KEY (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_grammar_point_v_item ON catalogue_grammar_point_v (item_id);

CREATE TABLE catalogue_grammar_prerequisite_v (
    pack_version_id   INTEGER NOT NULL,
    grammar_item_id   INTEGER NOT NULL,
    requires_item_id  INTEGER NOT NULL,
    PRIMARY KEY (pack_version_id, grammar_item_id, requires_item_id),
    FOREIGN KEY (pack_version_id, grammar_item_id) REFERENCES catalogue_grammar_point_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, requires_item_id) REFERENCES catalogue_grammar_point_v (pack_version_id, item_id),
    CHECK (grammar_item_id <> requires_item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_grammar_prerequisite_v_requires ON catalogue_grammar_prerequisite_v (pack_version_id, requires_item_id);

-- Explanation sections from the template, at three depths.
CREATE TABLE catalogue_explanation_v (
    pack_version_id   INTEGER NOT NULL,
    grammar_item_id   INTEGER NOT NULL,
    depth             TEXT    NOT NULL CHECK (depth IN ('short', 'full', 'technical')),
    section           TEXT    NOT NULL CHECK (section IN ('concept', 'elements', 'how_it_works', 'variations',
                                                        'exceptions', 'common_errors', 'contrast_and_varieties')),
    body_en_md        TEXT    NOT NULL,
    body_tl_md        TEXT,
    PRIMARY KEY (pack_version_id, grammar_item_id, depth, section),
    FOREIGN KEY (pack_version_id, grammar_item_id) REFERENCES catalogue_grammar_point_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT;

-- Rules with decision or formation steps, for example niet and geen, 't kofschip and the spelling rules.
CREATE TABLE catalogue_rule_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    grammar_item_id   INTEGER,
    rule_type         TEXT    NOT NULL CHECK (rule_type IN ('decision', 'formation', 'spelling', 'sound_spelling')),
    title_tl          TEXT    NOT NULL,
    title_en          TEXT    NOT NULL,
    why_en_md         TEXT,
    review_status     TEXT    NOT NULL DEFAULT 'draft' CHECK (review_status IN ('draft', 'native_checked')),
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, grammar_item_id) REFERENCES catalogue_grammar_point_v (pack_version_id, item_id)
) STRICT;
CREATE INDEX catalogue_rule_v_item ON catalogue_rule_v (item_id);
CREATE INDEX catalogue_rule_v_grammar ON catalogue_rule_v (pack_version_id, grammar_item_id);

-- A step is an item of its own (key such as nl:grammar:niet-geen#ng-2), so a wrong answer
-- can be linked to the step where the learner went wrong.
CREATE TABLE catalogue_rule_step_v (
    pack_version_id   INTEGER NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    rule_item_id      INTEGER NOT NULL,
    position          INTEGER NOT NULL CHECK (position >= 1),
    question_en       TEXT    NOT NULL,
    question_tl       TEXT,
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, rule_item_id) REFERENCES catalogue_rule_v (pack_version_id, item_id) ON DELETE CASCADE,
    UNIQUE (pack_version_id, rule_item_id, position)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_rule_step_v_item ON catalogue_rule_step_v (item_id);

CREATE TABLE catalogue_rule_step_outcome_v (
    pack_version_id   INTEGER NOT NULL,
    step_item_id      INTEGER NOT NULL,
    outcome_no        INTEGER NOT NULL CHECK (outcome_no >= 1),
    answer_en         TEXT    NOT NULL,
    answer_tl         TEXT,
    action_en         TEXT    NOT NULL,
    next_step_item_id INTEGER,
    PRIMARY KEY (pack_version_id, step_item_id, outcome_no),
    FOREIGN KEY (pack_version_id, step_item_id) REFERENCES catalogue_rule_step_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, next_step_item_id) REFERENCES catalogue_rule_step_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_rule_step_outcome_v_next ON catalogue_rule_step_outcome_v (pack_version_id, next_step_item_id);

CREATE TABLE catalogue_rule_example_v (
    pack_version_id   INTEGER NOT NULL,
    rule_item_id      INTEGER NOT NULL,
    example_no        INTEGER NOT NULL CHECK (example_no >= 1),
    text_tl           TEXT    NOT NULL,
    text_en           TEXT    NOT NULL,
    step_item_id      INTEGER,
    worked            INTEGER NOT NULL DEFAULT 0 @BOOL,
    PRIMARY KEY (pack_version_id, rule_item_id, example_no),
    FOREIGN KEY (pack_version_id, rule_item_id) REFERENCES catalogue_rule_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, step_item_id) REFERENCES catalogue_rule_step_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_rule_example_v_step ON catalogue_rule_example_v (pack_version_id, step_item_id);

CREATE TABLE catalogue_rule_exception_v (
    pack_version_id   INTEGER NOT NULL,
    rule_item_id      INTEGER NOT NULL,
    exception_no      INTEGER NOT NULL CHECK (exception_no >= 1),
    lexeme_item_id    INTEGER,
    note_en           TEXT    NOT NULL,
    example_tl        TEXT,
    PRIMARY KEY (pack_version_id, rule_item_id, exception_no),
    FOREIGN KEY (pack_version_id, rule_item_id) REFERENCES catalogue_rule_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, lexeme_item_id) REFERENCES catalogue_lexeme_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_rule_exception_v_lexeme ON catalogue_rule_exception_v (pack_version_id, lexeme_item_id);

-- Which rules apply to a verb (shown beside its chart).
CREATE TABLE catalogue_verb_rule_v (
    pack_version_id   INTEGER NOT NULL,
    verb_item_id      INTEGER NOT NULL,
    rule_item_id      INTEGER NOT NULL,
    PRIMARY KEY (pack_version_id, verb_item_id, rule_item_id),
    FOREIGN KEY (pack_version_id, verb_item_id) REFERENCES catalogue_verb_v (pack_version_id, lexeme_item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, rule_item_id) REFERENCES catalogue_rule_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_verb_rule_v_rule ON catalogue_verb_rule_v (pack_version_id, rule_item_id);

-- Grammar points that learners often confuse, for interleaved practice in the mixed run.
CREATE TABLE catalogue_confusable_pair_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_a_id         INTEGER NOT NULL REFERENCES catalogue_item,
    item_b_id         INTEGER NOT NULL REFERENCES catalogue_item,
    PRIMARY KEY (pack_version_id, item_a_id, item_b_id),
    CHECK (item_a_id < item_b_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_confusable_pair_v_a ON catalogue_confusable_pair_v (item_a_id);
CREATE INDEX catalogue_confusable_pair_v_b ON catalogue_confusable_pair_v (item_b_id);

-- Sounds and minimal pairs.
CREATE TABLE catalogue_sound_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    ipa               TEXT    NOT NULL,
    name_en           TEXT    NOT NULL,
    description_en    TEXT,
    PRIMARY KEY (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_sound_v_item ON catalogue_sound_v (item_id);

CREATE TABLE catalogue_sound_contrast_v (
    pack_version_id   INTEGER NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    sound_a_item_id   INTEGER NOT NULL,
    sound_b_item_id   INTEGER NOT NULL,
    priority          INTEGER CHECK (priority IS NULL OR priority >= 1),
    note_en           TEXT,
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, sound_a_item_id) REFERENCES catalogue_sound_v (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, sound_b_item_id) REFERENCES catalogue_sound_v (pack_version_id, item_id),
    CHECK (sound_a_item_id <> sound_b_item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_sound_contrast_v_item ON catalogue_sound_contrast_v (item_id);
CREATE INDEX catalogue_sound_contrast_v_a ON catalogue_sound_contrast_v (pack_version_id, sound_a_item_id);
CREATE INDEX catalogue_sound_contrast_v_b ON catalogue_sound_contrast_v (pack_version_id, sound_b_item_id);

CREATE TABLE catalogue_minimal_pair_v (
    pack_version_id   INTEGER NOT NULL,
    contrast_item_id  INTEGER NOT NULL,
    pair_no           INTEGER NOT NULL CHECK (pair_no >= 1),
    word_a            TEXT    NOT NULL,
    word_b            TEXT    NOT NULL,
    PRIMARY KEY (pack_version_id, contrast_item_id, pair_no),
    FOREIGN KEY (pack_version_id, contrast_item_id) REFERENCES catalogue_sound_contrast_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_minimal_pair_audio_v (
    pack_version_id   INTEGER NOT NULL,
    contrast_item_id  INTEGER NOT NULL,
    pair_no           INTEGER NOT NULL,
    side              TEXT    NOT NULL CHECK (side IN ('a', 'b')),
    speaker_key       TEXT    NOT NULL,
    audio_sha256      TEXT    NOT NULL REFERENCES catalogue_media_asset,
    PRIMARY KEY (pack_version_id, contrast_item_id, pair_no, side, speaker_key),
    FOREIGN KEY (pack_version_id, contrast_item_id, pair_no) REFERENCES catalogue_minimal_pair_v (pack_version_id, contrast_item_id, pair_no) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, speaker_key) REFERENCES catalogue_speaker_v (pack_version_id, speaker_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_minimal_pair_audio_v_speaker ON catalogue_minimal_pair_audio_v (pack_version_id, speaker_key);
CREATE INDEX catalogue_minimal_pair_audio_v_audio ON catalogue_minimal_pair_audio_v (audio_sha256);

-- Can-do descriptors, the components that are measured for a descriptor, and the items that count as evidence.
CREATE TABLE catalogue_can_do_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    level             TEXT    NOT NULL @LEVEL,
    activity          TEXT    NOT NULL CHECK (activity IN ('listening', 'reading', 'audiovisual', 'spoken_production',
                                   'written_production', 'spoken_interaction', 'written_interaction', 'mediation')),
    descriptor_en     TEXT    NOT NULL,
    descriptor_tl     TEXT,
    PRIMARY KEY (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_can_do_v_item ON catalogue_can_do_v (item_id);

CREATE TABLE catalogue_can_do_component_v (
    pack_version_id   INTEGER NOT NULL,
    can_do_item_id    INTEGER NOT NULL,
    component         TEXT    NOT NULL CHECK (component IN ('vocabulary', 'grammar', 'pronunciation', 'spelling',
                                   'pragmatics', 'sociocultural', 'fluency', 'comprehension')),
    PRIMARY KEY (pack_version_id, can_do_item_id, component),
    FOREIGN KEY (pack_version_id, can_do_item_id) REFERENCES catalogue_can_do_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

CREATE TABLE catalogue_can_do_evidence_v (
    pack_version_id   INTEGER NOT NULL,
    can_do_item_id    INTEGER NOT NULL,
    component         TEXT    NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    weight            REAL    NOT NULL DEFAULT 1.0 CHECK (weight > 0 AND weight <= 10),
    PRIMARY KEY (pack_version_id, can_do_item_id, component, item_id),
    FOREIGN KEY (pack_version_id, can_do_item_id, component) REFERENCES catalogue_can_do_component_v (pack_version_id, can_do_item_id, component) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_can_do_evidence_v_item ON catalogue_can_do_evidence_v (item_id);

CREATE TABLE catalogue_node_can_do_v (
    pack_version_id   INTEGER NOT NULL,
    node_item_id      INTEGER NOT NULL,
    can_do_item_id    INTEGER NOT NULL,
    PRIMARY KEY (pack_version_id, node_item_id, can_do_item_id),
    FOREIGN KEY (pack_version_id, node_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id) ON DELETE CASCADE,
    FOREIGN KEY (pack_version_id, can_do_item_id) REFERENCES catalogue_can_do_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_node_can_do_v_can_do ON catalogue_node_can_do_v (pack_version_id, can_do_item_id);

CREATE TABLE catalogue_scenario_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    title_tl          TEXT    NOT NULL,
    title_en          TEXT    NOT NULL,
    setting_en        TEXT    NOT NULL,
    goal_en           TEXT    NOT NULL,
    role_a_en         TEXT    NOT NULL,
    role_b_en         TEXT    NOT NULL,
    register          TEXT    NOT NULL DEFAULT 'neutral' CHECK (register IN ('neutral', 'informal', 'formal')),
    level             TEXT    NOT NULL @LEVEL,
    can_do_item_id    INTEGER,
    variety_id        INTEGER REFERENCES catalogue_variety,
    -- Scenarios with the same slot (course node and slot number) are alternatives for one
    -- place in the course, for example the fluency lesson. They share the slot's can-do,
    -- and the learner's goals are used to choose between them (decision of 21 November 2026).
    slot_node_item_id INTEGER,
    slot_no           INTEGER CHECK (slot_no IS NULL OR slot_no >= 1),
    PRIMARY KEY (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, can_do_item_id) REFERENCES catalogue_can_do_v (pack_version_id, item_id),
    FOREIGN KEY (pack_version_id, slot_node_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id),
    CHECK ((slot_node_item_id IS NULL) = (slot_no IS NULL))
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_scenario_v_item ON catalogue_scenario_v (item_id);
CREATE INDEX catalogue_scenario_v_slot ON catalogue_scenario_v (pack_version_id, slot_node_item_id, slot_no);
CREATE INDEX catalogue_scenario_v_can_do ON catalogue_scenario_v (pack_version_id, can_do_item_id);
CREATE INDEX catalogue_scenario_v_variety ON catalogue_scenario_v (variety_id);

-- Learner goals as the pack offers them. The goal keys belong to the app (study_goal) and are
-- the same in every pack; the pack has the names and says which goals it offers.
CREATE TABLE catalogue_goal_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    goal_key          TEXT    NOT NULL REFERENCES study_goal,
    name_tl           TEXT    NOT NULL,
    name_en           TEXT    NOT NULL,
    position          INTEGER NOT NULL CHECK (position >= 1),
    offered           INTEGER NOT NULL DEFAULT 1 @BOOL,
    PRIMARY KEY (pack_version_id, goal_key),
    UNIQUE (pack_version_id, position)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_goal_v_goal ON catalogue_goal_v (goal_key);

-- Goal tags on scenarios, can-dos and course nodes. An item with no tag is general and is
-- offered to every learner.
CREATE TABLE catalogue_goal_link_v (
    pack_version_id   INTEGER NOT NULL,
    goal_key          TEXT    NOT NULL,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    weight            REAL    NOT NULL DEFAULT 1.0 CHECK (weight > 0 AND weight <= 1),
    PRIMARY KEY (pack_version_id, goal_key, item_id),
    FOREIGN KEY (pack_version_id, goal_key) REFERENCES catalogue_goal_v (pack_version_id, goal_key) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_goal_link_v_item ON catalogue_goal_link_v (item_id);

-- Exams a learner can name as a target. available = 0: listed as coming after this release.
CREATE TABLE catalogue_exam_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    exam_key          TEXT    NOT NULL CHECK (length(exam_key) >= 2 AND exam_key NOT GLOB '*[^a-z0-9_-]*'),
    name_tl           TEXT    NOT NULL,
    name_en           TEXT    NOT NULL,
    issuer            TEXT    NOT NULL,
    level             TEXT    NOT NULL @LEVEL,
    skills            TEXT    NOT NULL,
    url               TEXT,
    checked_on        TEXT    NOT NULL @DAY,
    level_exam_item_id INTEGER,
    available         INTEGER NOT NULL DEFAULT 1 @BOOL,
    PRIMARY KEY (pack_version_id, exam_key),
    FOREIGN KEY (pack_version_id, level_exam_item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_exam_v_level_exam ON catalogue_exam_v (pack_version_id, level_exam_item_id);

-- Domain module fields (a module is a course node). Terminology is offered from the first
-- level, and genre and task work from the second.
CREATE TABLE catalogue_module_v (
    pack_version_id   INTEGER NOT NULL,
    item_id           INTEGER NOT NULL,
    terminology_from  TEXT    NOT NULL @LEVEL,
    tasks_from        TEXT    NOT NULL @LEVEL,
    PRIMARY KEY (pack_version_id, item_id),
    CHECK (instr(',orientation,pre-a1,a1,a2,b1,b2,c1,c2,professional,', ',' || terminology_from || ',') <= instr(',orientation,pre-a1,a1,a2,b1,b2,c1,c2,professional,', ',' || tasks_from || ',')),
    FOREIGN KEY (pack_version_id, item_id) REFERENCES catalogue_course_node_v (pack_version_id, item_id) ON DELETE CASCADE
) STRICT, WITHOUT ROWID;

-- Transcripts and word timings for pack audio and video.
CREATE TABLE catalogue_transcript_line_v (
    pack_version_id   INTEGER NOT NULL REFERENCES catalogue_pack_version ON DELETE CASCADE,
    media_sha256      TEXT    NOT NULL REFERENCES catalogue_media_asset,
    line_no           INTEGER NOT NULL CHECK (line_no >= 1),
    speaker_label     TEXT,
    start_ms          INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms            INTEGER NOT NULL,
    text_tl           TEXT    NOT NULL,
    text_en           TEXT,
    transliteration   TEXT,
    PRIMARY KEY (pack_version_id, media_sha256, line_no),
    CHECK (end_ms > start_ms)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_transcript_line_v_media ON catalogue_transcript_line_v (media_sha256);

CREATE TABLE catalogue_alignment_token_v (
    pack_version_id   INTEGER NOT NULL,
    media_sha256      TEXT    NOT NULL,
    line_no           INTEGER NOT NULL,
    token_no          INTEGER NOT NULL CHECK (token_no >= 1),
    surface           TEXT    NOT NULL,
    start_ms          INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms            INTEGER NOT NULL,
    item_id           INTEGER REFERENCES catalogue_item,
    grammar_item_id   INTEGER REFERENCES catalogue_item,
    PRIMARY KEY (pack_version_id, media_sha256, line_no, token_no),
    FOREIGN KEY (pack_version_id, media_sha256, line_no) REFERENCES catalogue_transcript_line_v (pack_version_id, media_sha256, line_no) ON DELETE CASCADE,
    CHECK (end_ms > start_ms)
) STRICT, WITHOUT ROWID;
CREATE INDEX catalogue_alignment_token_v_item ON catalogue_alignment_token_v (item_id);
CREATE INDEX catalogue_alignment_token_v_grammar ON catalogue_alignment_token_v (grammar_item_id);

-- Word search across the active version (lemmas, forms, glosses). Filled at import.
CREATE VIRTUAL TABLE catalogue_search_fts USING fts5 (
    term, gloss_en,
    pack_version_id UNINDEXED, item_id UNINDEXED,
    tokenize = 'unicode61 remove_diacritics 2'
);

-- =====================================================================
-- study: enrolments, plans, sessions, attempts, lookups, notes
-- =====================================================================

-- The goals a learner can choose (list of 21 November 2026). followup: the goal opens a second
-- question (which exam, which field).
CREATE TABLE study_goal (
    goal_key          TEXT    PRIMARY KEY CHECK (goal_key NOT GLOB '*[^a-z_]*'),
    name_en           TEXT    NOT NULL,
    description_en    TEXT    NOT NULL,
    followup          TEXT    CHECK (followup IN ('exam', 'field')),
    position          INTEGER NOT NULL UNIQUE
) STRICT, WITHOUT ROWID;

CREATE TABLE study_tour_part (
    tour_part_key     TEXT    PRIMARY KEY CHECK (tour_part_key NOT GLOB '*[^a-z_]*'),
    name_en           TEXT    NOT NULL,
    position          INTEGER NOT NULL UNIQUE
) STRICT, WITHOUT ROWID;

-- A learner's course in one language. Course-level settings are stored here.
CREATE TABLE study_enrolment (
    enrolment_id      INTEGER PRIMARY KEY,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    variety_id        INTEGER NOT NULL,
    daily_minutes     INTEGER NOT NULL DEFAULT 30 CHECK (daily_minutes BETWEEN 5 AND 240),
    depth             TEXT    NOT NULL DEFAULT 'full' CHECK (depth IN ('short', 'full', 'technical')),
    status            TEXT    NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'paused', 'ended')),
    started_at        TEXT    NOT NULL @TS,
    UNIQUE (learner_id, pack_id),
    FOREIGN KEY (pack_id, variety_id) REFERENCES catalogue_variety (pack_id, variety_id)
) STRICT;
CREATE INDEX study_enrolment_pack_variety ON study_enrolment (pack_id, variety_id);

-- Goals chosen by the learner. A removed goal keeps its row with removed_at, so progress can be
-- grouped by the goals that applied at the time.
CREATE TABLE study_enrolment_goal (
    enrolment_goal_id INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    goal_key          TEXT    NOT NULL REFERENCES study_goal,
    added_at          TEXT    NOT NULL @TS,
    removed_at        TEXT    @TS,
    CHECK (removed_at IS NULL OR removed_at >= added_at)
) STRICT;
CREATE INDEX study_enrolment_goal_enrolment ON study_enrolment_goal (enrolment_id);
CREATE UNIQUE INDEX study_enrolment_goal_open ON study_enrolment_goal (enrolment_id, goal_key) WHERE removed_at IS NULL;
CREATE INDEX study_enrolment_goal_goal ON study_enrolment_goal (goal_key);

-- A target level, with an optional date and exam (exam_key from catalogue_exam_v). One open
-- target per enrolment; a new one replaces it. The app shows a time range, never a countdown.
CREATE TABLE study_enrolment_target (
    target_id         INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    target_level      TEXT    @LEVEL,
    target_date       TEXT    @DAY,
    exam_key          TEXT,
    chosen_at         TEXT    NOT NULL @TS,
    replaced_at       TEXT    @TS,
    CHECK (target_level IS NOT NULL OR exam_key IS NOT NULL),
    CHECK (replaced_at IS NULL OR replaced_at >= chosen_at)
) STRICT;
CREATE INDEX study_enrolment_target_enrolment ON study_enrolment_target (enrolment_id);
CREATE UNIQUE INDEX study_enrolment_target_open ON study_enrolment_target (enrolment_id) WHERE replaced_at IS NULL;

-- Subject modules chosen under the subject goal (key field). A module that is not built yet is
-- an item of the pack with no content in the active version, so the choice can be stored and
-- shown as coming later.
CREATE TABLE study_enrolment_module (
    enrolment_module_id INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    module_item_id    INTEGER NOT NULL REFERENCES catalogue_item,
    terminology_on    INTEGER NOT NULL DEFAULT 1 @BOOL,
    added_at          TEXT    NOT NULL @TS,
    removed_at        TEXT    @TS,
    CHECK (removed_at IS NULL OR removed_at >= added_at)
) STRICT;
CREATE INDEX study_enrolment_module_enrolment ON study_enrolment_module (enrolment_id);
CREATE UNIQUE INDEX study_enrolment_module_open ON study_enrolment_module (enrolment_id, module_item_id) WHERE removed_at IS NULL;
CREATE INDEX study_enrolment_module_item ON study_enrolment_module (module_item_id);

-- The learner's own can-do list (up to 8 at a time): suggested from the goals or added by the
-- learner. It is shown to the learner and does not change what is tested at checkpoints. An
-- achieved can-do stays on the list until it is removed; the limit of 8 counts rows that are
-- neither achieved nor removed.
CREATE TABLE study_personal_can_do (
    personal_can_do_id INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    can_do_item_id    INTEGER NOT NULL REFERENCES catalogue_item,
    source            TEXT    NOT NULL CHECK (source IN ('goal', 'learner')),
    added_at          TEXT    NOT NULL @TS,
    achieved_at       TEXT    @TS,
    removed_at        TEXT    @TS,
    CHECK (achieved_at IS NULL OR achieved_at >= added_at),
    CHECK (removed_at IS NULL OR removed_at >= added_at)
) STRICT;
CREATE INDEX study_personal_can_do_enrolment ON study_personal_can_do (enrolment_id);
CREATE UNIQUE INDEX study_personal_can_do_open ON study_personal_can_do (enrolment_id, can_do_item_id) WHERE removed_at IS NULL;
CREATE INDEX study_personal_can_do_item ON study_personal_can_do (can_do_item_id);

-- "Your goals in Dutch", offered after 3 to 5 sessions: what the learner wants to be able to do,
-- in their own words, what might get in the way, and their plan for it. Optional.
CREATE TABLE study_goal_statement (
    goal_statement_id INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    statement         TEXT    NOT NULL CHECK (length(statement) BETWEEN 1 AND 1000),
    obstacle          TEXT    CHECK (length(obstacle) <= 500),
    plan              TEXT    CHECK (length(plan) <= 500),
    created_at        TEXT    NOT NULL @TS,
    replaced_at       TEXT    @TS,
    CHECK (replaced_at IS NULL OR replaced_at >= created_at)
) STRICT;
CREATE INDEX study_goal_statement_enrolment ON study_goal_statement (enrolment_id);
CREATE UNIQUE INDEX study_goal_statement_open ON study_goal_statement (enrolment_id) WHERE replaced_at IS NULL;

-- When the learner was shown their goals again (at most once a month) and what they did.
CREATE TABLE study_goal_review (
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    shown_at          TEXT    NOT NULL @TS,
    reason            TEXT    NOT NULL CHECK (reason IN ('month_start', 'checkpoint', 'return_after_break')),
    outcome           TEXT    NOT NULL CHECK (outcome IN ('kept', 'changed', 'dismissed')),
    PRIMARY KEY (enrolment_id, shown_at)
) STRICT, WITHOUT ROWID;

CREATE TABLE study_tour_progress (
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    tour_part_key     TEXT    NOT NULL REFERENCES study_tour_part,
    outcome           TEXT    NOT NULL CHECK (outcome IN ('completed', 'skipped')),
    at                TEXT    NOT NULL @TS,
    PRIMARY KEY (learner_id, tour_part_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX study_tour_progress_part ON study_tour_progress (tour_part_key);

-- Speaker, microphone and handwriting checks from the first run, per device kind.
CREATE TABLE study_device_check (
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    device_kind       TEXT    NOT NULL CHECK (device_kind IN ('desktop', 'tablet', 'phone')),
    check_kind        TEXT    NOT NULL CHECK (check_kind IN ('speaker', 'microphone', 'handwriting')),
    result            TEXT    NOT NULL CHECK (result IN ('ok', 'failed', 'skipped')),
    at                TEXT    NOT NULL @TS,
    PRIMARY KEY (learner_id, device_kind, check_kind)
) STRICT, WITHOUT ROWID;

CREATE TABLE study_session (
    session_id        INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    kind              TEXT    NOT NULL CHECK (kind IN ('today', 'lesson', 'review', 'practice', 'placement',
                                   'checkpoint', 'tour', 'library', 'conversation', 'together')),
    daily_plan_id     INTEGER REFERENCES study_daily_plan ON DELETE SET NULL,
    node_item_id      INTEGER REFERENCES catalogue_item,
    -- The pack version the session used (text, so the old version can still be deleted).
    pack_version      TEXT    NOT NULL,
    device_kind       TEXT    NOT NULL CHECK (device_kind IN ('desktop', 'tablet', 'phone')),
    started_at        TEXT    NOT NULL @TS,
    ended_at          TEXT    @TS,
    CHECK (ended_at IS NULL OR ended_at >= started_at)
) STRICT;
CREATE INDEX study_session_enrolment ON study_session (enrolment_id, started_at);
CREATE INDEX study_session_plan ON study_session (daily_plan_id);
CREATE INDEX study_session_node ON study_session (node_item_id);

CREATE TABLE study_placement (
    session_id        INTEGER PRIMARY KEY REFERENCES study_session ON DELETE CASCADE,
    outcome           TEXT    NOT NULL CHECK (outcome IN ('placed', 'skipped')),
    result_level      TEXT    @LEVEL,
    vocabulary_estimate INTEGER CHECK (vocabulary_estimate IS NULL OR vocabulary_estimate >= 0),
    start_node_item_id INTEGER REFERENCES catalogue_item,
    CHECK ((outcome = 'placed') = (start_node_item_id IS NOT NULL))
) STRICT;
CREATE INDEX study_placement_start ON study_placement (start_node_item_id);

-- Result of a stage checkpoint or level exam. A checkpoint does not block progress.
-- A learner who falls short is offered targeted practice.
CREATE TABLE study_checkpoint_result (
    session_id        INTEGER PRIMARY KEY REFERENCES study_session ON DELETE CASCADE,
    node_item_id      INTEGER NOT NULL REFERENCES catalogue_item,
    score             REAL    NOT NULL CHECK (score BETWEEN 0 AND 1),
    outcome           TEXT    NOT NULL CHECK (outcome IN ('met', 'practice_offered')),
    finished_at       TEXT    NOT NULL @TS
) STRICT;
CREATE INDEX study_checkpoint_result_node ON study_checkpoint_result (node_item_id);

-- Progress through the course tree. A node with no row has not been started.
CREATE TABLE study_node_progress (
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    node_item_id      INTEGER NOT NULL REFERENCES catalogue_item,
    status            TEXT    NOT NULL CHECK (status IN ('started', 'completed', 'skipped')),
    started_at        TEXT    NOT NULL @TS,
    completed_at      TEXT    @TS,
    PRIMARY KEY (enrolment_id, node_item_id),
    CHECK ((status = 'completed') = (completed_at IS NOT NULL))
) STRICT, WITHOUT ROWID;
CREATE INDEX study_node_progress_node ON study_node_progress (node_item_id);

-- Vandaag: one plan per enrolment per local day. mode, new_items_factor and offer are the
-- decision made when the plan was built, with the pack version whose settings were used.
CREATE TABLE study_daily_plan (
    daily_plan_id     INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    plan_day          TEXT    NOT NULL @DAY,
    built_at          TEXT    NOT NULL @TS,
    planned_minutes   INTEGER NOT NULL CHECK (planned_minutes > 0),
    review_minutes    INTEGER NOT NULL CHECK (review_minutes >= 0),
    mode              TEXT    NOT NULL CHECK (mode IN ('normal', 'reduced', 'review_only')),
    new_items_factor  REAL    NOT NULL DEFAULT 1.0 CHECK (new_items_factor > 0 AND new_items_factor <= 1),
    offer             TEXT    NOT NULL DEFAULT 'none' CHECK (offer IN ('none', 'review_first', 'earlier_lesson')),
    pack_version      TEXT    NOT NULL,
    lesson_item_id    INTEGER REFERENCES catalogue_item,
    extra_kind        TEXT    CHECK (extra_kind IN ('library', 'practice', 'unit_recap', 'conversation')),
    extra_ref         TEXT,
    extra_goal_key    TEXT    REFERENCES study_goal,   -- the goal the extra was chosen for, shown as the reason
    UNIQUE (enrolment_id, plan_day),
    CHECK (mode <> 'review_only' OR lesson_item_id IS NULL),
    CHECK ((mode = 'normal') = (new_items_factor = 1.0)),
    CHECK (mode = 'normal' OR extra_kind IS NULL OR extra_kind = 'unit_recap'),
    CHECK ((extra_kind IS NULL) = (extra_ref IS NULL)),
    CHECK (extra_goal_key IS NULL OR extra_kind IS NOT NULL)
) STRICT;
CREATE INDEX study_daily_plan_lesson ON study_daily_plan (lesson_item_id);
CREATE INDEX study_daily_plan_goal ON study_daily_plan (extra_goal_key);

-- Entries in a day's plan. Bridge items are held out of review for the warm-up. If the
-- lesson is not started, released_at is filled in and the items count as review again.
-- Reminders are for core items the learner has never met, so they have no card.
CREATE TABLE study_daily_plan_entry (
    daily_plan_id     INTEGER NOT NULL REFERENCES study_daily_plan ON DELETE CASCADE,
    entry_no          INTEGER NOT NULL CHECK (entry_no >= 1),
    section           TEXT    NOT NULL CHECK (section IN ('review', 'bridge', 'reminder')),
    card_id           INTEGER REFERENCES memory_card ON DELETE CASCADE,
    item_id           INTEGER REFERENCES catalogue_item,
    released_at       TEXT    @TS,
    done_at           TEXT    @TS,
    PRIMARY KEY (daily_plan_id, entry_no),
    CHECK ((section = 'reminder' AND card_id IS NULL AND item_id IS NOT NULL)
        OR (section <> 'reminder' AND card_id IS NOT NULL AND item_id IS NULL)),
    CHECK (released_at IS NULL OR section = 'bridge')
) STRICT, WITHOUT ROWID;
CREATE UNIQUE INDEX study_daily_plan_entry_card ON study_daily_plan_entry (daily_plan_id, card_id) WHERE card_id IS NOT NULL;
CREATE INDEX study_daily_plan_entry_card_id ON study_daily_plan_entry (card_id);
CREATE UNIQUE INDEX study_daily_plan_entry_item ON study_daily_plan_entry (daily_plan_id, item_id) WHERE item_id IS NOT NULL;
CREATE INDEX study_daily_plan_entry_item_id ON study_daily_plan_entry (item_id);

CREATE TABLE study_practice_run (
    session_id        INTEGER PRIMARY KEY REFERENCES study_session ON DELETE CASCADE,
    mode              TEXT    NOT NULL CHECK (mode IN ('single', 'mixed')),
    length_items      INTEGER NOT NULL CHECK (length_items BETWEEN 5 AND 200),
    source            TEXT    NOT NULL CHECK (source IN ('unit', 'known', 'lookups', 'hard'))
) STRICT;

CREATE TABLE study_practice_run_type (
    session_id        INTEGER NOT NULL REFERENCES study_practice_run ON DELETE CASCADE,
    activity_type     TEXT    NOT NULL REFERENCES catalogue_activity_type,
    PRIMARY KEY (session_id, activity_type)
) STRICT, WITHOUT ROWID;
CREATE INDEX study_practice_run_type_type ON study_practice_run_type (activity_type);

-- One answer to one item. The grade and the schedule change are in memory_review_log.
-- If there is no review row for an attempt, the schedule was not changed (for example after
-- a correct recognition answer in a mixed run). help_rung: 0 none, 1 tip, 2 step by step,
-- 3 answer shown. activity_type and direction are kept for generated exercises too.
CREATE TABLE study_attempt (
    attempt_id        INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    session_id        INTEGER NOT NULL REFERENCES study_session ON DELETE CASCADE,
    activity_item_id  INTEGER REFERENCES catalogue_item,
    activity_type     TEXT    NOT NULL REFERENCES catalogue_activity_type,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    direction         TEXT    NOT NULL CHECK (direction IN ('recognise', 'recall', 'say', 'spell', 'conjugate')),
    cell_key          TEXT,
    input_mode        TEXT    NOT NULL CHECK (input_mode IN ('typed', 'tapped', 'spoken', 'handwritten')),
    response          TEXT    CHECK (response IS NULL OR length(response) <= 4000),
    is_correct        INTEGER @BOOL,
    help_rung         INTEGER NOT NULL DEFAULT 0 CHECK (help_rung BETWEEN 0 AND 3),
    latency_ms        INTEGER CHECK (latency_ms IS NULL OR latency_ms >= 0),
    started_at        TEXT    NOT NULL @TS,
    answered_at       TEXT    NOT NULL @TS,
    CHECK (answered_at >= started_at)
) STRICT;
CREATE INDEX study_attempt_session ON study_attempt (session_id);
CREATE INDEX study_attempt_activity ON study_attempt (activity_item_id);
CREATE INDEX study_attempt_activity_type ON study_attempt (activity_type);
CREATE INDEX study_attempt_item ON study_attempt (item_id, answered_at);

-- Steps answered in Stap voor stap. The first wrong step is the one named in feedback.
CREATE TABLE study_help_step (
    attempt_id        INTEGER NOT NULL REFERENCES study_attempt ON DELETE CASCADE,
    position          INTEGER NOT NULL CHECK (position >= 1),
    step_item_id      INTEGER NOT NULL REFERENCES catalogue_item,
    is_correct        INTEGER NOT NULL @BOOL,
    PRIMARY KEY (attempt_id, position)
) STRICT, WITHOUT ROWID;
CREATE INDEX study_help_step_step ON study_help_step (step_item_id);

-- One row per time the learner listens in the listening step, with the text that was on screen.
CREATE TABLE study_listen (
    session_id        INTEGER NOT NULL REFERENCES study_session ON DELETE CASCADE,
    activity_item_id  INTEGER NOT NULL REFERENCES catalogue_item,
    listen_no         INTEGER NOT NULL CHECK (listen_no >= 1),
    speed             REAL    NOT NULL DEFAULT 1.0 CHECK (speed BETWEEN 0.5 AND 1.5),
    transcript        TEXT    NOT NULL CHECK (transcript IN ('none', 'transliteration', 'target', 'target_highlighted')),
    english           TEXT    NOT NULL CHECK (english IN ('off', 'per_line', 'all_lines', 'definitions')),
    text_shown_early  INTEGER NOT NULL DEFAULT 0 @BOOL,
    started_at        TEXT    NOT NULL @TS,
    PRIMARY KEY (session_id, activity_item_id, listen_no)
) STRICT, WITHOUT ROWID;
CREATE INDEX study_listen_activity ON study_listen (activity_item_id);

-- The guess at the start of the warm-up. option_no refers to the lesson's options in
-- the pack version that was active when the guess was made.
CREATE TABLE study_prediction_choice (
    session_id        INTEGER NOT NULL REFERENCES study_session ON DELETE CASCADE,
    lesson_item_id    INTEGER NOT NULL REFERENCES catalogue_item,
    option_no         INTEGER NOT NULL CHECK (option_no >= 0),
    chosen_at         TEXT    NOT NULL @TS,
    PRIMARY KEY (session_id, lesson_item_id, option_no)
) STRICT, WITHOUT ROWID;
CREATE INDEX study_prediction_choice_lesson ON study_prediction_choice (lesson_item_id);

-- Looked-up words and sentences, put into the next review (element key: lookups).
CREATE TABLE study_lookup (
    lookup_id         INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    session_id        INTEGER REFERENCES study_session ON DELETE SET NULL,
    item_id           INTEGER REFERENCES catalogue_item,
    query_text        TEXT    CHECK (query_text IS NULL OR length(query_text) BETWEEN 1 AND 300),
    source            TEXT    NOT NULL CHECK (source IN ('en_mark', 'word_card', 'dictionary', 'library')),
    looked_up_at      TEXT    NOT NULL @TS,
    reviewed_at       TEXT    @TS,
    CHECK (item_id IS NOT NULL OR query_text IS NOT NULL)
) STRICT;
CREATE INDEX study_lookup_enrolment_open ON study_lookup (enrolment_id, looked_up_at) WHERE reviewed_at IS NULL;
CREATE INDEX study_lookup_enrolment ON study_lookup (enrolment_id);
CREATE INDEX study_lookup_session ON study_lookup (session_id);
CREATE INDEX study_lookup_item ON study_lookup (item_id);

-- Handover of one task to the phone by QR code. The code is valid for 10 minutes at most.
CREATE TABLE study_handover (
    handover_id       INTEGER PRIMARY KEY,
    session_id        INTEGER NOT NULL REFERENCES study_session ON DELETE CASCADE,
    activity_item_id  INTEGER NOT NULL REFERENCES catalogue_item,
    token_hash        BLOB    NOT NULL UNIQUE CHECK (length(token_hash) = 32),
    created_at        TEXT    NOT NULL @TS,
    expires_at        TEXT    NOT NULL @TS,
    claimed_at        TEXT    @TS,
    claimed_by_auth_session_id INTEGER REFERENCES identity_auth_session ON DELETE SET NULL,
    CHECK (expires_at > created_at),
    CHECK (julianday(expires_at) - julianday(created_at) <= 10.0 / 1440 + 0.000001),
    CHECK ((claimed_at IS NULL) = (claimed_by_auth_session_id IS NULL))
) STRICT;
CREATE INDEX study_handover_claimed_by ON study_handover (claimed_by_auth_session_id);
CREATE INDEX study_handover_session ON study_handover (session_id);
CREATE INDEX study_handover_activity ON study_handover (activity_item_id);
CREATE INDEX study_handover_expires ON study_handover (expires_at);

CREATE TABLE study_notebook_entry (
    entry_id          INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    item_id           INTEGER REFERENCES catalogue_item,
    kind              TEXT    NOT NULL DEFAULT 'note' CHECK (kind IN ('note', 'own_example', 'mnemonic')),
    body_md           TEXT    NOT NULL CHECK (length(body_md) BETWEEN 1 AND 20000),
    created_at        TEXT    NOT NULL @TS,
    updated_at        TEXT    NOT NULL @TS
) STRICT;
CREATE INDEX study_notebook_entry_enrolment ON study_notebook_entry (enrolment_id);
CREATE INDEX study_notebook_entry_item ON study_notebook_entry (item_id);

CREATE VIRTUAL TABLE study_notebook_fts USING fts5 (
    body_md, content = 'study_notebook_entry', content_rowid = 'entry_id',
    tokenize = 'unicode61 remove_diacritics 2'
);

-- =====================================================================
-- memory: FSRS cards, parameters and the review log
-- =====================================================================

-- FSRS-6 parameters fitted to one learner's reviews in one course.
CREATE TABLE memory_fsrs_parameters (
    enrolment_id      INTEGER PRIMARY KEY REFERENCES study_enrolment ON DELETE CASCADE,
    weights           TEXT    NOT NULL CHECK (json_valid(weights) AND json_type(weights) = 'array' AND json_array_length(weights) = 21),
    desired_retention REAL    NOT NULL DEFAULT 0.90 CHECK (desired_retention BETWEEN 0.70 AND 0.97),
    fitted_at         TEXT    @TS,
    reviews_at_fit    INTEGER NOT NULL DEFAULT 0 CHECK (reviews_at_fit >= 0)
) STRICT;

-- One card per learner, item, direction and (for conjugation) form type. A card made offline
-- is matched on this natural key when the queue is replayed.
-- The FSRS columns are the result of replaying the card's review log (see the data model document).
-- A card whose item is not in the active pack version is left out of the queue through
-- catalogue_item_live; suspended_at is for the learner's own choice.
CREATE TABLE memory_card (
    card_id           INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    item_id           INTEGER NOT NULL REFERENCES catalogue_item,
    direction         TEXT    NOT NULL CHECK (direction IN ('recognise', 'recall', 'say', 'spell', 'conjugate')),
    form_type         TEXT    NOT NULL DEFAULT '' CHECK (form_type NOT GLOB '*[^a-z_]*'),
    state             TEXT    NOT NULL DEFAULT 'new' CHECK (state IN ('new', 'learning', 'review', 'relearning')),
    due_at            TEXT    @TS,
    stability         REAL    CHECK (stability IS NULL OR stability > 0),
    difficulty        REAL    CHECK (difficulty IS NULL OR difficulty BETWEEN 1 AND 10),
    learning_step     INTEGER NOT NULL DEFAULT 0 CHECK (learning_step >= 0),
    reps              INTEGER NOT NULL DEFAULT 0 CHECK (reps >= 0),
    lapses            INTEGER NOT NULL DEFAULT 0 CHECK (lapses >= 0),
    last_review_at    TEXT    @TS,
    suspended_at      TEXT    @TS,
    created_at        TEXT    NOT NULL @TS,
    UNIQUE (enrolment_id, item_id, direction, form_type),
    CHECK ((direction = 'conjugate') = (form_type <> '')),
    CHECK ((state = 'new') = (due_at IS NULL)),
    CHECK ((state = 'new') = (stability IS NULL)),
    CHECK ((state = 'new') = (last_review_at IS NULL)),
    CHECK (lapses <= reps)
) STRICT;
CREATE INDEX memory_card_due ON memory_card (enrolment_id, due_at) WHERE suspended_at IS NULL AND state <> 'new';
CREATE INDEX memory_card_item ON memory_card (item_id);

-- Rows can be added but not changed. The facts in a row are the grade and when and how it was
-- given. A changed grade is a new row (grade_source 'override') with corrects_review_id; it
-- has the reviewed_at, review_day, context and state_before of the row it corrects, so it
-- takes that row's place when the log is replayed. The card's state is worked out by
-- replaying, in reviewed_at order, the rows that no later row corrects.
-- state_before is the card state the scheduler saw when the answer was given. It is not
-- changed on replay; it is kept because a lapse is an Again on a card in review.
-- grade: 1 Again, 2 Hard, 3 Good, 4 Easy.
CREATE TABLE memory_review_log (
    review_id         INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    card_id           INTEGER NOT NULL REFERENCES memory_card ON DELETE CASCADE,
    attempt_id        INTEGER REFERENCES study_attempt ON DELETE SET NULL,
    context           TEXT    NOT NULL CHECK (context IN ('review', 'lesson', 'warmup', 'practice_mixed',
                                   'practice_single', 'placement', 'checkpoint', 'import')),
    grade             INTEGER NOT NULL CHECK (grade BETWEEN 1 AND 4),
    grade_source      TEXT    NOT NULL CHECK (grade_source IN ('auto', 'self', 'step_by_step', 'override')),
    state_before      TEXT    NOT NULL CHECK (state_before IN ('new', 'learning', 'review', 'relearning')),
    reviewed_at       TEXT    NOT NULL @TS,
    review_day        TEXT    NOT NULL @DAY,
    recorded_at       TEXT    NOT NULL @TS,
    corrects_review_id INTEGER UNIQUE REFERENCES memory_review_log,
    CHECK (grade_source <> 'step_by_step' OR grade IN (1, 2)),
    CHECK ((grade_source = 'override') = (corrects_review_id IS NOT NULL)),
    CHECK (recorded_at >= reviewed_at)
) STRICT;
CREATE INDEX memory_review_log_card ON memory_review_log (card_id, reviewed_at);
CREATE INDEX memory_review_log_attempt ON memory_review_log (attempt_id);
-- For the mixed-run limit per item and day (mix_updates_per_item_per_day), which the
-- engine checks before it writes: see mixed_run_updates_today in queries.sql.
CREATE INDEX memory_review_log_day ON memory_review_log (review_day, context);

-- =====================================================================
-- checking: feedback on answers
-- =====================================================================

CREATE TABLE checking_feedback (
    attempt_id        INTEGER NOT NULL REFERENCES study_attempt ON DELETE CASCADE,
    position          INTEGER NOT NULL CHECK (position >= 1),
    layer             TEXT    NOT NULL CHECK (layer IN ('accepted_answer', 'pack_rule', 'languagetool', 'ai')),
    error_type        TEXT    REFERENCES catalogue_error_type,
    code              TEXT,
    rule_item_id      INTEGER REFERENCES catalogue_item,
    step_item_id      INTEGER REFERENCES catalogue_item,
    span_start        INTEGER CHECK (span_start IS NULL OR span_start >= 0),
    span_end          INTEGER,
    message_en        TEXT    NOT NULL,
    message_tl        TEXT,
    suggestion        TEXT,
    PRIMARY KEY (attempt_id, position),
    CHECK ((span_start IS NULL) = (span_end IS NULL)),
    CHECK (span_end IS NULL OR span_end >= span_start)
) STRICT;
CREATE INDEX checking_feedback_rule ON checking_feedback (rule_item_id);
CREATE INDEX checking_feedback_step ON checking_feedback (step_item_id);
CREATE INDEX checking_feedback_error_type ON checking_feedback (error_type);

-- =====================================================================
-- mastery: estimates per can-do and component
-- =====================================================================

-- ability is on the logit scale of the logistic model. It can be worked out again from attempts.
CREATE TABLE mastery_estimate (
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    can_do_item_id    INTEGER NOT NULL REFERENCES catalogue_item,
    component         TEXT    NOT NULL CHECK (component IN ('vocabulary', 'grammar', 'pronunciation', 'spelling',
                                   'pragmatics', 'sociocultural', 'fluency', 'comprehension')),
    ability           REAL    NOT NULL CHECK (ability BETWEEN -10 AND 10),
    standard_error    REAL    NOT NULL CHECK (standard_error > 0),
    evidence_count    INTEGER NOT NULL CHECK (evidence_count >= 0),
    updated_at        TEXT    NOT NULL @TS,
    PRIMARY KEY (enrolment_id, can_do_item_id, component)
) STRICT, WITHOUT ROWID;
CREATE INDEX mastery_estimate_can_do ON mastery_estimate (can_do_item_id);

-- Can-do self-assessment (European Language Portfolio style).
CREATE TABLE mastery_self_assessment (
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    can_do_item_id    INTEGER NOT NULL REFERENCES catalogue_item,
    rating            TEXT    NOT NULL CHECK (rating IN ('not_yet', 'with_help', 'yes')),
    at                TEXT    NOT NULL @TS,
    PRIMARY KEY (enrolment_id, can_do_item_id, at)
) STRICT, WITHOUT ROWID;
CREATE INDEX mastery_self_assessment_can_do ON mastery_self_assessment (can_do_item_id);

-- =====================================================================
-- speech: recordings (kept 30 days) and pronunciation results
-- =====================================================================

-- The audio file is stored on disk under its sha256. The row and the file are deleted
-- together after delete_after.
CREATE TABLE speech_recording (
    recording_id      INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    purpose           TEXT    NOT NULL CHECK (purpose IN ('attempt', 'conversation', 'shadowing', 'device_check', 'together')),
    attempt_id        INTEGER REFERENCES study_attempt ON DELETE SET NULL,
    sha256            TEXT    NOT NULL UNIQUE @SHA,
    mime              TEXT    NOT NULL CHECK (mime IN ('audio/ogg', 'audio/webm', 'audio/mp4', 'audio/wav')),
    duration_ms       INTEGER NOT NULL CHECK (duration_ms > 0),
    recorded_at       TEXT    NOT NULL @TS,
    delete_after      TEXT    NOT NULL @TS,
    CHECK (delete_after > recorded_at),
    CHECK (julianday(delete_after) - julianday(recorded_at) <= 30.0001)
) STRICT;
CREATE INDEX speech_recording_learner ON speech_recording (learner_id);
CREATE INDEX speech_recording_attempt ON speech_recording (attempt_id);
CREATE INDEX speech_recording_delete_after ON speech_recording (delete_after);

CREATE TABLE speech_assessment (
    recording_id      INTEGER PRIMARY KEY REFERENCES speech_recording ON DELETE CASCADE,
    asr_text          TEXT,
    asr_model         TEXT    NOT NULL,
    overall           REAL    CHECK (overall IS NULL OR overall BETWEEN 0 AND 1),
    assessed_at       TEXT    NOT NULL @TS
) STRICT;

CREATE TABLE speech_phone_score (
    recording_id      INTEGER NOT NULL REFERENCES speech_assessment ON DELETE CASCADE,
    position          INTEGER NOT NULL CHECK (position >= 1),
    expected_ipa      TEXT    NOT NULL,
    heard_ipa         TEXT,
    score             REAL    NOT NULL CHECK (score BETWEEN 0 AND 1),
    start_ms          INTEGER NOT NULL CHECK (start_ms >= 0),
    end_ms            INTEGER NOT NULL,
    error_type        TEXT    REFERENCES catalogue_error_type,
    PRIMARY KEY (recording_id, position),
    CHECK (end_ms > start_ms)
) STRICT, WITHOUT ROWID;
CREATE INDEX speech_phone_score_error_type ON speech_phone_score (error_type);

-- =====================================================================
-- ai: conversations (kept 30 days) and a log of model calls without content
-- =====================================================================

CREATE TABLE ai_conversation (
    conversation_id   INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    session_id        INTEGER NOT NULL REFERENCES study_session ON DELETE CASCADE,
    scenario_item_id  INTEGER REFERENCES catalogue_item,
    started_at        TEXT    NOT NULL @TS,
    ended_at          TEXT    @TS,
    delete_after      TEXT    NOT NULL @TS,
    CHECK (julianday(delete_after) - julianday(started_at) <= 30.0001)
) STRICT;
CREATE INDEX ai_conversation_session ON ai_conversation (session_id);
CREATE INDEX ai_conversation_scenario ON ai_conversation (scenario_item_id);
CREATE INDEX ai_conversation_delete_after ON ai_conversation (delete_after);

CREATE TABLE ai_turn (
    conversation_id   INTEGER NOT NULL REFERENCES ai_conversation ON DELETE CASCADE,
    turn_no           INTEGER NOT NULL CHECK (turn_no >= 1),
    speaker           TEXT    NOT NULL CHECK (speaker IN ('learner', 'partner')),
    text_tl           TEXT    NOT NULL,
    text_en           TEXT,
    recording_id      INTEGER REFERENCES speech_recording ON DELETE SET NULL,
    created_at        TEXT    NOT NULL @TS,
    PRIMARY KEY (conversation_id, turn_no)
) STRICT;
CREATE INDEX ai_turn_recording ON ai_turn (recording_id);

-- Prices of hosted models, in micro-dollars (millionths of a US dollar) per million tokens,
-- as the provider bills them. A model with prices that depend on prompt size (Haiku 5.5
-- above 100,000 tokens) has one row per tier. Old prices are kept, so past costs stay right.
CREATE TABLE ai_price (
    ai_price_id       INTEGER PRIMARY KEY,
    provider          TEXT    NOT NULL CHECK (provider IN ('anthropic', 'mistral', 'local')),
    model             TEXT    NOT NULL CHECK (length(model) BETWEEN 1 AND 100),
    min_prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (min_prompt_tokens >= 0),
    input             INTEGER NOT NULL CHECK (input >= 0),
    output            INTEGER NOT NULL CHECK (output >= 0),
    cache_write_5m    INTEGER NOT NULL CHECK (cache_write_5m >= 0),
    cache_write_1h    INTEGER NOT NULL CHECK (cache_write_1h >= 0),
    cache_read        INTEGER NOT NULL CHECK (cache_read >= 0),
    valid_from        TEXT    NOT NULL @DAY,
    valid_to          TEXT    @DAY,
    source_url        TEXT,
    UNIQUE (provider, model, min_prompt_tokens, valid_from),
    CHECK (valid_to IS NULL OR valid_to > valid_from)
) STRICT;

-- Spending limits, applied by Franca before each call (decision of 21 November 2026).
-- 'learning' covers calls made while learners study; 'content' covers pack-building jobs.
-- A new row replaces the limit from valid_from on; earlier rows are kept as history.
CREATE TABLE ai_budget (
    ai_budget_id      INTEGER PRIMARY KEY,
    category          TEXT    NOT NULL CHECK (category IN ('learning', 'content')),
    monthly_limit_microusd INTEGER NOT NULL CHECK (monthly_limit_microusd > 0),
    learner_daily_limit_microusd INTEGER CHECK (learner_daily_limit_microusd IS NULL OR learner_daily_limit_microusd > 0),
    warn_share_first  REAL    NOT NULL DEFAULT 0.5 CHECK (warn_share_first > 0 AND warn_share_first < 1),
    warn_share_second REAL    NOT NULL DEFAULT 0.8 CHECK (warn_share_second > 0 AND warn_share_second < 1),
    valid_from        TEXT    NOT NULL @TS,
    changed_by_learner_id INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    UNIQUE (category, valid_from),
    CHECK (warn_share_first < warn_share_second),
    CHECK (category = 'learning' OR learner_daily_limit_microusd IS NULL)
) STRICT;
CREATE INDEX ai_budget_changed_by ON ai_budget (changed_by_learner_id);

-- Usage of hosted model calls: tokens, outcome and time. No prompts, answers or learner text.
-- Kept one year. outcome 'over_limit' means Franca's own limiter refused the call before it was sent.
CREATE TABLE ai_request (
    ai_request_id     INTEGER PRIMARY KEY,
    learner_id        INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    category          TEXT    NOT NULL CHECK (category IN ('learning', 'content')),
    purpose           TEXT    NOT NULL CHECK (purpose IN ('feedback', 'conversation', 'handwriting', 'explanation',
                                   'speech_recognition', 'content_generation', 'translation', 'classification')),
    ai_price_id       INTEGER REFERENCES ai_price,
    input_tokens      INTEGER NOT NULL DEFAULT 0 CHECK (input_tokens >= 0),
    cache_write_5m_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cache_write_5m_tokens >= 0),
    cache_write_1h_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cache_write_1h_tokens >= 0),
    cache_read_tokens INTEGER NOT NULL DEFAULT 0 CHECK (cache_read_tokens >= 0),
    output_tokens     INTEGER NOT NULL DEFAULT 0 CHECK (output_tokens >= 0),
    estimated_microusd INTEGER NOT NULL DEFAULT 0 CHECK (estimated_microusd >= 0),
    -- pending: written with the estimate, inside BEGIN IMMEDIATE, before the call is sent, and
    -- updated when the call ends. Pending rows count at their estimate, so calls still running
    -- are counted by every worker process, and a call lost in a crash is still counted.
    outcome           TEXT    NOT NULL CHECK (outcome IN ('pending', 'ok', 'error', 'refused', 'timeout', 'over_limit')),
    latency_ms        INTEGER CHECK (latency_ms >= 0),
    at                TEXT    NOT NULL @TS,
    CHECK (outcome <> 'over_limit' OR (input_tokens = 0 AND output_tokens = 0 AND cache_read_tokens = 0
                                       AND cache_write_5m_tokens = 0 AND cache_write_1h_tokens = 0)),
    CHECK (outcome IN ('over_limit', 'error', 'timeout') OR ai_price_id IS NOT NULL),
    CHECK ((outcome = 'pending') = (latency_ms IS NULL))
) STRICT;
-- A learning call is made for a learner. Checked at insert only, so that deleting a learner
-- (which sets learner_id to NULL) keeps the spending record.
CREATE TRIGGER ai_request_learning_has_learner BEFORE INSERT ON ai_request
WHEN NEW.category = 'learning' AND NEW.learner_id IS NULL AND NEW.outcome <> 'over_limit'
BEGIN
    SELECT RAISE(ABORT, 'a learning call needs a learner');
END;
CREATE INDEX ai_request_learner ON ai_request (learner_id, at);
CREATE INDEX ai_request_at ON ai_request (category, at);
CREATE INDEX ai_request_price ON ai_request (ai_price_id);

-- Warnings sent to the owner, so each level is sent once per category and month.
CREATE TABLE ai_budget_alert (
    category          TEXT    NOT NULL CHECK (category IN ('learning', 'content')),
    month             TEXT    NOT NULL CHECK (month GLOB '[0-9][0-9][0-9][0-9]-[01][0-9]'),
    level             TEXT    NOT NULL CHECK (level IN ('first_warning', 'second_warning', 'limit_reached')),
    sent_at           TEXT    NOT NULL @TS,
    PRIMARY KEY (category, month, level)
) STRICT, WITHOUT ROWID;

-- =====================================================================
-- partner: Samen
-- =====================================================================

-- What one learner lets the other see. If there is no row for a scope, it is not shared.
CREATE TABLE partner_share (
    owner_learner_id  INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    viewer_learner_id INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    scope             TEXT    NOT NULL CHECK (scope IN ('lessons', 'words', 'game_results')),
    granted_at        TEXT    NOT NULL @TS,
    PRIMARY KEY (owner_learner_id, viewer_learner_id, pack_id, scope),
    CHECK (owner_learner_id <> viewer_learner_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX partner_share_viewer ON partner_share (viewer_learner_id);
CREATE INDEX partner_share_pack ON partner_share (pack_id);

-- A role-play done together. Each learner's part is linked to their own session.
CREATE TABLE partner_roleplay (
    roleplay_id       INTEGER PRIMARY KEY,
    uuid              TEXT    NOT NULL UNIQUE @UUID,
    scenario_item_id  INTEGER NOT NULL REFERENCES catalogue_item,
    setup             TEXT    NOT NULL CHECK (setup IN ('one_screen', 'two_devices', 'print')),
    started_at        TEXT    NOT NULL @TS
) STRICT;
CREATE INDEX partner_roleplay_scenario ON partner_roleplay (scenario_item_id);

CREATE TABLE partner_roleplay_member (
    roleplay_id       INTEGER NOT NULL REFERENCES partner_roleplay ON DELETE CASCADE,
    session_id        INTEGER NOT NULL REFERENCES study_session ON DELETE CASCADE,
    role              TEXT    NOT NULL CHECK (role IN ('a', 'b')),
    PRIMARY KEY (roleplay_id, role),
    UNIQUE (roleplay_id, session_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX partner_roleplay_member_session ON partner_roleplay_member (session_id);

-- A learner's comments on the other learner's capstone task or recording.
CREATE TABLE partner_review (
    partner_review_id INTEGER PRIMARY KEY,
    attempt_id        INTEGER NOT NULL REFERENCES study_attempt ON DELETE CASCADE,
    reviewer_learner_id INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    body              TEXT    NOT NULL CHECK (length(body) BETWEEN 1 AND 4000),
    created_at        TEXT    NOT NULL @TS
) STRICT;
CREATE INDEX partner_review_attempt ON partner_review (attempt_id);
CREATE INDEX partner_review_reviewer ON partner_review (reviewer_learner_id);

-- =====================================================================
-- library: the household's private library and word tracking (Lute model)
-- =====================================================================

CREATE TABLE library_item (
    library_item_id   INTEGER PRIMARY KEY,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    title             TEXT    NOT NULL,
    author            TEXT,
    kind              TEXT    NOT NULL CHECK (kind IN ('book', 'story', 'article', 'video', 'audio', 'podcast')),
    level_estimate    TEXT    @LEVEL,
    media_sha256      TEXT    REFERENCES catalogue_media_asset,
    licence_code      TEXT    NOT NULL REFERENCES catalogue_licence,
    rights_scope      TEXT    NOT NULL DEFAULT 'private' CHECK (rights_scope IN ('private', 'shareable')),
    source_note       TEXT,
    added_by_learner_id INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    added_at          TEXT    NOT NULL @TS
) STRICT;
CREATE INDEX library_item_pack ON library_item (pack_id);
CREATE INDEX library_item_media ON library_item (media_sha256);
CREATE INDEX library_item_licence ON library_item (licence_code);
CREATE INDEX library_item_added_by ON library_item (added_by_learner_id);

-- Goals a library item suits, used to weight suggestions. At least half of what is suggested
-- stays general.
CREATE TABLE library_item_goal (
    library_item_id   INTEGER NOT NULL REFERENCES library_item ON DELETE CASCADE,
    goal_key          TEXT    NOT NULL REFERENCES study_goal,
    PRIMARY KEY (library_item_id, goal_key)
) STRICT, WITHOUT ROWID;
CREATE INDEX library_item_goal_goal ON library_item_goal (goal_key);

CREATE TABLE library_section (
    section_id        INTEGER PRIMARY KEY,
    library_item_id   INTEGER NOT NULL REFERENCES library_item ON DELETE CASCADE,
    section_no        INTEGER NOT NULL CHECK (section_no >= 1),
    title             TEXT,
    body_text         TEXT    NOT NULL,
    word_count        INTEGER NOT NULL CHECK (word_count >= 0),
    start_ms          INTEGER CHECK (start_ms IS NULL OR start_ms >= 0),
    end_ms            INTEGER,
    UNIQUE (library_item_id, section_no),
    CHECK (end_ms IS NULL OR end_ms > start_ms)
) STRICT;

CREATE VIRTUAL TABLE library_fts USING fts5 (
    body_text, content = 'library_section', content_rowid = 'section_id',
    tokenize = 'unicode61 remove_diacritics 2'
);

CREATE TABLE library_caption_track (
    library_item_id   INTEGER NOT NULL REFERENCES library_item ON DELETE CASCADE,
    language          TEXT    NOT NULL CHECK (language GLOB '[a-z][a-z]*'),
    vtt_sha256        TEXT    NOT NULL REFERENCES catalogue_media_asset,
    PRIMARY KEY (library_item_id, language)
) STRICT, WITHOUT ROWID;
CREATE INDEX library_caption_track_vtt ON library_caption_track (vtt_sha256);

CREATE TABLE library_progress (
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    library_item_id   INTEGER NOT NULL REFERENCES library_item ON DELETE CASCADE,
    section_no        INTEGER NOT NULL CHECK (section_no >= 1),
    position          INTEGER NOT NULL DEFAULT 0 CHECK (position >= 0),
    updated_at        TEXT    NOT NULL @TS,
    finished_at       TEXT    @TS,
    PRIMARY KEY (enrolment_id, library_item_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX library_progress_item ON library_progress (library_item_id);

-- Word statuses as in Lute: 1 to 5 learning, 98 ignored, 99 well known.
-- text_norm is NFC and case-folded. A term with no pack item is a word met only in the library.
CREATE TABLE library_term (
    term_id           INTEGER PRIMARY KEY,
    enrolment_id      INTEGER NOT NULL REFERENCES study_enrolment ON DELETE CASCADE,
    text              TEXT    NOT NULL CHECK (length(text) BETWEEN 1 AND 200),
    text_norm         TEXT    NOT NULL CHECK (length(text_norm) BETWEEN 1 AND 200),
    word_count        INTEGER NOT NULL DEFAULT 1 CHECK (word_count BETWEEN 1 AND 15),
    status            INTEGER NOT NULL CHECK (status IN (1, 2, 3, 4, 5, 98, 99)),
    translation       TEXT,
    romanisation      TEXT,
    item_id           INTEGER REFERENCES catalogue_item,
    created_at        TEXT    NOT NULL @TS,
    status_changed_at TEXT    NOT NULL @TS,
    UNIQUE (enrolment_id, text_norm)
) STRICT;
CREATE INDEX library_term_item ON library_term (item_id);

CREATE TABLE library_term_parent (
    term_id           INTEGER NOT NULL REFERENCES library_term ON DELETE CASCADE,
    parent_term_id    INTEGER NOT NULL REFERENCES library_term ON DELETE CASCADE,
    PRIMARY KEY (term_id, parent_term_id),
    CHECK (term_id <> parent_term_id)
) STRICT, WITHOUT ROWID;
CREATE INDEX library_term_parent_parent ON library_term_parent (parent_term_id);

-- =====================================================================
-- studio: the owner's review queue (Te controleren)
-- =====================================================================

CREATE TABLE studio_review_task (
    review_task_id    INTEGER PRIMARY KEY,
    pack_id           INTEGER NOT NULL REFERENCES catalogue_pack,
    item_id           INTEGER REFERENCES catalogue_item,
    kind              TEXT    NOT NULL CHECK (kind IN ('native_check', 'learner_report', 'generated_content', 'rights')),
    status            TEXT    NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'accepted', 'changed', 'rejected', 'deferred')),
    summary           TEXT    NOT NULL CHECK (length(summary) BETWEEN 1 AND 300),
    detail            TEXT,
    attempt_id        INTEGER REFERENCES study_attempt ON DELETE SET NULL,
    raised_by_learner_id INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    raised_at         TEXT    NOT NULL @TS,
    resolved_by_learner_id INTEGER REFERENCES identity_learner ON DELETE SET NULL,
    resolved_at       TEXT    @TS,
    resolution_note   TEXT,
    CHECK ((status IN ('open', 'deferred')) = (resolved_at IS NULL))
) STRICT;
CREATE INDEX studio_review_task_open ON studio_review_task (pack_id, status) WHERE status IN ('open', 'deferred');
CREATE INDEX studio_review_task_pack ON studio_review_task (pack_id);
CREATE INDEX studio_review_task_item ON studio_review_task (item_id);
CREATE INDEX studio_review_task_attempt ON studio_review_task (attempt_id);
CREATE INDEX studio_review_task_raised_by ON studio_review_task (raised_by_learner_id);
CREATE INDEX studio_review_task_resolved_by ON studio_review_task (resolved_by_learner_id);

-- =====================================================================
-- records: xAPI statements waiting to be exported (outbox)
-- =====================================================================

CREATE TABLE records_xapi_statement (
    statement_uuid    TEXT    PRIMARY KEY @UUID,
    learner_id        INTEGER NOT NULL REFERENCES identity_learner ON DELETE CASCADE,
    attempt_id        INTEGER REFERENCES study_attempt ON DELETE SET NULL,
    verb_iri          TEXT    NOT NULL CHECK (verb_iri LIKE 'http%'),
    statement_json    TEXT    NOT NULL CHECK (json_valid(statement_json)),
    stored_at         TEXT    NOT NULL @TS,
    exported_at       TEXT    @TS
) STRICT, WITHOUT ROWID;
CREATE INDEX records_xapi_statement_learner ON records_xapi_statement (learner_id);
CREATE INDEX records_xapi_statement_attempt ON records_xapi_statement (attempt_id);
CREATE INDEX records_xapi_statement_unsent ON records_xapi_statement (stored_at) WHERE exported_at IS NULL;

-- @GENERATED (the generated views and triggers are inserted here by build_schema.py)

-- =====================================================================
-- Hand-written triggers and views
-- =====================================================================

-- Items cannot be deleted, because learner data is linked to them.
CREATE TRIGGER catalogue_item_no_delete BEFORE DELETE ON catalogue_item
BEGIN
    SELECT RAISE(ABORT, 'catalogue_item rows are retired, not deleted');
END;

-- The active version has to be retired before it can be deleted.
CREATE TRIGGER catalogue_pack_version_no_delete_active BEFORE DELETE ON catalogue_pack_version
WHEN OLD.status = 'active'
BEGIN
    SELECT RAISE(ABORT, 'retire a pack version before deleting it');
END;

-- The review log cannot be changed. The one exception is attempt_id, which is cleared when
-- its attempt is deleted (ON DELETE SET NULL is carried out as an update).
CREATE TRIGGER memory_review_log_no_update BEFORE UPDATE OF review_id, uuid, card_id, context, grade,
    grade_source, state_before, reviewed_at, review_day, recorded_at, corrects_review_id ON memory_review_log
BEGIN
    SELECT RAISE(ABORT, 'memory_review_log is append-only; add a correcting row instead');
END;

CREATE TRIGGER memory_review_log_attempt_only_cleared BEFORE UPDATE OF attempt_id ON memory_review_log
WHEN NEW.attempt_id IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'memory_review_log is append-only; add a correcting row instead');
END;

-- Rows are deleted only together with their card (or the card's learner).
CREATE TRIGGER memory_review_log_no_delete BEFORE DELETE ON memory_review_log
WHEN EXISTS (SELECT 1 FROM memory_card WHERE card_id = OLD.card_id)
BEGIN
    SELECT RAISE(ABORT, 'memory_review_log rows are deleted only with their card');
END;

-- A correcting row belongs to the same card and takes the corrected row's place in time.
CREATE TRIGGER memory_review_log_correction_matches BEFORE INSERT ON memory_review_log
WHEN NEW.corrects_review_id IS NOT NULL
 AND NOT EXISTS (SELECT 1 FROM memory_review_log o
                 WHERE o.review_id = NEW.corrects_review_id AND o.card_id = NEW.card_id
                   AND o.reviewed_at = NEW.reviewed_at AND o.review_day = NEW.review_day
                   AND o.context = NEW.context AND o.state_before = NEW.state_before)
BEGIN
    SELECT RAISE(ABORT, 'a correcting review must match the card, time, context and state of the review it corrects');
END;

-- A grade reached with Stap voor stap stays Hard or Again: it cannot be corrected
-- (decision of 11 November 2026). The link to change a grade is not shown for these answers.
CREATE TRIGGER memory_review_log_step_by_step_final BEFORE INSERT ON memory_review_log
WHEN NEW.corrects_review_id IS NOT NULL
 AND (SELECT grade_source FROM memory_review_log WHERE review_id = NEW.corrects_review_id) = 'step_by_step'
BEGIN
    SELECT RAISE(ABORT, 'a grade reached with Stap voor stap cannot be changed');
END;

-- A card belongs to an item of the enrolment's pack, of a kind that can be learned and reviewed.
CREATE TRIGGER memory_card_item_insert BEFORE INSERT ON memory_card
WHEN (SELECT pack_id FROM catalogue_item WHERE item_id = NEW.item_id)
     IS NOT (SELECT pack_id FROM study_enrolment WHERE enrolment_id = NEW.enrolment_id)
  OR (SELECT kind FROM catalogue_item WHERE item_id = NEW.item_id) NOT IN
     ('lexeme', 'sense', 'chunk', 'grammar_point', 'rule', 'rule_step', 'sound', 'sound_contrast')
BEGIN
    SELECT RAISE(ABORT, 'a card must be for a learnable item of the enrolment''s pack');
END;

CREATE TRIGGER memory_card_item_update BEFORE UPDATE OF item_id, enrolment_id ON memory_card
WHEN (SELECT pack_id FROM catalogue_item WHERE item_id = NEW.item_id)
     IS NOT (SELECT pack_id FROM study_enrolment WHERE enrolment_id = NEW.enrolment_id)
  OR (SELECT kind FROM catalogue_item WHERE item_id = NEW.item_id) NOT IN
     ('lexeme', 'sense', 'chunk', 'grammar_point', 'rule', 'rule_step', 'sound', 'sound_contrast')
BEGIN
    SELECT RAISE(ABORT, 'a card must be for a learnable item of the enrolment''s pack');
END;

-- A chosen subject module is a course node of the enrolment's pack, and a personal can-do is a
-- can-do of that pack.
CREATE TRIGGER study_enrolment_module_item BEFORE INSERT ON study_enrolment_module
WHEN (SELECT pack_id FROM catalogue_item WHERE item_id = NEW.module_item_id)
     IS NOT (SELECT pack_id FROM study_enrolment WHERE enrolment_id = NEW.enrolment_id)
  OR (SELECT kind FROM catalogue_item WHERE item_id = NEW.module_item_id) IS NOT 'course_node'
BEGIN
    SELECT RAISE(ABORT, 'a chosen module must be a course node of the enrolment''s pack');
END;

CREATE TRIGGER study_personal_can_do_item BEFORE INSERT ON study_personal_can_do
WHEN (SELECT pack_id FROM catalogue_item WHERE item_id = NEW.can_do_item_id)
     IS NOT (SELECT pack_id FROM study_enrolment WHERE enrolment_id = NEW.enrolment_id)
  OR (SELECT kind FROM catalogue_item WHERE item_id = NEW.can_do_item_id) IS NOT 'can_do'
BEGIN
    SELECT RAISE(ABORT, 'a personal can-do must be a can-do of the enrolment''s pack');
END;

-- Links between learner rows stay within one learner's course.
CREATE TRIGGER study_daily_plan_entry_same_enrolment BEFORE INSERT ON study_daily_plan_entry
WHEN NEW.card_id IS NOT NULL
 AND (SELECT enrolment_id FROM memory_card WHERE card_id = NEW.card_id)
     IS NOT (SELECT enrolment_id FROM study_daily_plan WHERE daily_plan_id = NEW.daily_plan_id)
BEGIN
    SELECT RAISE(ABORT, 'a plan entry must use a card of the same course');
END;

CREATE TRIGGER memory_review_log_same_enrolment BEFORE INSERT ON memory_review_log
WHEN NEW.attempt_id IS NOT NULL
 AND (SELECT s.enrolment_id FROM study_attempt a JOIN study_session s USING (session_id) WHERE a.attempt_id = NEW.attempt_id)
     IS NOT (SELECT enrolment_id FROM memory_card WHERE card_id = NEW.card_id)
BEGIN
    SELECT RAISE(ABORT, 'a review must link to an attempt of the same course');
END;

CREATE TRIGGER study_lookup_same_enrolment BEFORE INSERT ON study_lookup
WHEN NEW.session_id IS NOT NULL
 AND (SELECT enrolment_id FROM study_session WHERE session_id = NEW.session_id) IS NOT NEW.enrolment_id
BEGIN
    SELECT RAISE(ABORT, 'a lookup must link to a session of the same course');
END;

CREATE TRIGGER study_attempt_same_pack BEFORE INSERT ON study_attempt
WHEN (SELECT pack_id FROM catalogue_item WHERE item_id = NEW.item_id)
     IS NOT (SELECT e.pack_id FROM study_session s JOIN study_enrolment e USING (enrolment_id) WHERE s.session_id = NEW.session_id)
BEGIN
    SELECT RAISE(ABORT, 'an attempt must be for an item of the session''s pack');
END;

-- A lesson row belongs to a lesson node, and the course tree has no cycles.
CREATE TRIGGER catalogue_lesson_v_on_lesson_node BEFORE INSERT ON catalogue_lesson_v
WHEN (SELECT node_type FROM catalogue_course_node_v WHERE pack_version_id = NEW.pack_version_id AND item_id = NEW.item_id) IS NOT 'lesson'
BEGIN
    SELECT RAISE(ABORT, 'lesson fields can be added to a lesson node only');
END;

CREATE TRIGGER catalogue_course_node_v_no_cycle BEFORE UPDATE OF parent_item_id ON catalogue_course_node_v
WHEN NEW.parent_item_id IS NOT NULL AND EXISTS (
    WITH RECURSIVE up (id) AS (
        SELECT NEW.parent_item_id
        UNION
        SELECT n.parent_item_id FROM catalogue_course_node_v n JOIN up ON n.item_id = up.id
        WHERE n.pack_version_id = NEW.pack_version_id AND n.parent_item_id IS NOT NULL)
    SELECT 1 FROM up WHERE id = NEW.item_id)
BEGIN
    SELECT RAISE(ABORT, 'this parent would make a cycle in the course tree');
END;

-- Pack versions: start as importing, move only along importing -> active or failed,
-- active <-> retired, and cannot be changed once they leave importing.
CREATE TRIGGER catalogue_pack_version_starts_importing BEFORE INSERT ON catalogue_pack_version
WHEN NEW.status <> 'importing'
BEGIN
    SELECT RAISE(ABORT, 'a pack version starts as importing');
END;

CREATE TRIGGER catalogue_pack_version_transitions BEFORE UPDATE OF status ON catalogue_pack_version
WHEN NOT ((OLD.status = 'importing' AND NEW.status IN ('active', 'failed'))
       OR (OLD.status = 'active' AND NEW.status = 'retired')
       OR (OLD.status = 'retired' AND NEW.status = 'active')
       OR OLD.status = NEW.status)
BEGIN
    SELECT RAISE(ABORT, 'this pack version status change is not allowed');
END;

CREATE TRIGGER catalogue_pack_version_frozen BEFORE UPDATE OF pack_id, version, content_sha256, signature,
    distribution, built_at, imported_at ON catalogue_pack_version
WHEN OLD.status <> 'importing'
BEGIN
    SELECT RAISE(ABORT, 'a pack version cannot be changed after import');
END;

-- Rights cannot contradict the licence, and cannot change once a version that uses the file is installed.
CREATE TRIGGER catalogue_media_asset_licence_insert BEFORE INSERT ON catalogue_media_asset
WHEN NEW.rights_scope = 'shareable' AND (SELECT shareable FROM catalogue_licence WHERE licence_code = NEW.licence_code) = 0
BEGIN
    SELECT RAISE(ABORT, 'a file under this licence cannot be shareable');
END;

CREATE TRIGGER catalogue_media_asset_rights_frozen BEFORE UPDATE OF rights_scope, licence_code ON catalogue_media_asset
WHEN EXISTS (SELECT 1 FROM catalogue_version_media vm JOIN catalogue_pack_version v USING (pack_version_id)
             WHERE vm.sha256 = OLD.sha256 AND v.status <> 'importing')
  OR (NEW.rights_scope = 'shareable' AND (SELECT shareable FROM catalogue_licence WHERE licence_code = NEW.licence_code) = 0)
BEGIN
    SELECT RAISE(ABORT, 'the rights of this file cannot be changed');
END;

CREATE TRIGGER library_item_licence_insert BEFORE INSERT ON library_item
WHEN NEW.rights_scope = 'shareable' AND (SELECT shareable FROM catalogue_licence WHERE licence_code = NEW.licence_code) = 0
BEGIN
    SELECT RAISE(ABORT, 'a library item under this licence cannot be shareable');
END;

-- A library item with a media file has the rights of that file: it cannot be shareable if the file is private.
CREATE TRIGGER library_item_media_rights BEFORE INSERT ON library_item
WHEN NEW.media_sha256 IS NOT NULL AND NEW.rights_scope = 'shareable'
 AND (SELECT rights_scope FROM catalogue_media_asset WHERE sha256 = NEW.media_sha256) = 'private'
BEGIN
    SELECT RAISE(ABORT, 'a library item cannot be shareable when its file is private');
END;

CREATE TRIGGER library_item_media_rights_update BEFORE UPDATE OF rights_scope, media_sha256 ON library_item
WHEN NEW.media_sha256 IS NOT NULL AND NEW.rights_scope = 'shareable'
 AND (SELECT rights_scope FROM catalogue_media_asset WHERE sha256 = NEW.media_sha256) = 'private'
BEGIN
    SELECT RAISE(ABORT, 'a library item cannot be shareable when its file is private');
END;

CREATE TRIGGER library_item_licence_update BEFORE UPDATE OF rights_scope, licence_code ON library_item
WHEN NEW.rights_scope = 'shareable' AND (SELECT shareable FROM catalogue_licence WHERE licence_code = NEW.licence_code) = 0
BEGIN
    SELECT RAISE(ABORT, 'a library item under this licence cannot be shareable');
END;

-- A paradigm cell has either real forms or one row saying the form does not exist.
CREATE TRIGGER catalogue_form_v_nonexistent_alone BEFORE INSERT ON catalogue_form_v
WHEN EXISTS (SELECT 1 FROM catalogue_form_v f
             WHERE f.pack_version_id = NEW.pack_version_id AND f.lexeme_item_id = NEW.lexeme_item_id
               AND f.cell_key = NEW.cell_key AND (f.nonexistent = 1 OR NEW.nonexistent = 1))
BEGIN
    SELECT RAISE(ABORT, 'a cell with a nonexistent row cannot have forms');
END;

-- Private media cannot be used in a shareable pack version.
CREATE TRIGGER catalogue_pack_version_shareable_media BEFORE UPDATE OF status ON catalogue_pack_version
WHEN NEW.status = 'active' AND NEW.distribution = 'shareable'
 AND EXISTS (SELECT 1 FROM catalogue_version_media vm
             JOIN catalogue_media_asset m ON m.sha256 = vm.sha256
             WHERE vm.pack_version_id = NEW.pack_version_id AND m.rights_scope = 'private')
BEGIN
    SELECT RAISE(ABORT, 'a shareable pack version uses private media');
END;

-- Search rows are deleted with their pack version.
CREATE TRIGGER catalogue_pack_version_search_cleanup AFTER DELETE ON catalogue_pack_version
BEGIN
    DELETE FROM catalogue_search_fts WHERE pack_version_id = OLD.pack_version_id;
END;

-- The notebook search index is kept in step with the notebook.
CREATE TRIGGER study_notebook_fts_insert AFTER INSERT ON study_notebook_entry BEGIN
    INSERT INTO study_notebook_fts (rowid, body_md) VALUES (NEW.entry_id, NEW.body_md);
END;
CREATE TRIGGER study_notebook_fts_delete AFTER DELETE ON study_notebook_entry BEGIN
    INSERT INTO study_notebook_fts (study_notebook_fts, rowid, body_md) VALUES ('delete', OLD.entry_id, OLD.body_md);
END;
CREATE TRIGGER study_notebook_fts_update AFTER UPDATE OF body_md ON study_notebook_entry BEGIN
    INSERT INTO study_notebook_fts (study_notebook_fts, rowid, body_md) VALUES ('delete', OLD.entry_id, OLD.body_md);
    INSERT INTO study_notebook_fts (rowid, body_md) VALUES (NEW.entry_id, NEW.body_md);
END;

CREATE TRIGGER library_fts_insert AFTER INSERT ON library_section BEGIN
    INSERT INTO library_fts (rowid, body_text) VALUES (NEW.section_id, NEW.body_text);
END;
CREATE TRIGGER library_fts_delete AFTER DELETE ON library_section BEGIN
    INSERT INTO library_fts (library_fts, rowid, body_text) VALUES ('delete', OLD.section_id, OLD.body_text);
END;
CREATE TRIGGER library_fts_update AFTER UPDATE OF body_text ON library_section BEGIN
    INSERT INTO library_fts (library_fts, rowid, body_text) VALUES ('delete', OLD.section_id, OLD.body_text);
    INSERT INTO library_fts (rowid, body_text) VALUES (NEW.section_id, NEW.body_text);
END;

-- The active version of each pack.
CREATE VIEW catalogue_active_version AS
SELECT pack_id, pack_version_id, version FROM catalogue_pack_version WHERE status = 'active';

-- Items in the active version of their pack. An item a new version leaves out is not live;
-- after a rollback it is live again, with no change to any stored row.
CREATE VIEW catalogue_item_live AS
SELECT vi.item_id, a.pack_id, a.pack_version_id
FROM catalogue_active_version a
JOIN catalogue_version_item vi ON vi.pack_version_id = a.pack_version_id;

-- Every media file in use, by a pack version or by the library. Files not listed here can be deleted.
CREATE VIEW catalogue_media_in_use AS
SELECT DISTINCT sha256 FROM catalogue_version_media
UNION SELECT media_sha256 FROM library_item WHERE media_sha256 IS NOT NULL
UNION SELECT vtt_sha256 FROM library_caption_track;

-- Every row with an expiry date, and that date. The purge job deletes the rows whose date has
-- passed: files first, then rows. A revoked sign-in session is listed from its revocation.
CREATE VIEW retention_expired AS
SELECT 'speech_recording' AS table_name, recording_id AS row_id, delete_after AS expired_at FROM speech_recording
UNION ALL SELECT 'ai_conversation', conversation_id, delete_after FROM ai_conversation
UNION ALL SELECT 'study_handover', handover_id, expires_at FROM study_handover
UNION ALL SELECT 'identity_auth_session', auth_session_id, coalesce(revoked_at, expires_at) FROM identity_auth_session
UNION ALL SELECT 'identity_audit_event', audit_event_id, strftime('%Y-%m-%dT%H:%M:%fZ', at, '+365 days') FROM identity_audit_event
UNION ALL SELECT 'ai_request', ai_request_id, strftime('%Y-%m-%dT%H:%M:%fZ', at, '+365 days') FROM ai_request
UNION ALL SELECT 'identity_invitation', invitation_id, expires_at FROM identity_invitation WHERE accepted_at IS NULL
UNION ALL SELECT 'identity_invitation', invitation_id, strftime('%Y-%m-%dT%H:%M:%fZ', accepted_at, '+30 days') FROM identity_invitation WHERE accepted_at IS NOT NULL;

-- Cost of each model call in micro-dollars, from its tokens and the price row in force.
-- A pending call, and a timeout with no usage returned, count at their estimate, because the
-- provider may still bill them. The limiter reads this view with a range on at (one month, or
-- one learner's day), which uses the indexes on ai_request.
CREATE VIEW ai_request_cost AS
SELECT r.ai_request_id, r.learner_id, r.category, r.purpose, r.outcome, r.at,
       CASE WHEN r.outcome = 'pending' OR (r.outcome = 'timeout' AND r.ai_price_id IS NULL) THEN r.estimated_microusd
            ELSE coalesce((r.input_tokens * p.input + r.cache_write_5m_tokens * p.cache_write_5m
                 + r.cache_write_1h_tokens * p.cache_write_1h + r.cache_read_tokens * p.cache_read
                 + r.output_tokens * p.output) / 1000000, 0) END AS cost_microusd
FROM ai_request r LEFT JOIN ai_price p ON p.ai_price_id = r.ai_price_id;

-- Prices in force today, one row per provider, model and tier. The app loads prices from here.
CREATE VIEW ai_price_current AS
SELECT * FROM ai_price
WHERE valid_from <= date('now') AND (valid_to IS NULL OR valid_to > date('now'));

-- Spending per category and calendar month (UTC), the figure the limiter compares with the limit.
CREATE VIEW ai_month_spend AS
SELECT category, substr(at, 1, 7) AS month, sum(cost_microusd) AS spent_microusd,
       count(*) AS calls, sum(outcome = 'over_limit') AS refused_calls
FROM ai_request_cost GROUP BY category, substr(at, 1, 7);

-- The limit in force now for each category.
CREATE VIEW ai_budget_current AS
SELECT b.* FROM ai_budget b
WHERE b.valid_from = (SELECT max(valid_from) FROM ai_budget x
                      WHERE x.category = b.category AND x.valid_from <= strftime('%Y-%m-%dT%H:%M:%fZ', 'now'));
