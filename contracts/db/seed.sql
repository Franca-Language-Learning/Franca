-- Reference data that belongs to the app, not to a pack. Loaded by the first migration.
-- Changing these rows is a schema change and needs a migration.

INSERT INTO catalogue_licence (licence_code, name, url, shareable) VALUES
    ('owned-copy',     'Copy owned by the household, for private use', NULL, 0),
    ('franca-original','Written for Franca', NULL, 1),
    ('public-domain',  'Public domain', NULL, 1),
    ('CC0-1.0',        'Creative Commons Zero 1.0', 'https://creativecommons.org/publicdomain/zero/1.0/', 1),
    ('CC-BY-4.0',      'Creative Commons Attribution 4.0', 'https://creativecommons.org/licenses/by/4.0/', 1),
    ('CC-BY-SA-4.0',   'Creative Commons Attribution-ShareAlike 4.0', 'https://creativecommons.org/licenses/by-sa/4.0/', 1),
    ('int-noncommercial', 'INT licence for non-commercial use (Wablieft corpus), for the licensee''s own study', 'https://taalmaterialen.ivdnt.org/', 0);

-- From the activity table in the course design and pedagogy document. response: what the learner gives.
-- auto_graded: a typed answer can be graded without the learner rating it.
INSERT INTO catalogue_activity_type (activity_type, name_en, strand, response, needs_microphone, needs_handwriting, auto_graded) VALUES
    ('scene_video',       'Scene video',                    'input',          'recognition', 0, 0, 1),
    ('graded_story',      'Graded story',                   'input',          'recognition', 0, 0, 1),
    ('listen_and_do',     'Listen and do',                  'input',          'recognition', 0, 0, 1),
    ('rule_card',         'Rule card',                      'language_focus', 'none',        0, 0, 0),
    ('worked_example',    'Worked example',                 'language_focus', 'production',  0, 0, 1),
    ('rule_discovery',    'Rule discovery',                 'language_focus', 'recognition', 0, 0, 1),
    ('self_explanation',  'Self-explanation prompt',        'language_focus', 'recognition', 0, 0, 1),
    ('structured_input',  'Structured input',               'language_focus', 'recognition', 0, 0, 1),
    ('noticing',          'Noticing',                       'language_focus', 'recognition', 0, 0, 1),
    ('retrieval_card',    'Retrieval card',                 'language_focus', 'production',  0, 0, 1),
    ('picture_card',      'Picture card',                   'language_focus', 'production',  0, 0, 1),
    ('cloze',             'Cloze in context',               'language_focus', 'production',  0, 0, 1),
    ('sentence_building', 'Sentence building',              'language_focus', 'production',  0, 0, 1),
    ('sentence_workshop', 'Sentence workshop',              'output',         'production',  0, 0, 1),
    ('dictation',         'Dictation',                      'language_focus', 'production',  0, 0, 1),
    ('sound_contrast',    'Sound contrast',                 'language_focus', 'recognition', 0, 0, 1),
    ('script_practice',   'Script practice',                'language_focus', 'production',  0, 0, 1),
    ('shadowing',         'Shadowing',                      'output',         'production',  1, 0, 0),
    ('translation',       'Translation',                    'language_focus', 'production',  0, 0, 1),
    ('find_and_fix',      'Find and fix',                   'language_focus', 'production',  0, 0, 1),
    ('gender_drill',      'Gender, class or measure-word drill', 'language_focus', 'recognition', 0, 0, 1),
    ('paradigm_practice', 'Paradigm practice (conjugation drill)', 'language_focus', 'production', 0, 0, 1),
    ('prompted_speaking', 'Prompted speaking',              'output',         'production',  1, 0, 0),
    ('role_play',         'Role-play',                      'output',         'production',  0, 0, 0),
    ('partner_task',      'Partner task',                   'output',         'production',  0, 0, 0),
    ('guided_writing',    'Guided writing',                 'output',         'production',  0, 0, 0),
    ('information_gap',   'Information gap',                'output',         'production',  0, 0, 0),
    ('mediation',         'Mediation',                      'output',         'production',  0, 0, 0),
    ('genre_task',        'Genre task',                     'output',         'production',  0, 0, 0),
    ('talk_4_3_2',        '4/3/2 talk',                     'fluency',        'production',  1, 0, 0),
    ('timed_rereading',   'Timed rereading',                'fluency',        'none',        0, 0, 0),
    ('review_sprint',     'Review sprint',                  'fluency',        'production',  0, 0, 1),
    ('speed_listening',   'Speed listening',                'fluency',        'recognition', 0, 0, 1);

