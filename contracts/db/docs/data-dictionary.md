# Franca data dictionary

Generated from `schema.sql` by `gen_docs.py`. Do not edit by hand.

129 tables. Tables ending in `_v` hold pack content for one pack version.

## Packs, versions, stable items, media and settings

### `catalogue_activity_type`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `activity_type` | TEXT | yes | PK |  |
| `name_en` | TEXT | yes |  |  |
| `strand` | TEXT | yes |  |  |
| `response` | TEXT | yes |  |  |
| `needs_microphone` | INTEGER | yes |  |  |
| `needs_handwriting` | INTEGER | yes |  |  |
| `auto_graded` | INTEGER | yes |  |  |
| `game` | INTEGER | yes |  |  |

### `catalogue_alignment_token_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_transcript_line_v` (on delete cascade) |
| `media_sha256` | TEXT | yes | PK FK | `catalogue_transcript_line_v` (on delete cascade) |
| `line_no` | INTEGER | yes | PK FK | `catalogue_transcript_line_v` (on delete cascade) |
| `token_no` | INTEGER | yes | PK |  |
| `surface` | TEXT | yes |  |  |
| `start_ms` | INTEGER | yes |  |  |
| `end_ms` | INTEGER | yes |  |  |
| `item_id` | INTEGER |  | FK | `catalogue_item` |
| `grammar_item_id` | INTEGER |  | FK | `catalogue_item` |

### `catalogue_course_config_v`

Course settings (spec/course-config.schema.json).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `bridge_min` | INTEGER | yes |  |  |
| `bridge_max` | INTEGER | yes |  |  |
| `bridge_max_seconds` | INTEGER | yes |  |  |
| `recall_below` | REAL | yes |  |  |
| `lapses_in_30_days` | INTEGER | yes |  |  |
| `warmup_skip_within_hours` | INTEGER | yes |  |  |
| `offer_review_first_above` | INTEGER | yes |  |  |
| `warmup_target_seconds` | INTEGER | yes |  |  |
| `warmup_limit_seconds` | INTEGER | yes |  |  |
| `reminders_max` | INTEGER | yes |  |  |
| `reminder_seconds` | INTEGER | yes |  |  |
| `fewer_new_above` | REAL | yes |  |  |
| `no_new_lesson_above` | REAL | yes |  |  |
| `new_items_factor_when_reduced` | REAL | yes |  |  |
| `mix_recall_low` | REAL | yes |  |  |
| `mix_recall_high` | REAL | yes |  |  |
| `mix_skip_above` | REAL | yes |  |  |
| `mix_skip_within_hours` | INTEGER | yes |  |  |
| `mix_updates_per_item_per_day` | INTEGER | yes |  |  |
| `mix_recognition_only_on_failure` | INTEGER | yes |  |  |

### `catalogue_element_name_v`

Interface names and strings in the pack's language (ui.yaml).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `element_key` | TEXT | yes | PK FK | `catalogue_ui_element` |
| `name_tl` | TEXT | yes |  |  |

### `catalogue_error_type`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `error_type` | TEXT | yes | PK |  |
| `name_en` | TEXT | yes |  |  |

### `catalogue_glossary_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `term_key` | TEXT | yes | PK |  |
| `term_tl` | TEXT | yes |  |  |
| `term_en` | TEXT | yes |  |  |
| `explanation_en` | TEXT | yes |  |  |
| `explanation_tl` | TEXT |  |  |  |

### `catalogue_item`

One row per item key. Rows are added on import and are not deleted, because learner data is linked to item_id. Whether an item is in the active version is worked out from the content tables (view catalogue_item_live), so a rollback needs no change here.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `item_id` | INTEGER | yes | PK |  |
| `pack_id` | INTEGER | yes | FK | `catalogue_pack` |
| `item_key` | TEXT | yes |  |  |
| `kind` | TEXT | yes | FK | `catalogue_item_kind` |

### `catalogue_licence`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `licence_code` | TEXT | yes | PK |  |
| `name` | TEXT | yes |  |  |
| `url` | TEXT |  |  |  |
| `shareable` | INTEGER | yes |  |  |

### `catalogue_listening_rule_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `level` | TEXT | yes | PK |  |
| `listens_without_text` | INTEGER | yes |  |  |
| `extra_listen_offered` | INTEGER | yes |  |  |
| `transliteration_listen` | INTEGER | yes |  |  |
| `transcript_from` | INTEGER | yes |  |  |
| `highlight_words` | INTEGER | yes |  |  |
| `english_from` | INTEGER | yes |  |  |
| `english_mode` | TEXT | yes |  |  |
| `slower_speed` | INTEGER | yes |  |  |

### `catalogue_media_asset`

Media files are stored on disk by hash (media/ab/cd/<sha256>), not in the database. One asset row can be used by several pack versions and by the library.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `sha256` | TEXT | yes | PK |  |
| `mime` | TEXT | yes |  |  |
| `byte_size` | INTEGER | yes |  |  |
| `duration_ms` | INTEGER |  |  |  |
| `width` | INTEGER |  |  |  |
| `height` | INTEGER |  |  |  |
| `licence_code` | TEXT | yes | FK | `catalogue_licence` |
| `rights_scope` | TEXT | yes |  |  |
| `attribution` | TEXT |  |  |  |
| `source_url` | TEXT |  |  |  |
| `synthetic_voice` | INTEGER | yes |  |  |
| `added_at` | TEXT | yes |  |  |

### `catalogue_pack`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_id` | INTEGER | yes | PK |  |
| `language` | TEXT | yes |  |  |
| `name_en` | TEXT | yes |  |  |
| `script` | TEXT | yes |  |  |
| `direction` | TEXT | yes |  |  |
| `created_at` | TEXT | yes |  |  |

### `catalogue_pack_version`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK |  |
| `pack_id` | INTEGER | yes | FK | `catalogue_pack` |
| `version` | TEXT | yes |  |  |
| `content_sha256` | TEXT | yes |  |  |
| `signature` | BLOB | yes |  |  |
| `distribution` | TEXT | yes |  |  |
| `status` | TEXT | yes |  |  |
| `built_at` | TEXT | yes |  |  |
| `imported_at` | TEXT | yes |  |  |
| `activated_at` | TEXT |  |  |  |
| `retired_at` | TEXT |  |  |  |

### `catalogue_preteach_limit_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `level` | TEXT | yes | PK |  |
| `max_items` | INTEGER | yes |  |  |

### `catalogue_transcript_line_v`

Transcripts and word timings for pack audio and video.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `media_sha256` | TEXT | yes | PK FK | `catalogue_media_asset` |
| `line_no` | INTEGER | yes | PK |  |
| `speaker_label` | TEXT |  |  |  |
| `start_ms` | INTEGER | yes |  |  |
| `end_ms` | INTEGER | yes |  |  |
| `text_tl` | TEXT | yes |  |  |
| `text_en` | TEXT |  |  |  |
| `transliteration` | TEXT |  |  |  |

### `catalogue_ui_element`

Interface element keys. The name that is shown is taken from the pack (catalogue_element_name_v). name_en is used where the pack has no name, and for the English layer.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `element_key` | TEXT | yes | PK |  |
| `name_en` | TEXT | yes |  |  |
| `description` | TEXT | yes |  |  |

