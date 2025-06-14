-- Enable the necessary extension for UUID generation
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Create the database user
CREATE USER verideal_user WITH PASSWORD 'verideal';

-- 2. Create the database
CREATE DATABASE verideal
  WITH OWNER verideal_user
       ENCODING 'UTF8'
       TABLESPACE pg_default;

\connect verideal

-- 3. Create the users table with UUID v4 primary key
CREATE TABLE users (
  id             UUID PRIMARY KEY
                   DEFAULT gen_random_uuid(),
  first_name     VARCHAR(100)    NOT NULL,
  last_name      VARCHAR(100)    NOT NULL,
  email          VARCHAR(255)    NOT NULL UNIQUE,
  address        TEXT,
  phone_number   VARCHAR(20),
  work_phone_number VARCHAR(20),
  company_name   VARCHAR(255)
);

-- 4. Create the roles table with UUID v4 primary key and UUID foreign key
CREATE TABLE roles (
  id      UUID PRIMARY KEY
             DEFAULT gen_random_uuid(),
  role    VARCHAR(100) NOT NULL,
  user_id UUID         NOT NULL
             REFERENCES users(id)
             ON DELETE CASCADE
);

-- 5. Create the deals table (already using UUID v4)
CREATE TABLE deals (
  id                   UUID         PRIMARY KEY
                        DEFAULT gen_random_uuid(),
  customer_email       VARCHAR(255) NOT NULL,
  customer_website     VARCHAR(255) NOT NULL,
  deal_value           NUMERIC(12,2) NOT NULL,
  arr                  NUMERIC(12,2) NOT NULL,
  product_sold         VARCHAR(255) NOT NULL,
  description          TEXT         NOT NULL,
  deal_cycle_length    INTEGER      NOT NULL,
  rate_me              INTEGER      NOT NULL,
  sales_agent          VARCHAR(255) NOT NULL,
  verified_by          VARCHAR(255) NOT NULL,
  verified             BOOLEAN      NOT NULL DEFAULT FALSE,
  verified_at          TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  display_verified_at  BOOLEAN      NOT NULL DEFAULT FALSE,
  display_verified_by  BOOLEAN      NOT NULL DEFAULT FALSE,
  sales_trainer        VARCHAR(255) NOT NULL,
  sales_manager        VARCHAR(255) NOT NULL,
  created_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  updated_at           TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
  closed_at            TIMESTAMPTZ,
  closed               BOOLEAN      NOT NULL DEFAULT FALSE
);

-- 6. Grant privileges to the application user
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO verideal_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO verideal_user;