-- The games from the course design section Games and puzzles (22 November 2026). Answers count as reviews under
-- the mixed-run rules. Sentence building (Zinsbouw) and the sound game (Wat hoor je?) are the activity types
-- sentence_building and sound_contrast shown in game form, so they have no rows of their own.
INSERT INTO catalogue_activity_type (activity_type, name_en, strand, response, needs_microphone, needs_handwriting, auto_graded, game) VALUES
    ('crossword',         'Crossword (Kruiswoord)',                    'language_focus', 'production',  0, 0, 1, 1),
    ('collocation_match', 'Collocation match (Welk werkwoord?)',       'language_focus', 'production',  0, 0, 1, 1),
    ('odd_one_out',       'Odd one out (Wat hoort er niet bij?)',      'language_focus', 'recognition', 0, 0, 1, 1),
    ('article_sort',      'Article sorting (De of het?)',              'fluency',        'recognition', 0, 0, 1, 1),
    ('memory_game',       'Memory',                                    'language_focus', 'recognition', 0, 0, 1, 1),
    ('guess_the_word',    'Guess the word (Raad het woord)',           'output',         'production',  0, 0, 0, 1),
    ('story_game',        'Story game (Avontuur)',                     'input',          'recognition', 0, 0, 1, 1);

-- Interface element keys from round 6 (EL1). Names in the pack's language are taken from the pack.
INSERT INTO catalogue_ui_element (element_key, name_en, description) VALUES
    ('course',        'Course',        'Main menu: the course home with Vandaag and the unit list'),
    ('practise',      'Practise',      'Main menu: the practice tab'),
    ('words',         'Words',         'Main menu: words, dictionary and verb reference'),
    ('library',       'Library',       'Main menu: the private library'),
    ('conversations', 'Conversations', 'Main menu: AI and partner conversations'),
    ('notes',         'Notes',         'Main menu: the notebook'),
    ('more',          'More',          'Phone bar: the menu with the remaining sections'),
    ('progress',      'Progress',      'Progress screens'),
    ('together',      'Together',      'Samen: what the two learners share and do together'),
    ('settings',      'Settings',      'Settings'),
    ('today',         'Today',         'The daily plan at the top of the course home'),
    ('review',        'Review',        'The review part of the daily plan'),
    ('lookups',       'Looked up',     'Words and sentences looked up, added to the next review'),
    ('mix',           'Mixed',         'The mixed run on the practice tab'),
    ('flashcards',    'Flashcards',    'Picture and word cards'),
    ('step_by_step',  'Step by step',  'Second rung of the help ladder: the decision steps'),
    ('hint',          'Hint',          'First rung of the help ladder'),
    ('answer',        'Answer',        'Third rung of the help ladder'),
    ('to_check',      'To check',      'The owner''s review queue (Te controleren)'),
    ('transcript',    'Transcript',    'Transcript panel in listening'),
    ('listen_n',      'Listen',        'Listen counter in the listening step');

INSERT INTO catalogue_error_type (error_type, name_en) VALUES
    ('word_order',    'Word order'),
    ('agreement',     'Agreement'),
    ('gender',        'Gender or article'),
    ('tense',         'Tense'),
    ('verb_form',     'Verb form'),
    ('spelling',      'Spelling'),
    ('word_choice',   'Word choice'),
    ('missing_word',  'Missing word'),
    ('extra_word',    'Extra word'),
    ('register',      'Register'),
    ('vowel',         'Pronunciation: vowel'),
    ('consonant',     'Pronunciation: consonant'),
    ('prosody',       'Pronunciation: stress or intonation');

