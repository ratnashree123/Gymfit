-- OPTIONAL. Phase 8 works without this file because the code has defaults.
-- Safe to run more than once (INSERT IGNORE skips rows that already exist).
USE gymfit;

INSERT IGNORE INTO gym_settings (setting_key, setting_value, description) VALUES
  ('notification_expired_days', '30', 'Only alert about memberships that ended within this many days');

-- Settings you already have and that notifications and the dashboard use:
--   expiry_alert_days        warn this many days before a membership ends (default 7)
--   maintenance_alert_days   warn this many days before equipment maintenance is due (default 7)
--   currency_symbol          shown in payment notifications