### `catalogue_ui_string_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `string_key` | TEXT | yes | PK |  |
| `message_icu` | TEXT | yes |  |  |

### `catalogue_variety`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `variety_id` | INTEGER | yes | PK |  |
| `pack_id` | INTEGER | yes | FK | `catalogue_pack` |
| `code` | TEXT | yes |  |  |
| `name_en` | TEXT | yes |  |  |
| `productive` | INTEGER | yes |  |  |
| `receptive_from` | TEXT |  |  |  |

## Course tree, lessons and activities

### `catalogue_accepted_answer_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_activity_v` (on delete cascade) |
| `activity_item_id` | INTEGER | yes | PK FK | `catalogue_activity_v` (on delete cascade) |
| `slot` | INTEGER | yes | PK |  |
| `answer_no` | INTEGER | yes | PK |  |
| `answer_text` | TEXT | yes |  |  |
| `variety_id` | INTEGER |  | FK | `catalogue_variety` |
| `preferred` | INTEGER | yes |  |  |

### `catalogue_activity_use_v`

Items used in an activity, and which of them the learner has to produce.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_activity_v` (on delete cascade) |
| `activity_item_id` | INTEGER | yes | PK FK | `catalogue_activity_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `production_target` | INTEGER | yes |  |  |

### `catalogue_activity_v`

Activities. Fields that differ by activity type are in payload, checked against the pack JSON Schema at build time and not used in SQL conditions (see the data model document).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `lesson_item_id` | INTEGER |  | FK | `catalogue_lesson_v` |
| `step` | TEXT |  |  |  |
| `position` | INTEGER | yes |  |  |
| `activity_type` | TEXT | yes | FK | `catalogue_activity_type` |
| `purpose` | TEXT | yes |  |  |
| `grammar_item_id` | INTEGER |  | FK | `catalogue_item` |
| `media_sha256` | TEXT |  | FK | `catalogue_media_asset` |
| `prompt_tl` | TEXT |  |  |  |
| `prompt_en` | TEXT |  |  |  |
| `payload` | TEXT |  |  |  |

### `catalogue_course_node_v`

Course tree: level, stage, unit, lesson and domain module nodes.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `parent_item_id` | INTEGER |  | FK | `catalogue_course_node_v` |
| `node_type` | TEXT | yes |  |  |
| `position` | INTEGER | yes |  |  |
| `level` | TEXT |  |  |  |
| `title_tl` | TEXT | yes |  |  |
| `title_en` | TEXT | yes |  |  |
| `estimated_minutes` | INTEGER |  |  |  |
| `lesson_role` | TEXT |  |  |  |

### `catalogue_deck_item_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_deck_v` (on delete cascade) |
| `deck_key` | TEXT | yes | PK FK | `catalogue_deck_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `position` | INTEGER | yes |  |  |

### `catalogue_deck_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `deck_key` | TEXT | yes | PK |  |
| `title_tl` | TEXT | yes |  |  |
| `title_en` | TEXT | yes |  |  |

### `catalogue_lesson_item_v`

The items linked to a lesson, by role: taught, taught before the input (preteach), built on, or shown without being taught (exposure_only).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lesson_v` (on delete cascade) |
| `lesson_item_id` | INTEGER | yes | PK FK | `catalogue_lesson_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `relation` | TEXT | yes |  |  |
| `weight` | TEXT |  |  |  |
| `position` | INTEGER | yes |  |  |
| `taught_in_item_id` | INTEGER |  | FK | `catalogue_course_node_v` |
| `prompt_target` | TEXT |  |  |  |
| `prompt_transliteration` | TEXT |  |  |  |
| `prompt_cue_en` | TEXT |  |  |  |

### `catalogue_lesson_return_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lesson_v` (on delete cascade) |
| `lesson_item_id` | INTEGER | yes | PK FK | `catalogue_lesson_v` (on delete cascade) |
| `node_item_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` |

### `catalogue_lesson_v`

Lesson-only fields (spec/lesson.schema.json).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` (on delete cascade) |
| `recap_of_item_id` | INTEGER |  | FK | `catalogue_course_node_v` |
| `prediction_tl` | TEXT |  |  |  |
| `prediction_en` | TEXT |  |  |  |
| `prediction_multiple` | INTEGER |  |  |  |

### `catalogue_prediction_option_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lesson_v` (on delete cascade) |
| `lesson_item_id` | INTEGER | yes | PK FK | `catalogue_lesson_v` (on delete cascade) |
| `option_no` | INTEGER | yes | PK |  |
| `text_tl` | TEXT | yes |  |  |
| `text_en` | TEXT |  |  |  |
| `is_answer` | INTEGER | yes |  |  |
| `feedback_tl` | TEXT |  |  |  |
| `feedback_en` | TEXT |  |  |  |

## Lexicon, forms, verbs, pronunciation and chunks

### `catalogue_chunk_part_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_chunk_v` (on delete cascade) |
| `chunk_item_id` | INTEGER | yes | PK FK | `catalogue_chunk_v` (on delete cascade) |
| `position` | INTEGER | yes | PK |  |
| `surface` | TEXT | yes |  |  |
| `lexeme_item_id` | INTEGER |  | FK | `catalogue_lexeme_v` |

### `catalogue_chunk_v`

Chunks and formulas.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `text_tl` | TEXT | yes |  |  |
| `gloss_en` | TEXT | yes |  |  |
| `literal_en` | TEXT |  |  |  |
| `function_en` | TEXT |  |  |  |
| `register` | TEXT | yes |  |  |
| `level` | TEXT |  |  |  |

### `catalogue_form_v`

Inflected forms. A cell can have more than one variant (zei, zegde), and a variant can be limited to one variety. A form that does not exist is a row with nonexistent = 1.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `lexeme_item_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `cell_key` | TEXT | yes | PK FK | `catalogue_paradigm_cell_v` |
| `variant_no` | INTEGER | yes | PK |  |
| `form` | TEXT |  |  |  |
| `variety_id` | INTEGER |  | FK | `catalogue_variety` |
| `nonexistent` | INTEGER | yes |  |  |

### `catalogue_lexeme_feature_v`

Grammatical features with Universal Dependencies names, for example Gender=Com. A word that takes both de and het has two rows.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `lexeme_item_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `feature` | TEXT | yes | PK |  |
| `value` | TEXT | yes | PK |  |

### `catalogue_lexeme_v`

Lexicon.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `lemma` | TEXT | yes |  |  |
| `upos` | TEXT | yes |  |  |
| `frequency_rank` | INTEGER |  |  |  |
| `level` | TEXT |  |  |  |
| `added_for_course` | INTEGER | yes |  |  |
| `review_status` | TEXT | yes |  |  |

### `catalogue_paradigm_cell_v`

Paradigm cells defined by the pack, for example present.2sg.inverted, past.pl or plural.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `cell_key` | TEXT | yes | PK |  |
| `upos` | TEXT | yes |  |  |
| `form_type` | TEXT | yes |  |  |
| `ud_feats` | TEXT |  |  |  |
| `label_tl` | TEXT | yes |  |  |
| `label_en` | TEXT | yes |  |  |
| `position` | INTEGER | yes |  |  |

### `catalogue_picture_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_sense_v` (on delete cascade) |
| `sense_item_id` | INTEGER | yes | PK FK | `catalogue_sense_v` (on delete cascade) |
| `image_sha256` | TEXT | yes | PK FK | `catalogue_media_asset` |
| `alt_en` | TEXT | yes |  |  |
| `alt_tl` | TEXT |  |  |  |

### `catalogue_pronunciation_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `pronunciation_no` | INTEGER | yes | PK |  |
| `item_id` | INTEGER | yes | FK | `catalogue_item` |
| `variety_id` | INTEGER | yes | FK | `catalogue_variety` |
| `speaker_key` | TEXT |  | FK | `catalogue_speaker_v` |
| `ipa` | TEXT |  |  |  |
| `audio_sha256` | TEXT |  | FK | `catalogue_media_asset` |

