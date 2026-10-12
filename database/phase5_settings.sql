-- OPTIONAL. Phase 5 works without this file because the code has defaults.
-- Safe to run more than once (INSERT IGNORE skips rows that already exist).
USE gymfit;

INSERT IGNORE INTO gym_settings (setting_key, setting_value, description) VALUES
  ('auto_checkout_hours', '8', 'A visit still open after this many hours counts as a forgotten check-out');

-- Settings you already have from schema.sql and that attendance now uses:
--   grace_period_days      days after a membership ends when entry is still allowed (0 = none)
--   allow_checkin_unpaid   'false' = a member with an unpaid or part-paid membership fee cannot enter
-- Example: allow 2 days of grace and let unpaid members in:
--   UPDATE gym_settings SET setting_value = '2'    WHERE setting_key = 'grace_period_days';
--   UPDATE gym_settings SET setting_value = 'true' WHERE setting_key = 'allow_checkin_unpaid';
