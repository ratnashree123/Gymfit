-- =====================================================================
-- GymFit database schema (MySQL 8.0.13+)
-- Run once. Timestamps are stored in UTC.
-- =====================================================================
CREATE DATABASE IF NOT EXISTS gymfit
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE gymfit;

-- ---------------------------------------------------------------------
-- 1. ROLES & USERS
-- ---------------------------------------------------------------------
CREATE TABLE roles (
  id          TINYINT UNSIGNED NOT NULL AUTO_INCREMENT,
  name        VARCHAR(30) NOT NULL,
  description VARCHAR(255) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_roles_name (name)
) ENGINE=InnoDB;

CREATE TABLE users (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  role_id       TINYINT UNSIGNED NOT NULL,
  full_name     VARCHAR(120) NOT NULL,
  email         VARCHAR(150) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  last_login_at DATETIME NULL,
  created_at    DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  updated_at    DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  UNIQUE KEY uq_users_email (email),
  KEY ix_users_role (role_id),
  CONSTRAINT fk_users_role FOREIGN KEY (role_id) REFERENCES roles (id)
) ENGINE=InnoDB;

CREATE TABLE staff_profiles (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id          INT UNSIGNED NOT NULL,
  phone            VARCHAR(20) NOT NULL,
  address          VARCHAR(255) NULL,
  specialization   VARCHAR(120) NULL,
  working_schedule VARCHAR(255) NULL,
  hire_date        DATE NULL,
  salary           DECIMAL(10,2) NULL,
  status           ENUM('active','on_leave','inactive') NOT NULL DEFAULT 'active',
  created_at       DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  UNIQUE KEY uq_staff_user (user_id),
  KEY ix_staff_status (status),
  CONSTRAINT fk_staff_user FOREIGN KEY (user_id) REFERENCES users (id),
  CONSTRAINT ck_staff_salary CHECK (salary IS NULL OR salary >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 2. MEMBERS
-- ---------------------------------------------------------------------
CREATE TABLE members (
  id                      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  member_code             VARCHAR(20) NOT NULL,          -- e.g. GF-000001
  full_name               VARCHAR(120) NOT NULL,
  phone                   VARCHAR(20) NOT NULL,
  email                   VARCHAR(150) NULL,
  gender                  ENUM('male','female','other') NULL,
  date_of_birth           DATE NULL,
  address                 VARCHAR(255) NULL,
  emergency_contact_name  VARCHAR(120) NULL,
  emergency_contact_phone VARCHAR(20) NULL,
  photo_path              VARCHAR(255) NULL,
  medical_notes           TEXT NULL,                     -- voluntary, restricted by role
  registration_date       DATE NOT NULL,
  status                  ENUM('active','inactive') NOT NULL DEFAULT 'active',
  assigned_trainer_id     INT UNSIGNED NULL,
  is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
  created_by              INT UNSIGNED NULL,
  created_at              DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  updated_at              DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  UNIQUE KEY uq_members_code (member_code),
  UNIQUE KEY uq_members_phone (phone),                   -- blocks duplicate registrations
  KEY ix_members_name (full_name),
  KEY ix_members_status (status, is_deleted),
  KEY ix_members_trainer (assigned_trainer_id),
  CONSTRAINT fk_members_trainer FOREIGN KEY (assigned_trainer_id) REFERENCES staff_profiles (id) ON DELETE SET NULL,
  CONSTRAINT fk_members_creator FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 3. PLANS, MEMBERSHIPS, INVOICES, PAYMENTS
-- ---------------------------------------------------------------------
CREATE TABLE membership_plans (
  id            INT UNSIGNED NOT NULL AUTO_INCREMENT,
  name          VARCHAR(100) NOT NULL,
  plan_type     ENUM('membership','addon') NOT NULL DEFAULT 'membership',
  duration_days INT UNSIGNED NOT NULL,
  price         DECIMAL(10,2) NOT NULL,
  description   VARCHAR(255) NULL,
  benefits      TEXT NULL,
  is_active     BOOLEAN NOT NULL DEFAULT TRUE,
  created_at    DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  UNIQUE KEY uq_plans_name (name),
  CONSTRAINT ck_plans_price CHECK (price >= 0),
  CONSTRAINT ck_plans_duration CHECK (duration_days > 0)
) ENGINE=InnoDB;

CREATE TABLE memberships (
  id                 INT UNSIGNED NOT NULL AUTO_INCREMENT,
  member_id          INT UNSIGNED NOT NULL,
  plan_id            INT UNSIGNED NOT NULL,
  start_date         DATE NOT NULL,
  end_date           DATE NOT NULL,
  price_at_purchase  DECIMAL(10,2) NOT NULL,             -- keeps history correct if plan price changes
  is_renewal         BOOLEAN NOT NULL DEFAULT FALSE,
  status             ENUM('active','expired','cancelled') NOT NULL DEFAULT 'active',
  created_by         INT UNSIGNED NULL,
  created_at         DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  KEY ix_memberships_member (member_id),
  KEY ix_memberships_end (end_date),
  KEY ix_memberships_status (status),
  CONSTRAINT fk_ms_member  FOREIGN KEY (member_id) REFERENCES members (id),
  CONSTRAINT fk_ms_plan    FOREIGN KEY (plan_id)   REFERENCES membership_plans (id),
  CONSTRAINT fk_ms_creator FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT ck_ms_dates CHECK (end_date >= start_date)
) ENGINE=InnoDB;

CREATE TABLE invoices (
  id             INT UNSIGNED NOT NULL AUTO_INCREMENT,
  invoice_number VARCHAR(30) NOT NULL,
  member_id      INT UNSIGNED NOT NULL,
  membership_id  INT UNSIGNED NULL,
  invoice_type   ENUM('membership','renewal','personal_training','other') NOT NULL,
  subtotal       DECIMAL(10,2) NOT NULL,
  discount_amount DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  tax_amount     DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  total_amount   DECIMAL(10,2) NOT NULL,
  status         ENUM('pending','partial','paid','cancelled') NOT NULL DEFAULT 'pending',
  due_date       DATE NULL,
  issued_at      DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  created_by     INT UNSIGNED NULL,
  notes          VARCHAR(255) NULL,
  PRIMARY KEY (id),
  UNIQUE KEY uq_invoices_number (invoice_number),
  KEY ix_invoices_member (member_id),
  KEY ix_invoices_status_due (status, due_date),
  CONSTRAINT fk_inv_member     FOREIGN KEY (member_id) REFERENCES members (id),
  CONSTRAINT fk_inv_membership FOREIGN KEY (membership_id) REFERENCES memberships (id),
  CONSTRAINT fk_inv_creator    FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT ck_inv_amounts CHECK (subtotal >= 0 AND discount_amount >= 0 AND tax_amount >= 0 AND total_amount >= 0)
) ENGINE=InnoDB;

CREATE TABLE payments (
  id                INT UNSIGNED NOT NULL AUTO_INCREMENT,
  receipt_number    VARCHAR(30) NOT NULL,
  invoice_id        INT UNSIGNED NOT NULL,
  member_id         INT UNSIGNED NOT NULL,
  amount            DECIMAL(10,2) NOT NULL,
  method            ENUM('cash','upi','card','bank_transfer') NOT NULL,
  verification_type ENUM('manual','verified_online') NOT NULL DEFAULT 'manual',
  reference_no      VARCHAR(100) NULL,                   -- UPI ref / card slip / bank txn id
  payment_date      DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  received_by       INT UNSIGNED NULL,
  notes             VARCHAR(255) NULL,
  created_at        DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  UNIQUE KEY uq_payments_receipt (receipt_number),
  KEY ix_payments_invoice (invoice_id),
  KEY ix_payments_member (member_id),
  KEY ix_payments_date (payment_date),
  CONSTRAINT fk_pay_invoice  FOREIGN KEY (invoice_id) REFERENCES invoices (id),
  CONSTRAINT fk_pay_member   FOREIGN KEY (member_id)  REFERENCES members (id),
  CONSTRAINT fk_pay_receiver FOREIGN KEY (received_by) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT ck_pay_amount CHECK (amount > 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 4. ATTENDANCE
-- ---------------------------------------------------------------------
CREATE TABLE attendance (
  id               BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  member_id        INT UNSIGNED NOT NULL,
  check_in_at      DATETIME NOT NULL,
  check_out_at     DATETIME NULL,
  duration_minutes INT UNSIGNED NULL,
  status           ENUM('inside','completed','auto_closed','corrected') NOT NULL DEFAULT 'inside',
  checked_in_by    INT UNSIGNED NULL,
  checked_out_by   INT UNSIGNED NULL,
  notes            VARCHAR(255) NULL,
  -- Equals member_id only while the member is inside; NULL after checkout.
  -- UNIQUE on it => one open visit per member, enforced by MySQL itself.
  open_member_id   INT UNSIGNED GENERATED ALWAYS AS (IF(check_out_at IS NULL, member_id, NULL)) STORED,
  PRIMARY KEY (id),
  UNIQUE KEY uq_attendance_one_open (open_member_id),
  KEY ix_attendance_member_date (member_id, check_in_at),
  KEY ix_attendance_checkin (check_in_at),
  CONSTRAINT fk_att_member FOREIGN KEY (member_id) REFERENCES members (id),
  CONSTRAINT fk_att_in_by  FOREIGN KEY (checked_in_by)  REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT fk_att_out_by FOREIGN KEY (checked_out_by) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT ck_att_times CHECK (check_out_at IS NULL OR check_out_at >= check_in_at)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 5. EQUIPMENT
-- ---------------------------------------------------------------------
CREATE TABLE equipment (
  id                      INT UNSIGNED NOT NULL AUTO_INCREMENT,
  equipment_code          VARCHAR(20) NOT NULL,          -- e.g. EQ-0001
  name                    VARCHAR(120) NOT NULL,
  category                VARCHAR(60) NOT NULL,
  brand_model             VARCHAR(120) NULL,
  quantity                INT UNSIGNED NOT NULL DEFAULT 1,
  purchase_date           DATE NULL,
  purchase_price          DECIMAL(10,2) NULL,
  condition_status        ENUM('new','good','fair','poor') NOT NULL DEFAULT 'good',
  location                VARCHAR(100) NULL,
  status                  ENUM('available','damaged','under_maintenance') NOT NULL DEFAULT 'available',
  last_maintenance_date   DATE NULL,
  next_maintenance_date   DATE NULL,
  notes                   TEXT NULL,
  is_archived             BOOLEAN NOT NULL DEFAULT FALSE,
  created_at              DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  updated_at              DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  UNIQUE KEY uq_equipment_code (equipment_code),
  KEY ix_equipment_status (status, is_archived),
  KEY ix_equipment_next_maint (next_maintenance_date),
  CONSTRAINT ck_eq_price CHECK (purchase_price IS NULL OR purchase_price >= 0)
) ENGINE=InnoDB;

CREATE TABLE equipment_maintenance (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  equipment_id     INT UNSIGNED NOT NULL,
  maintenance_type ENUM('routine','repair','inspection') NOT NULL DEFAULT 'routine',
  status           ENUM('scheduled','in_progress','completed','cancelled') NOT NULL DEFAULT 'scheduled',
  scheduled_date   DATE NOT NULL,
  performed_date   DATE NULL,
  cost             DECIMAL(10,2) NOT NULL DEFAULT 0.00,
  performed_by     VARCHAR(120) NULL,
  description      TEXT NULL,
  created_by       INT UNSIGNED NULL,
  created_at       DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  KEY ix_maint_equipment (equipment_id),
  KEY ix_maint_status_date (status, scheduled_date),
  CONSTRAINT fk_maint_equipment FOREIGN KEY (equipment_id) REFERENCES equipment (id),
  CONSTRAINT fk_maint_creator   FOREIGN KEY (created_by) REFERENCES users (id) ON DELETE SET NULL,
  CONSTRAINT ck_maint_cost CHECK (cost >= 0)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 6. WORKOUTS & PROGRESS
-- ---------------------------------------------------------------------
CREATE TABLE workout_plans (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT,
  member_id   INT UNSIGNED NOT NULL,
  trainer_id  INT UNSIGNED NULL,
  title       VARCHAR(120) NOT NULL,
  goal        VARCHAR(255) NULL,
  start_date  DATE NOT NULL,
  end_date    DATE NULL,
  status      ENUM('active','completed','archived') NOT NULL DEFAULT 'active',
  notes       TEXT NULL,
  created_at  DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  KEY ix_wplans_member (member_id),
  CONSTRAINT fk_wplan_member  FOREIGN KEY (member_id)  REFERENCES members (id),
  CONSTRAINT fk_wplan_trainer FOREIGN KEY (trainer_id) REFERENCES staff_profiles (id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE workout_exercises (
  id               INT UNSIGNED NOT NULL AUTO_INCREMENT,
  plan_id          INT UNSIGNED NOT NULL,
  day_number       TINYINT UNSIGNED NOT NULL,            -- 1 = Day 1 ... 7
  muscle_group     VARCHAR(60) NOT NULL,
  exercise_name    VARCHAR(120) NOT NULL,
  sets             SMALLINT UNSIGNED NULL,
  reps             SMALLINT UNSIGNED NULL,
  duration_minutes SMALLINT UNSIGNED NULL,
  rest_seconds     SMALLINT UNSIGNED NULL,
  sort_order       SMALLINT UNSIGNED NOT NULL DEFAULT 0,
  notes            VARCHAR(255) NULL,
  PRIMARY KEY (id),
  KEY ix_wex_plan_day (plan_id, day_number),
  CONSTRAINT fk_wex_plan FOREIGN KEY (plan_id) REFERENCES workout_plans (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE member_progress (
  id           INT UNSIGNED NOT NULL AUTO_INCREMENT,
  member_id    INT UNSIGNED NOT NULL,
  recorded_on  DATE NOT NULL,
  weight_kg    DECIMAL(5,2) NULL,
  height_cm    DECIMAL(5,1) NULL,
  body_fat_pct DECIMAL(4,1) NULL,
  chest_cm     DECIMAL(5,1) NULL,
  waist_cm     DECIMAL(5,1) NULL,
  hips_cm      DECIMAL(5,1) NULL,
  goal         VARCHAR(255) NULL,
  notes        VARCHAR(255) NULL,
  recorded_by  INT UNSIGNED NULL,
  created_at   DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  KEY ix_progress_member_date (member_id, recorded_on),
  CONSTRAINT fk_prog_member   FOREIGN KEY (member_id) REFERENCES members (id),
  CONSTRAINT fk_prog_recorder FOREIGN KEY (recorded_by) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 7. NOTIFICATIONS, AUDIT, SETTINGS
-- ---------------------------------------------------------------------
CREATE TABLE notifications (
  id           BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id      INT UNSIGNED NULL,                        -- NULL = visible to all staff
  type         ENUM('membership_expiring','membership_expired','payment_pending','maintenance_due','system') NOT NULL,
  title        VARCHAR(150) NOT NULL,
  message      VARCHAR(255) NOT NULL,
  related_type VARCHAR(40) NULL,
  related_id   INT UNSIGNED NULL,
  is_read      BOOLEAN NOT NULL DEFAULT FALSE,
  created_at   DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  KEY ix_notif_user_read (user_id, is_read),
  KEY ix_notif_created (created_at),
  CONSTRAINT fk_notif_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE CASCADE
) ENGINE=InnoDB;

CREATE TABLE audit_logs (
  id          BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id     INT UNSIGNED NULL,
  action      VARCHAR(60) NOT NULL,                      -- e.g. member.update, attendance.correct
  entity_type VARCHAR(40) NOT NULL,
  entity_id   INT UNSIGNED NULL,
  old_values  JSON NULL,
  new_values  JSON NULL,
  ip_address  VARCHAR(45) NULL,
  created_at  DATETIME NOT NULL DEFAULT (UTC_TIMESTAMP()),
  PRIMARY KEY (id),
  KEY ix_audit_entity (entity_type, entity_id),
  KEY ix_audit_user (user_id),
  KEY ix_audit_created (created_at),
  CONSTRAINT fk_audit_user FOREIGN KEY (user_id) REFERENCES users (id) ON DELETE SET NULL
) ENGINE=InnoDB;

CREATE TABLE gym_settings (
  setting_key   VARCHAR(60) NOT NULL,
  setting_value VARCHAR(255) NOT NULL,
  description   VARCHAR(255) NULL,
  PRIMARY KEY (setting_key)
) ENGINE=InnoDB;

-- ---------------------------------------------------------------------
-- 8. REQUIRED REFERENCE DATA (safe for production: no credentials here)
-- ---------------------------------------------------------------------
INSERT INTO roles (name, description) VALUES
  ('Admin',        'Full access to all modules'),
  ('Receptionist', 'Members, payments, attendance'),
  ('Trainer',      'Assigned members, workout plans, progress');

INSERT INTO gym_settings (setting_key, setting_value, description) VALUES
  ('gym_name',                'GymFit',      'Name shown on receipts'),
  ('timezone',                'Asia/Kolkata','Display timezone'),
  ('tax_percent',             '0',           'Default tax % applied to invoices'),
  ('allow_partial_payments',  'true',        'Allow paying an invoice in parts'),
  ('expiry_alert_days',       '7',           'Days before expiry to raise alerts'),
  ('grace_period_days',       '0',           'Days after expiry check-in is still allowed'),
  ('allow_checkin_unpaid',    'false',       'Allow check-in when invoice is pending');