### `catalogue_sense_example_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_sense_v` (on delete cascade) |
| `sense_item_id` | INTEGER | yes | PK FK | `catalogue_sense_v` (on delete cascade) |
| `example_no` | INTEGER | yes | PK |  |
| `text_tl` | TEXT | yes |  |  |
| `text_en` | TEXT | yes |  |  |
| `audio_sha256` | TEXT |  | FK | `catalogue_media_asset` |

### `catalogue_sense_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `lexeme_item_id` | INTEGER | yes | FK | `catalogue_lexeme_v` (on delete cascade) |
| `sense_no` | INTEGER | yes |  |  |
| `gloss_en` | TEXT | yes |  |  |
| `definition_tl` | TEXT |  |  |  |
| `register` | TEXT | yes |  |  |
| `variety_id` | INTEGER |  | FK | `catalogue_variety` |
| `level` | TEXT |  |  |  |

### `catalogue_speaker_v`

Pronunciation per variety and speaker.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `speaker_key` | TEXT | yes | PK |  |
| `display_name` | TEXT | yes |  |  |
| `variety_id` | INTEGER | yes | FK | `catalogue_variety` |
| `voice_kind` | TEXT | yes |  |  |

### `catalogue_verb_auxiliary_v`

Auxiliaries for the perfect: one row per auxiliary, so a verb with hebben and zijn has two.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_verb_v` (on delete cascade) |
| `verb_item_id` | INTEGER | yes | PK FK | `catalogue_verb_v` (on delete cascade) |
| `auxiliary_item_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` |
| `condition_en` | TEXT |  |  |  |
| `example_tl` | TEXT |  |  |  |
| `example_en` | TEXT |  |  |  |

### `catalogue_verb_class_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `class_key` | TEXT | yes | PK |  |
| `label_tl` | TEXT | yes |  |  |
| `label_en` | TEXT | yes |  |  |

### `catalogue_verb_rule_v`

Which rules apply to a verb (shown beside its chart).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_verb_v` (on delete cascade) |
| `verb_item_id` | INTEGER | yes | PK FK | `catalogue_verb_v` (on delete cascade) |
| `rule_item_id` | INTEGER | yes | PK FK | `catalogue_rule_v` |

### `catalogue_verb_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `lexeme_item_id` | INTEGER | yes | PK FK | `catalogue_lexeme_v` (on delete cascade) |
| `class_key` | TEXT | yes | FK | `catalogue_verb_class_v` |
| `stem` | TEXT | yes |  |  |
| `vowel_pattern` | TEXT |  |  |  |
| `separable_particle` | TEXT |  |  |  |
| `subject` | TEXT | yes |  |  |
| `chart_rank` | INTEGER |  |  |  |
| `review_status` | TEXT | yes |  |  |

## Grammar, rules, sounds, can-dos and scenarios

### `catalogue_can_do_component_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_can_do_v` (on delete cascade) |
| `can_do_item_id` | INTEGER | yes | PK FK | `catalogue_can_do_v` (on delete cascade) |
| `component` | TEXT | yes | PK |  |

### `catalogue_can_do_evidence_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_can_do_component_v` (on delete cascade) |
| `can_do_item_id` | INTEGER | yes | PK FK | `catalogue_can_do_component_v` (on delete cascade) |
| `component` | TEXT | yes | PK FK | `catalogue_can_do_component_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `weight` | REAL | yes |  |  |

### `catalogue_can_do_v`

Can-do descriptors, the components that are measured for a descriptor, and the items that count as evidence.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `level` | TEXT | yes |  |  |
| `activity` | TEXT | yes |  |  |
| `descriptor_en` | TEXT | yes |  |  |
| `descriptor_tl` | TEXT |  |  |  |

### `catalogue_confusable_pair_v`

Grammar points that learners often confuse, for interleaved practice in the mixed run.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_a_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `item_b_id` | INTEGER | yes | PK FK | `catalogue_item` |

### `catalogue_exam_v`

Exams a learner can name as a target. available = 0: listed as coming after this release.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `exam_key` | TEXT | yes | PK |  |
| `name_tl` | TEXT | yes |  |  |
| `name_en` | TEXT | yes |  |  |
| `issuer` | TEXT | yes |  |  |
| `level` | TEXT | yes |  |  |
| `skills` | TEXT | yes |  |  |
| `url` | TEXT |  |  |  |
| `checked_on` | TEXT | yes |  |  |
| `level_exam_item_id` | INTEGER |  | FK | `catalogue_course_node_v` |
| `available` | INTEGER | yes |  |  |

### `catalogue_explanation_v`

Explanation sections from the template, at three depths.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_grammar_point_v` (on delete cascade) |
| `grammar_item_id` | INTEGER | yes | PK FK | `catalogue_grammar_point_v` (on delete cascade) |
| `depth` | TEXT | yes | PK |  |
| `section` | TEXT | yes | PK |  |
| `body_en_md` | TEXT | yes |  |  |
| `body_tl_md` | TEXT |  |  |  |

### `catalogue_goal_link_v`

Goal tags on scenarios, can-dos and course nodes. An item with no tag is general and is offered to every learner.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_goal_v` (on delete cascade) |
| `goal_key` | TEXT | yes | PK FK | `catalogue_goal_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `weight` | REAL | yes |  |  |

### `catalogue_goal_v`

Learner goals as the pack offers them. The goal keys belong to the app (study_goal) and are the same in every pack; the pack has the names and says which goals it offers.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `goal_key` | TEXT | yes | PK FK | `study_goal` |
| `name_tl` | TEXT | yes |  |  |
| `name_en` | TEXT | yes |  |  |
| `position` | INTEGER | yes |  |  |
| `offered` | INTEGER | yes |  |  |

### `catalogue_grammar_point_v`

Grammar graph, explanations and rules.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `title_tl` | TEXT | yes |  |  |
| `title_en` | TEXT | yes |  |  |
| `level` | TEXT |  |  |  |
| `review_status` | TEXT | yes |  |  |

### `catalogue_grammar_prerequisite_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_grammar_point_v` (on delete cascade) |
| `grammar_item_id` | INTEGER | yes | PK FK | `catalogue_grammar_point_v` (on delete cascade) |
| `requires_item_id` | INTEGER | yes | PK FK | `catalogue_grammar_point_v` |

### `catalogue_item_kind`

What kind of thing an item is, which says which content table describes it. A pack's own item types (the middle part of an item key) are mapped onto these.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `kind` | TEXT | yes | PK |  |
| `description` | TEXT | yes |  |  |