-- Goal list of 21 November 2026, from the pedagogy and syllabus reviews. Pack names come from catalogue_goal_v.
INSERT INTO study_goal (goal_key, name_en, description_en, followup, position) VALUES
    ('living', 'Daily life and services', 'Shops, neighbours, getting around, the doctor, the town hall, the bank', NULL, 1),
    ('social', 'Family and friends', 'Talking with family, friends and other parents', NULL, 2),
    ('travel', 'Travel', 'Trips in Flanders, Brussels and the Netherlands', NULL, 3),
    ('work',   'Work', 'Speaking and writing at work, and looking for work', NULL, 4),
    ('study',  'Study and courses', 'Following a course or training in Dutch', NULL, 5),
    ('media',  'Books, TV, radio and podcasts', 'Reading and listening for pleasure', NULL, 6),
    ('exam',   'An exam or official test', 'Practice in the format of a named exam', 'exam', 7),
    ('field',  'A subject I work in or care about', 'Word lists from A2, reading and tasks from B1', 'field', 8);

INSERT INTO study_tour_part (tour_part_key, name_en, position) VALUES
    ('listen_first',    'Listening before reading', 1),
    ('look_up',         'Looking things up', 2),
    ('try_first',       'Trying before asking for help', 3),
    ('spaced_review',   'Reviewing at the right moment', 4),
    ('speak_and_write', 'Speaking and writing', 5),
    ('daily_plan',      'The daily plan', 6);

-- Item kinds. The detail table for each kind is listed in build_schema.py (ENTITY_KIND).
INSERT INTO catalogue_item_kind (kind, description) VALUES
    ('lexeme',         'A word (lemma), described in catalogue_lexeme_v'),
    ('sense',          'One meaning of a word, catalogue_sense_v'),
    ('chunk',          'A phrase taught as a whole, catalogue_chunk_v'),
    ('grammar_point',  'A node in the grammar graph, catalogue_grammar_point_v'),
    ('rule',           'A rule with steps, catalogue_rule_v'),
    ('rule_step',      'One step of a rule, catalogue_rule_step_v'),
    ('sound',          'A phoneme or tone, catalogue_sound_v'),
    ('sound_contrast', 'Two sounds trained as a pair, catalogue_sound_contrast_v'),
    ('can_do',         'A CEFR can-do descriptor, catalogue_can_do_v'),
    ('course_node',    'A level, stage, unit, lesson or module, catalogue_course_node_v'),
    ('activity',       'An exercise or text, catalogue_activity_v'),
    ('scenario',       'A role-play situation, catalogue_scenario_v');

-- Model prices on 21 November 2026, in micro-dollars per million tokens
-- (https://platform.claude.com/en/docs/about-claude/pricing). Mistral prices are added when
-- the fallback account is opened; until then the limiter refuses calls to a model with no price.
INSERT INTO ai_price (provider, model, min_prompt_tokens, input, output, cache_write_5m, cache_write_1h, cache_read, valid_from, source_url) VALUES
    ('anthropic', 'claude-sonnet-5-5',      0, 2000000, 10000000, 2500000, 4000000, 100000, '2026-11-21', 'https://platform.claude.com/en/docs/about-claude/pricing'),
    ('anthropic', 'claude-haiku-5-5',       0,  100000,   500000,  125000,  200000,  10000, '2026-11-21', 'https://platform.claude.com/en/docs/about-claude/pricing'),
    ('anthropic', 'claude-haiku-5-5', 100001,   500000,  2500000,  625000, 1000000,  50000, '2026-11-21', 'https://platform.claude.com/en/docs/about-claude/pricing');

-- First spending limits, chosen on 21 November 2026 (see spec/ai_budget.py for the estimate):
-- learning 40 dollars a month with 3 dollars per learner per day; content jobs 60 dollars a month.
INSERT INTO ai_budget (category, monthly_limit_microusd, learner_daily_limit_microusd, valid_from) VALUES
    ('learning', 40000000, 3000000, '2026-11-21T00:00:00.000Z'),
    ('content',  60000000, NULL,    '2026-11-21T00:00:00.000Z');
