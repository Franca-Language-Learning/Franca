-- The main read paths, kept in one place so that their use of indexes can be tested.
-- Parameters are named (:name). These queries, or equivalent SQLAlchemy statements, are
-- used in the study engine. In test_queries.py it is checked that each query runs and that
-- no table is read from start to end.

-- name: due_reviews
-- Cards due now for one course, oldest due first. Cards for items that are not in the
-- active pack version are left out.
SELECT c.card_id, c.item_id, c.direction, c.form_type, c.due_at, c.stability, c.difficulty
FROM memory_card c
JOIN study_enrolment e ON e.enrolment_id = c.enrolment_id
JOIN catalogue_active_version a ON a.pack_id = e.pack_id
WHERE c.enrolment_id = :enrolment_id AND c.suspended_at IS NULL AND c.state <> 'new' AND c.due_at <= :now
  AND EXISTS (SELECT 1 FROM catalogue_version_item vi
              WHERE vi.pack_version_id = a.pack_version_id AND vi.item_id = c.item_id)
ORDER BY c.due_at
LIMIT :limit;

-- name: bridge_candidates
-- Core items a lesson builds on, with the learner's recall card and its lapses in the last
-- 30 days. A lapse is an Again on a card in review, not corrected by a later row.
-- The thresholds from catalogue_course_config_v are applied in the planner (spec/planner_rules.py).
-- met is 0 when the learner has no card of any direction for the item (a reminder screen).
SELECT li.item_id, li.position, li.prompt_target, li.prompt_cue_en,
       EXISTS (SELECT 1 FROM memory_card m WHERE m.enrolment_id = :enrolment_id AND m.item_id = li.item_id) AS met,
       c.card_id, c.state, c.due_at, c.stability, c.last_review_at,
       (SELECT count(*) FROM memory_review_log r
         WHERE r.card_id = c.card_id AND r.grade = 1 AND r.state_before = 'review'
           AND r.reviewed_at >= :since_30_days
           AND NOT EXISTS (SELECT 1 FROM memory_review_log o WHERE o.corrects_review_id = r.review_id)) AS lapses_30_days
FROM catalogue_active_version a
JOIN catalogue_lesson_item_v li ON li.pack_version_id = a.pack_version_id
LEFT JOIN memory_card c ON c.enrolment_id = :enrolment_id AND c.item_id = li.item_id
                       AND c.direction = 'recall' AND c.suspended_at IS NULL
WHERE a.pack_id = :pack_id AND li.lesson_item_id = :lesson_item_id
  AND li.relation = 'builds_on' AND li.weight = 'core'
ORDER BY li.position;

-- name: mixed_run_updates_today
-- How many times the mixed run has changed the schedule of any card of this item today.
-- The engine compares this with mix_updates_per_item_per_day before it writes a review.
-- During an offline replay, a review over the limit is recorded as an attempt only.
SELECT count(*) AS updates_today
FROM memory_review_log r
JOIN memory_card c ON c.card_id = r.card_id
WHERE c.enrolment_id = :enrolment_id AND c.item_id = :item_id
  AND r.review_day = :today AND r.context = 'practice_mixed' AND r.grade_source <> 'override';

-- name: open_lookups
-- Looked-up words not yet put into a review.
SELECT lookup_id, item_id, query_text, source, looked_up_at
FROM study_lookup
WHERE enrolment_id = :enrolment_id AND reviewed_at IS NULL
ORDER BY looked_up_at;

-- name: verb_chart_by_form
-- Find a verb from any of its forms (zei, opgestaan, komt) and return its chart once.
SELECT v.lexeme_item_id, l.lemma, v.class_key, v.stem, f.cell_key, pc.label_tl, pc.label_en,
       f.variant_no, f.form, f.nonexistent, var.code AS variety
FROM catalogue_active_version a
JOIN catalogue_verb_v v ON v.pack_version_id = a.pack_version_id
 AND v.lexeme_item_id IN (SELECT hit.lexeme_item_id FROM catalogue_form_v hit
                          WHERE hit.pack_version_id = a.pack_version_id AND hit.form = :form)
JOIN catalogue_lexeme_v l ON l.pack_version_id = a.pack_version_id AND l.item_id = v.lexeme_item_id
JOIN catalogue_form_v f ON f.pack_version_id = a.pack_version_id AND f.lexeme_item_id = v.lexeme_item_id
JOIN catalogue_paradigm_cell_v pc ON pc.pack_version_id = a.pack_version_id AND pc.cell_key = f.cell_key
LEFT JOIN catalogue_variety var ON var.variety_id = f.variety_id
WHERE a.pack_id = :pack_id
ORDER BY v.lexeme_item_id, pc.position, f.variant_no;

-- name: mistakes_per_rule
-- The learner's own mistakes with one rule, newest first, and the step where the learner went wrong (VR1).
SELECT a.attempt_id, a.response, a.answered_at, f.step_item_id, f.message_en
FROM checking_feedback f
JOIN study_attempt a ON a.attempt_id = f.attempt_id
JOIN study_session s ON s.session_id = a.session_id
WHERE f.rule_item_id = :rule_item_id AND s.enrolment_id = :enrolment_id
ORDER BY a.answered_at DESC
LIMIT :limit;

-- name: partner_lessons
-- What one learner may see of the other's progress: lessons, if shared.
SELECT p.node_item_id, p.status, p.completed_at
FROM partner_share sh
JOIN study_enrolment e ON e.learner_id = sh.owner_learner_id AND e.pack_id = sh.pack_id
JOIN study_node_progress p ON p.enrolment_id = e.enrolment_id
WHERE sh.viewer_learner_id = :viewer_learner_id AND sh.owner_learner_id = :owner_learner_id
  AND sh.pack_id = :pack_id AND sh.scope = 'lessons';