### `catalogue_minimal_pair_audio_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_minimal_pair_v` (on delete cascade) |
| `contrast_item_id` | INTEGER | yes | PK FK | `catalogue_minimal_pair_v` (on delete cascade) |
| `pair_no` | INTEGER | yes | PK FK | `catalogue_minimal_pair_v` (on delete cascade) |
| `side` | TEXT | yes | PK |  |
| `speaker_key` | TEXT | yes | PK FK | `catalogue_speaker_v` |
| `audio_sha256` | TEXT | yes | FK | `catalogue_media_asset` |

### `catalogue_minimal_pair_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_sound_contrast_v` (on delete cascade) |
| `contrast_item_id` | INTEGER | yes | PK FK | `catalogue_sound_contrast_v` (on delete cascade) |
| `pair_no` | INTEGER | yes | PK |  |
| `word_a` | TEXT | yes |  |  |
| `word_b` | TEXT | yes |  |  |

### `catalogue_module_v`

Domain module fields (a module is a course node). Terminology is offered from the first level, and genre and task work from the second.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` (on delete cascade) |
| `terminology_from` | TEXT | yes |  |  |
| `tasks_from` | TEXT | yes |  |  |

### `catalogue_node_can_do_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` (on delete cascade) |
| `node_item_id` | INTEGER | yes | PK FK | `catalogue_course_node_v` (on delete cascade) |
| `can_do_item_id` | INTEGER | yes | PK FK | `catalogue_can_do_v` |

### `catalogue_rule_example_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_rule_v` (on delete cascade) |
| `rule_item_id` | INTEGER | yes | PK FK | `catalogue_rule_v` (on delete cascade) |
| `example_no` | INTEGER | yes | PK |  |
| `text_tl` | TEXT | yes |  |  |
| `text_en` | TEXT | yes |  |  |
| `step_item_id` | INTEGER |  | FK | `catalogue_rule_step_v` |
| `worked` | INTEGER | yes |  |  |

### `catalogue_rule_exception_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_rule_v` (on delete cascade) |
| `rule_item_id` | INTEGER | yes | PK FK | `catalogue_rule_v` (on delete cascade) |
| `exception_no` | INTEGER | yes | PK |  |
| `lexeme_item_id` | INTEGER |  | FK | `catalogue_lexeme_v` |
| `note_en` | TEXT | yes |  |  |
| `example_tl` | TEXT |  |  |  |

### `catalogue_rule_step_outcome_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_rule_step_v` (on delete cascade) |
| `step_item_id` | INTEGER | yes | PK FK | `catalogue_rule_step_v` (on delete cascade) |
| `outcome_no` | INTEGER | yes | PK |  |
| `answer_en` | TEXT | yes |  |  |
| `answer_tl` | TEXT |  |  |  |
| `action_en` | TEXT | yes |  |  |
| `next_step_item_id` | INTEGER |  | FK | `catalogue_rule_step_v` |

### `catalogue_rule_step_v`

A step is an item of its own (key such as nl:grammar:niet-geen#ng-2), so a wrong answer can be linked to the step where the learner went wrong.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_rule_v` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `rule_item_id` | INTEGER | yes | FK | `catalogue_rule_v` (on delete cascade) |
| `position` | INTEGER | yes |  |  |
| `question_en` | TEXT | yes |  |  |
| `question_tl` | TEXT |  |  |  |

### `catalogue_rule_v`

Rules with decision or formation steps, for example niet and geen, 't kofschip and the spelling rules.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `grammar_item_id` | INTEGER |  | FK | `catalogue_grammar_point_v` |
| `rule_type` | TEXT | yes |  |  |
| `title_tl` | TEXT | yes |  |  |
| `title_en` | TEXT | yes |  |  |
| `why_en_md` | TEXT |  |  |  |
| `review_status` | TEXT | yes |  |  |

### `catalogue_scenario_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `title_tl` | TEXT | yes |  |  |
| `title_en` | TEXT | yes |  |  |
| `setting_en` | TEXT | yes |  |  |
| `goal_en` | TEXT | yes |  |  |
| `role_a_en` | TEXT | yes |  |  |
| `role_b_en` | TEXT | yes |  |  |
| `register` | TEXT | yes |  |  |
| `level` | TEXT | yes |  |  |
| `can_do_item_id` | INTEGER |  | FK | `catalogue_can_do_v` |
| `variety_id` | INTEGER |  | FK | `catalogue_variety` |
| `slot_node_item_id` | INTEGER |  | FK | `catalogue_course_node_v` |
| `slot_no` | INTEGER |  |  |  |

### `catalogue_sound_contrast_v`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_sound_v` |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `sound_a_item_id` | INTEGER | yes | FK | `catalogue_sound_v` |
| `sound_b_item_id` | INTEGER | yes | FK | `catalogue_sound_v` |
| `priority` | INTEGER |  |  |  |
| `note_en` | TEXT |  |  |  |

### `catalogue_sound_v`

Sounds and minimal pairs.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `pack_version_id` | INTEGER | yes | PK FK | `catalogue_pack_version` (on delete cascade) |
| `item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `ipa` | TEXT | yes |  |  |
| `name_en` | TEXT | yes |  |  |
| `description_en` | TEXT |  |  |  |

## Learners, sign-in, preferences and audit log

### `identity_audit_event`

Security events (OWASP ASVS V7). There are no secrets or answer text in the detail column. Kept for one year.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `audit_event_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `event` | TEXT | yes |  |  |
| `detail` | TEXT |  |  |  |
| `at` | TEXT | yes |  |  |

### `identity_auth_session`

A sign-in session expires 30 days after it was last used (decision of 11 November 2026): expires_at is moved forward when the session is used. There is a 256-bit random token in the session cookie. The token is not stored; its SHA-256 hash is.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `auth_session_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `token_hash` | BLOB | yes |  |  |
| `device_kind` | TEXT | yes |  |  |
| `user_agent` | TEXT |  |  |  |
| `created_at` | TEXT | yes |  |  |
| `last_seen_at` | TEXT | yes |  |  |
| `expires_at` | TEXT | yes |  |  |
| `revoked_at` | TEXT |  |  |  |
| `passkey_credential_id` | BLOB |  | FK | `identity_passkey` (on delete set null) |

### `identity_external_identity`

Sign-in through an outside identity provider. subject is the provider's stable id for the person (the OpenID Connect sub claim); the e-mail address can change and is not a key.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `external_identity_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `provider` | TEXT | yes |  |  |
| `subject` | TEXT | yes |  |  |
| `email` | TEXT | yes |  |  |
| `email_verified` | INTEGER | yes |  |  |
| `created_at` | TEXT | yes |  |  |
| `last_used_at` | TEXT |  |  |  |

### `identity_invitation`

The owner invites a person by e-mail address. The first Google sign-in with that verified address within the time limit creates the learner. The app stores addresses after Unicode NFC and casefold; the CHECK below covers ASCII letters only. An invitation always makes a learner: the owner role is not handed over by invitation. Before a new invitation to the same address, the app revokes an expired one, since the index below treats it as still open. An accepted invitation is purged 30 days after acceptance (retention_expired).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `invitation_id` | INTEGER | yes | PK |  |
| `email_norm` | TEXT | yes |  |  |
| `role` | TEXT | yes |  |  |
| `invited_by_learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `created_at` | TEXT | yes |  |  |
| `expires_at` | TEXT | yes |  |  |
| `accepted_at` | TEXT |  |  |  |
| `accepted_learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `revoked_at` | TEXT |  |  |  |

