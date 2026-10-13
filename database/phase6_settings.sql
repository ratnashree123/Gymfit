-- OPTIONAL. Phase 6 works without this file because the code has a default of 7 days.
-- Safe to run more than once (INSERT IGNORE skips rows that already exist).
USE gymfit;

INSERT IGNORE INTO gym_settings (setting_key, setting_value, description) VALUES
  ('maintenance_alert_days', '7', 'Warn this many days before equipment maintenance is due');

-- Example: warn two weeks ahead
--   UPDATE gym_settings SET setting_value = '14' WHERE setting_key = 'maintenance_alert_days';
