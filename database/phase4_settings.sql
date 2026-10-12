-- OPTIONAL. Phase 4 works without this file because the code has defaults.
-- Run it in MySQL Workbench only if you want to change these values later.
-- Safe to run more than once (INSERT IGNORE skips rows that already exist).
USE gymfit;

INSERT IGNORE INTO gym_settings (setting_key, setting_value, description) VALUES
  ('invoice_due_days',                   '7',  'Days after issue when an unpaid invoice becomes overdue'),
  ('max_receptionist_discount_percent',  '10', 'Largest discount (%) a Receptionist may give; Admins have no limit'),
  ('currency_symbol',                    '₹',  'Shown on receipts');

-- To charge tax (for example 18 percent GST) run:
--   UPDATE gym_settings SET setting_value = '18' WHERE setting_key = 'tax_percent';
-- To require full payment only:
--   UPDATE gym_settings SET setting_value = 'false' WHERE setting_key = 'allow_partial_payments';