### `identity_learner`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `learner_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `display_name` | TEXT | yes |  |  |
| `role` | TEXT | yes |  |  |
| `status` | TEXT | yes |  |  |
| `support_language` | TEXT | yes |  |  |
| `timezone` | TEXT | yes |  |  |
| `day_starts_hour` | INTEGER | yes |  |  |
| `created_at` | TEXT | yes |  |  |

### `identity_passkey`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `credential_id` | BLOB | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `public_key` | BLOB | yes |  |  |
| `sign_count` | INTEGER | yes |  |  |
| `transports` | TEXT |  |  |  |
| `aaguid` | BLOB |  |  |  |
| `backup_eligible` | INTEGER | yes |  |  |
| `backed_up` | INTEGER | yes |  |  |
| `label` | TEXT |  |  |  |
| `created_at` | TEXT | yes |  |  |
| `last_used_at` | TEXT |  |  |  |

### `identity_preferences`

One row per learner. Settings that belong to one course are on study_enrolment.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `learner_id` | INTEGER | yes | PK FK | `identity_learner` (on delete cascade) |
| `english_layer` | INTEGER | yes |  |  |
| `line_controls` | TEXT | yes |  |  |
| `font` | TEXT | yes |  |  |
| `text_scale` | REAL | yes |  |  |
| `line_spacing` | REAL | yes |  |  |
| `theme` | TEXT | yes |  |  |
| `reduced_motion` | TEXT | yes |  |  |
| `handwriting` | INTEGER | yes |  |  |
| `typo_tolerance` | TEXT | yes |  |  |
| `library_captions` | TEXT | yes |  |  |
| `session_mode` | TEXT | yes |  |  |
| `break_minutes` | INTEGER | yes |  |  |
| `updated_at` | TEXT | yes |  |  |

### `identity_push_subscription`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `push_subscription_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `endpoint` | TEXT | yes |  |  |
| `p256dh` | BLOB | yes |  |  |
| `auth_secret` | BLOB | yes |  |  |
| `created_at` | TEXT | yes |  |  |
| `last_success_at` | TEXT |  |  |  |
| `failure_count` | INTEGER | yes |  |  |

### `identity_recovery_code`

Recovery codes are stored as Argon2id hashes, not as plain text.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `recovery_code_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `code_hash` | TEXT | yes |  |  |
| `created_at` | TEXT | yes |  |  |
| `used_at` | TEXT |  |  |  |

### `identity_reminder`

Optional daily reminder: one row per weekday the learner chose (1 = Monday).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `learner_id` | INTEGER | yes | PK FK | `identity_learner` (on delete cascade) |
| `weekday` | INTEGER | yes | PK |  |
| `local_time` | TEXT | yes |  |  |
| `last_sent_on` | TEXT |  |  |  |

## Enrolments, daily plan, sessions, attempts and lookups

### `study_attempt`

One answer to one item. The grade and the schedule change are in memory_review_log. If there is no review row for an attempt, the schedule was not changed (for example after a correct recognition answer in a mixed run). help_rung: 0 none, 1 tip, 2 step by step, 3 answer shown. activity_type and direction are kept for generated exercises too.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `attempt_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `session_id` | INTEGER | yes | FK | `study_session` (on delete cascade) |
| `activity_item_id` | INTEGER |  | FK | `catalogue_item` |
| `activity_type` | TEXT | yes | FK | `catalogue_activity_type` |
| `item_id` | INTEGER | yes | FK | `catalogue_item` |
| `direction` | TEXT | yes |  |  |
| `cell_key` | TEXT |  |  |  |
| `input_mode` | TEXT | yes |  |  |
| `response` | TEXT |  |  |  |
| `is_correct` | INTEGER |  |  |  |
| `help_rung` | INTEGER | yes |  |  |
| `latency_ms` | INTEGER |  |  |  |
| `started_at` | TEXT | yes |  |  |
| `answered_at` | TEXT | yes |  |  |

### `study_checkpoint_result`

Result of a stage checkpoint or level exam. A checkpoint does not block progress. A learner who falls short is offered targeted practice.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK FK | `study_session` (on delete cascade) |
| `node_item_id` | INTEGER | yes | FK | `catalogue_item` |
| `score` | REAL | yes |  |  |
| `outcome` | TEXT | yes |  |  |
| `finished_at` | TEXT | yes |  |  |

### `study_daily_plan`

Vandaag: one plan per enrolment per local day. mode, new_items_factor and offer are the decision made when the plan was built, with the pack version whose settings were used.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `daily_plan_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `plan_day` | TEXT | yes |  |  |
| `built_at` | TEXT | yes |  |  |
| `planned_minutes` | INTEGER | yes |  |  |
| `review_minutes` | INTEGER | yes |  |  |
| `mode` | TEXT | yes |  |  |
| `new_items_factor` | REAL | yes |  |  |
| `offer` | TEXT | yes |  |  |
| `pack_version` | TEXT | yes |  |  |
| `lesson_item_id` | INTEGER |  | FK | `catalogue_item` |
| `extra_kind` | TEXT |  |  |  |
| `extra_ref` | TEXT |  |  |  |
| `extra_goal_key` | TEXT |  | FK | `study_goal` |

### `study_daily_plan_entry`

Entries in a day's plan. Bridge items are held out of review for the warm-up. If the lesson is not started, released_at is filled in and the items count as review again. Reminders are for core items the learner has never met, so they have no card.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `daily_plan_id` | INTEGER | yes | PK FK | `study_daily_plan` (on delete cascade) |
| `entry_no` | INTEGER | yes | PK |  |
| `section` | TEXT | yes |  |  |
| `card_id` | INTEGER |  | FK | `memory_card` (on delete cascade) |
| `item_id` | INTEGER |  | FK | `catalogue_item` |
| `released_at` | TEXT |  |  |  |
| `done_at` | TEXT |  |  |  |

### `study_device_check`

Speaker, microphone and handwriting checks from the first run, per device kind.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `learner_id` | INTEGER | yes | PK FK | `identity_learner` (on delete cascade) |
| `device_kind` | TEXT | yes | PK |  |
| `check_kind` | TEXT | yes | PK |  |
| `result` | TEXT | yes |  |  |
| `at` | TEXT | yes |  |  |

### `study_enrolment`

A learner's course in one language. Course-level settings are stored here.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `pack_id` | INTEGER | yes | FK | `catalogue_pack` |
| `variety_id` | INTEGER | yes | FK | `catalogue_variety` |
| `daily_minutes` | INTEGER | yes |  |  |
| `depth` | TEXT | yes |  |  |
| `status` | TEXT | yes |  |  |
| `started_at` | TEXT | yes |  |  |

### `study_enrolment_goal`

Goals chosen by the learner. A removed goal keeps its row with removed_at, so progress can be grouped by the goals that applied at the time.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_goal_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `goal_key` | TEXT | yes | FK | `study_goal` |
| `added_at` | TEXT | yes |  |  |
| `removed_at` | TEXT |  |  |  |

### `study_enrolment_module`

Subject modules chosen under the subject goal (key field). A module that is not built yet is an item of the pack with no content in the active version, so the choice can be stored and shown as coming later.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_module_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `module_item_id` | INTEGER | yes | FK | `catalogue_item` |
| `terminology_on` | INTEGER | yes |  |  |
| `added_at` | TEXT | yes |  |  |
| `removed_at` | TEXT |  |  |  |

### `study_enrolment_target`

A target level, with an optional date and exam (exam_key from catalogue_exam_v). One open target per enrolment; a new one replaces it. The app shows a time range, never a countdown.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `target_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `target_level` | TEXT |  |  |  |
| `target_date` | TEXT |  |  |  |
| `exam_key` | TEXT |  |  |  |
| `chosen_at` | TEXT | yes |  |  |
| `replaced_at` | TEXT |  |  |  |

### `study_goal`

The goals a learner can choose (list of 21 November 2026). followup: the goal opens a second question (which exam, which field).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `goal_key` | TEXT | yes | PK |  |
| `name_en` | TEXT | yes |  |  |
| `description_en` | TEXT | yes |  |  |
| `followup` | TEXT |  |  |  |
| `position` | INTEGER | yes |  |  |

### `study_goal_review`

When the learner was shown their goals again (at most once a month) and what they did.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK FK | `study_enrolment` (on delete cascade) |
| `shown_at` | TEXT | yes | PK |  |
| `reason` | TEXT | yes |  |  |
| `outcome` | TEXT | yes |  |  |

### `study_goal_statement`

"Your goals in Dutch", offered after 3 to 5 sessions: what the learner wants to be able to do, in their own words, what might get in the way, and their plan for it. Optional.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `goal_statement_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `statement` | TEXT | yes |  |  |
| `obstacle` | TEXT |  |  |  |
| `plan` | TEXT |  |  |  |
| `created_at` | TEXT | yes |  |  |
| `replaced_at` | TEXT |  |  |  |

### `study_handover`

Handover of one task to the phone by QR code. The code is valid for 10 minutes at most.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `handover_id` | INTEGER | yes | PK |  |
| `session_id` | INTEGER | yes | FK | `study_session` (on delete cascade) |
| `activity_item_id` | INTEGER | yes | FK | `catalogue_item` |
| `token_hash` | BLOB | yes |  |  |
| `created_at` | TEXT | yes |  |  |
| `expires_at` | TEXT | yes |  |  |
| `claimed_at` | TEXT |  |  |  |
| `claimed_by_auth_session_id` | INTEGER |  | FK | `identity_auth_session` (on delete set null) |

### `study_help_step`

Steps answered in Stap voor stap. The first wrong step is the one named in feedback.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `attempt_id` | INTEGER | yes | PK FK | `study_attempt` (on delete cascade) |
| `position` | INTEGER | yes | PK |  |
| `step_item_id` | INTEGER | yes | FK | `catalogue_item` |
| `is_correct` | INTEGER | yes |  |  |

### `study_listen`

One row per time the learner listens in the listening step, with the text that was on screen.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK FK | `study_session` (on delete cascade) |
| `activity_item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `listen_no` | INTEGER | yes | PK |  |
| `speed` | REAL | yes |  |  |
| `transcript` | TEXT | yes |  |  |
| `english` | TEXT | yes |  |  |
| `text_shown_early` | INTEGER | yes |  |  |
| `started_at` | TEXT | yes |  |  |

### `study_lookup`

Looked-up words and sentences, put into the next review (element key: lookups).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `lookup_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `session_id` | INTEGER |  | FK | `study_session` (on delete set null) |
| `item_id` | INTEGER |  | FK | `catalogue_item` |
| `query_text` | TEXT |  |  |  |
| `source` | TEXT | yes |  |  |
| `looked_up_at` | TEXT | yes |  |  |
| `reviewed_at` | TEXT |  |  |  |

### `study_node_progress`

Progress through the course tree. A node with no row has not been started.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK FK | `study_enrolment` (on delete cascade) |
| `node_item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `status` | TEXT | yes |  |  |
| `started_at` | TEXT | yes |  |  |
| `completed_at` | TEXT |  |  |  |

### `study_notebook_entry`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `entry_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `item_id` | INTEGER |  | FK | `catalogue_item` |
| `kind` | TEXT | yes |  |  |
| `body_md` | TEXT | yes |  |  |
| `created_at` | TEXT | yes |  |  |
| `updated_at` | TEXT | yes |  |  |

### `study_personal_can_do`

The learner's own can-do list (up to 8 at a time): suggested from the goals or added by the learner. It is shown to the learner and does not change what is tested at checkpoints. An achieved can-do stays on the list until it is removed; the limit of 8 counts rows that are neither achieved nor removed.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `personal_can_do_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `can_do_item_id` | INTEGER | yes | FK | `catalogue_item` |
| `source` | TEXT | yes |  |  |
| `added_at` | TEXT | yes |  |  |
| `achieved_at` | TEXT |  |  |  |
| `removed_at` | TEXT |  |  |  |

### `study_placement`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK FK | `study_session` (on delete cascade) |
| `outcome` | TEXT | yes |  |  |
| `result_level` | TEXT |  |  |  |
| `vocabulary_estimate` | INTEGER |  |  |  |
| `start_node_item_id` | INTEGER |  | FK | `catalogue_item` |

### `study_practice_run`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK FK | `study_session` (on delete cascade) |
| `mode` | TEXT | yes |  |  |
| `length_items` | INTEGER | yes |  |  |
| `source` | TEXT | yes |  |  |

### `study_practice_run_type`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK FK | `study_practice_run` (on delete cascade) |
| `activity_type` | TEXT | yes | PK FK | `catalogue_activity_type` |

### `study_prediction_choice`

The guess at the start of the warm-up. option_no refers to the lesson's options in the pack version that was active when the guess was made.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK FK | `study_session` (on delete cascade) |
| `lesson_item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `option_no` | INTEGER | yes | PK |  |
| `chosen_at` | TEXT | yes |  |  |

### `study_session`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `session_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `kind` | TEXT | yes |  |  |
| `daily_plan_id` | INTEGER |  | FK | `study_daily_plan` (on delete set null) |
| `node_item_id` | INTEGER |  | FK | `catalogue_item` |
| `pack_version` | TEXT | yes |  |  |
| `device_kind` | TEXT | yes |  |  |
| `started_at` | TEXT | yes |  |  |
| `ended_at` | TEXT |  |  |  |

### `study_tour_part`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `tour_part_key` | TEXT | yes | PK |  |
| `name_en` | TEXT | yes |  |  |
| `position` | INTEGER | yes |  |  |

### `study_tour_progress`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `learner_id` | INTEGER | yes | PK FK | `identity_learner` (on delete cascade) |
| `tour_part_key` | TEXT | yes | PK FK | `study_tour_part` |
| `outcome` | TEXT | yes |  |  |
| `at` | TEXT | yes |  |  |

## Cards, review log, feedback and mastery

### `checking_feedback`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `attempt_id` | INTEGER | yes | PK FK | `study_attempt` (on delete cascade) |
| `position` | INTEGER | yes | PK |  |
| `layer` | TEXT | yes |  |  |
| `error_type` | TEXT |  | FK | `catalogue_error_type` |
| `code` | TEXT |  |  |  |
| `rule_item_id` | INTEGER |  | FK | `catalogue_item` |
| `step_item_id` | INTEGER |  | FK | `catalogue_item` |
| `span_start` | INTEGER |  |  |  |
| `span_end` | INTEGER |  |  |  |
| `message_en` | TEXT | yes |  |  |
| `message_tl` | TEXT |  |  |  |
| `suggestion` | TEXT |  |  |  |

### `mastery_estimate`

ability is on the logit scale of the logistic model. It can be worked out again from attempts.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK FK | `study_enrolment` (on delete cascade) |
| `can_do_item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `component` | TEXT | yes | PK |  |
| `ability` | REAL | yes |  |  |
| `standard_error` | REAL | yes |  |  |
| `evidence_count` | INTEGER | yes |  |  |
| `updated_at` | TEXT | yes |  |  |

### `mastery_self_assessment`

Can-do self-assessment (European Language Portfolio style).

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK FK | `study_enrolment` (on delete cascade) |
| `can_do_item_id` | INTEGER | yes | PK FK | `catalogue_item` |
| `rating` | TEXT | yes |  |  |
| `at` | TEXT | yes | PK |  |

### `memory_card`

One card per learner, item, direction and (for conjugation) form type. A card made offline is matched on this natural key when the queue is replayed. The FSRS columns are the result of replaying the card's review log (see the data model document). A card whose item is not in the active pack version is left out of the queue through catalogue_item_live; suspended_at is for the learner's own choice.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `card_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `item_id` | INTEGER | yes | FK | `catalogue_item` |
| `direction` | TEXT | yes |  |  |
| `form_type` | TEXT | yes |  |  |
| `state` | TEXT | yes |  |  |
| `due_at` | TEXT |  |  |  |
| `stability` | REAL |  |  |  |
| `difficulty` | REAL |  |  |  |
| `learning_step` | INTEGER | yes |  |  |
| `reps` | INTEGER | yes |  |  |
| `lapses` | INTEGER | yes |  |  |
| `last_review_at` | TEXT |  |  |  |
| `suspended_at` | TEXT |  |  |  |
| `created_at` | TEXT | yes |  |  |

### `memory_fsrs_parameters`

FSRS-6 parameters fitted to one learner's reviews in one course.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK FK | `study_enrolment` (on delete cascade) |
| `weights` | TEXT | yes |  |  |
| `desired_retention` | REAL | yes |  |  |
| `fitted_at` | TEXT |  |  |  |
| `reviews_at_fit` | INTEGER | yes |  |  |

### `memory_review_log`

Rows can be added but not changed. The facts in a row are the grade and when and how it was given. A changed grade is a new row (grade_source 'override') with corrects_review_id; it has the reviewed_at, review_day, context and state_before of the row it corrects, so it takes that row's place when the log is replayed. The card's state is worked out by replaying, in reviewed_at order, the rows that no later row corrects. state_before is the card state the scheduler saw when the answer was given. It is not changed on replay; it is kept because a lapse is an Again on a card in review. grade: 1 Again, 2 Hard, 3 Good, 4 Easy.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `review_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `card_id` | INTEGER | yes | FK | `memory_card` (on delete cascade) |
| `attempt_id` | INTEGER |  | FK | `study_attempt` (on delete set null) |
| `context` | TEXT | yes |  |  |
| `grade` | INTEGER | yes |  |  |
| `grade_source` | TEXT | yes |  |  |
| `state_before` | TEXT | yes |  |  |
| `reviewed_at` | TEXT | yes |  |  |
| `review_day` | TEXT | yes |  |  |
| `recorded_at` | TEXT | yes |  |  |
| `corrects_review_id` | INTEGER |  | FK | `memory_review_log` |

## Recordings, conversations and Samen

### `ai_budget`

Spending limits, applied by Franca before each call (decision of 21 November 2026). 'learning' covers calls made while learners study; 'content' covers pack-building jobs. A new row replaces the limit from valid_from on; earlier rows are kept as history.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `ai_budget_id` | INTEGER | yes | PK |  |
| `category` | TEXT | yes |  |  |
| `monthly_limit_microusd` | INTEGER | yes |  |  |
| `learner_daily_limit_microusd` | INTEGER |  |  |  |
| `warn_share_first` | REAL | yes |  |  |
| `warn_share_second` | REAL | yes |  |  |
| `valid_from` | TEXT | yes |  |  |
| `changed_by_learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |

### `ai_budget_alert`

Warnings sent to the owner, so each level is sent once per category and month.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `category` | TEXT | yes | PK |  |
| `month` | TEXT | yes | PK |  |
| `level` | TEXT | yes | PK |  |
| `sent_at` | TEXT | yes |  |  |

### `ai_conversation`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `conversation_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `session_id` | INTEGER | yes | FK | `study_session` (on delete cascade) |
| `scenario_item_id` | INTEGER |  | FK | `catalogue_item` |
| `started_at` | TEXT | yes |  |  |
| `ended_at` | TEXT |  |  |  |
| `delete_after` | TEXT | yes |  |  |

### `ai_price`

Prices of hosted models, in micro-dollars (millionths of a US dollar) per million tokens, as the provider bills them. A model with prices that depend on prompt size (Haiku 5.5 above 100,000 tokens) has one row per tier. Old prices are kept, so past costs stay right.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `ai_price_id` | INTEGER | yes | PK |  |
| `provider` | TEXT | yes |  |  |
| `model` | TEXT | yes |  |  |
| `min_prompt_tokens` | INTEGER | yes |  |  |
| `input` | INTEGER | yes |  |  |
| `output` | INTEGER | yes |  |  |
| `cache_write_5m` | INTEGER | yes |  |  |
| `cache_write_1h` | INTEGER | yes |  |  |
| `cache_read` | INTEGER | yes |  |  |
| `valid_from` | TEXT | yes |  |  |
| `valid_to` | TEXT |  |  |  |
| `source_url` | TEXT |  |  |  |

### `ai_request`

Usage of hosted model calls: tokens, outcome and time. No prompts, answers or learner text. Kept one year. outcome 'over_limit' means Franca's own limiter refused the call before it was sent.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `ai_request_id` | INTEGER | yes | PK |  |
| `learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `category` | TEXT | yes |  |  |
| `purpose` | TEXT | yes |  |  |
| `ai_price_id` | INTEGER |  | FK | `ai_price` |
| `input_tokens` | INTEGER | yes |  |  |
| `cache_write_5m_tokens` | INTEGER | yes |  |  |
| `cache_write_1h_tokens` | INTEGER | yes |  |  |
| `cache_read_tokens` | INTEGER | yes |  |  |
| `output_tokens` | INTEGER | yes |  |  |
| `estimated_microusd` | INTEGER | yes |  |  |
| `outcome` | TEXT | yes |  |  |
| `latency_ms` | INTEGER |  |  |  |
| `at` | TEXT | yes |  |  |

### `ai_turn`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `conversation_id` | INTEGER | yes | PK FK | `ai_conversation` (on delete cascade) |
| `turn_no` | INTEGER | yes | PK |  |
| `speaker` | TEXT | yes |  |  |
| `text_tl` | TEXT | yes |  |  |
| `text_en` | TEXT |  |  |  |
| `recording_id` | INTEGER |  | FK | `speech_recording` (on delete set null) |
| `created_at` | TEXT | yes |  |  |

### `partner_review`

A learner's comments on the other learner's capstone task or recording.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `partner_review_id` | INTEGER | yes | PK |  |
| `attempt_id` | INTEGER | yes | FK | `study_attempt` (on delete cascade) |
| `reviewer_learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `body` | TEXT | yes |  |  |
| `created_at` | TEXT | yes |  |  |

### `partner_roleplay`

A role-play done together. Each learner's part is linked to their own session.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `roleplay_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `scenario_item_id` | INTEGER | yes | FK | `catalogue_item` |
| `setup` | TEXT | yes |  |  |
| `started_at` | TEXT | yes |  |  |

### `partner_roleplay_member`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `roleplay_id` | INTEGER | yes | PK FK | `partner_roleplay` (on delete cascade) |
| `session_id` | INTEGER | yes | FK | `study_session` (on delete cascade) |
| `role` | TEXT | yes | PK |  |

### `partner_share`

What one learner lets the other see. If there is no row for a scope, it is not shared.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `owner_learner_id` | INTEGER | yes | PK FK | `identity_learner` (on delete cascade) |
| `viewer_learner_id` | INTEGER | yes | PK FK | `identity_learner` (on delete cascade) |
| `pack_id` | INTEGER | yes | PK FK | `catalogue_pack` |
| `scope` | TEXT | yes | PK |  |
| `granted_at` | TEXT | yes |  |  |

### `speech_assessment`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `recording_id` | INTEGER | yes | PK FK | `speech_recording` (on delete cascade) |
| `asr_text` | TEXT |  |  |  |
| `asr_model` | TEXT | yes |  |  |
| `overall` | REAL |  |  |  |
| `assessed_at` | TEXT | yes |  |  |

### `speech_phone_score`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `recording_id` | INTEGER | yes | PK FK | `speech_assessment` (on delete cascade) |
| `position` | INTEGER | yes | PK |  |
| `expected_ipa` | TEXT | yes |  |  |
| `heard_ipa` | TEXT |  |  |  |
| `score` | REAL | yes |  |  |
| `start_ms` | INTEGER | yes |  |  |
| `end_ms` | INTEGER | yes |  |  |
| `error_type` | TEXT |  | FK | `catalogue_error_type` |

### `speech_recording`

The audio file is stored on disk under its sha256. The row and the file are deleted together after delete_after.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `recording_id` | INTEGER | yes | PK |  |
| `uuid` | TEXT | yes |  |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `purpose` | TEXT | yes |  |  |
| `attempt_id` | INTEGER |  | FK | `study_attempt` (on delete set null) |
| `sha256` | TEXT | yes |  |  |
| `mime` | TEXT | yes |  |  |
| `duration_ms` | INTEGER | yes |  |  |
| `recorded_at` | TEXT | yes |  |  |
| `delete_after` | TEXT | yes |  |  |

## Library, review queue and xAPI outbox

### `library_caption_track`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `library_item_id` | INTEGER | yes | PK FK | `library_item` (on delete cascade) |
| `language` | TEXT | yes | PK |  |
| `vtt_sha256` | TEXT | yes | FK | `catalogue_media_asset` |

### `library_item`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `library_item_id` | INTEGER | yes | PK |  |
| `pack_id` | INTEGER | yes | FK | `catalogue_pack` |
| `title` | TEXT | yes |  |  |
| `author` | TEXT |  |  |  |
| `kind` | TEXT | yes |  |  |
| `level_estimate` | TEXT |  |  |  |
| `media_sha256` | TEXT |  | FK | `catalogue_media_asset` |
| `licence_code` | TEXT | yes | FK | `catalogue_licence` |
| `rights_scope` | TEXT | yes |  |  |
| `source_note` | TEXT |  |  |  |
| `added_by_learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `added_at` | TEXT | yes |  |  |

### `library_item_goal`

Goals a library item suits, used to weight suggestions. At least half of what is suggested stays general.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `library_item_id` | INTEGER | yes | PK FK | `library_item` (on delete cascade) |
| `goal_key` | TEXT | yes | PK FK | `study_goal` |

### `library_progress`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `enrolment_id` | INTEGER | yes | PK FK | `study_enrolment` (on delete cascade) |
| `library_item_id` | INTEGER | yes | PK FK | `library_item` (on delete cascade) |
| `section_no` | INTEGER | yes |  |  |
| `position` | INTEGER | yes |  |  |
| `updated_at` | TEXT | yes |  |  |
| `finished_at` | TEXT |  |  |  |

### `library_section`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `section_id` | INTEGER | yes | PK |  |
| `library_item_id` | INTEGER | yes | FK | `library_item` (on delete cascade) |
| `section_no` | INTEGER | yes |  |  |
| `title` | TEXT |  |  |  |
| `body_text` | TEXT | yes |  |  |
| `word_count` | INTEGER | yes |  |  |
| `start_ms` | INTEGER |  |  |  |
| `end_ms` | INTEGER |  |  |  |

### `library_term`

Word statuses as in Lute: 1 to 5 learning, 98 ignored, 99 well known. text_norm is NFC and case-folded. A term with no pack item is a word met only in the library.

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `term_id` | INTEGER | yes | PK |  |
| `enrolment_id` | INTEGER | yes | FK | `study_enrolment` (on delete cascade) |
| `text` | TEXT | yes |  |  |
| `text_norm` | TEXT | yes |  |  |
| `word_count` | INTEGER | yes |  |  |
| `status` | INTEGER | yes |  |  |
| `translation` | TEXT |  |  |  |
| `romanisation` | TEXT |  |  |  |
| `item_id` | INTEGER |  | FK | `catalogue_item` |
| `created_at` | TEXT | yes |  |  |
| `status_changed_at` | TEXT | yes |  |  |

### `library_term_parent`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `term_id` | INTEGER | yes | PK FK | `library_term` (on delete cascade) |
| `parent_term_id` | INTEGER | yes | PK FK | `library_term` (on delete cascade) |

### `records_xapi_statement`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `statement_uuid` | TEXT | yes | PK |  |
| `learner_id` | INTEGER | yes | FK | `identity_learner` (on delete cascade) |
| `attempt_id` | INTEGER |  | FK | `study_attempt` (on delete set null) |
| `verb_iri` | TEXT | yes |  |  |
| `statement_json` | TEXT | yes |  |  |
| `stored_at` | TEXT | yes |  |  |
| `exported_at` | TEXT |  |  |  |

### `studio_review_task`

| Column | Type | Required | Key | Refers to |
| --- | --- | --- | --- | --- |
| `review_task_id` | INTEGER | yes | PK |  |
| `pack_id` | INTEGER | yes | FK | `catalogue_pack` |
| `item_id` | INTEGER |  | FK | `catalogue_item` |
| `kind` | TEXT | yes |  |  |
| `status` | TEXT | yes |  |  |
| `summary` | TEXT | yes |  |  |
| `detail` | TEXT |  |  |  |
| `attempt_id` | INTEGER |  | FK | `study_attempt` (on delete set null) |
| `raised_by_learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `raised_at` | TEXT | yes |  |  |
| `resolved_by_learner_id` | INTEGER |  | FK | `identity_learner` (on delete set null) |
| `resolved_at` | TEXT |  |  |  |
| `resolution_note` | TEXT |  |  |  |
