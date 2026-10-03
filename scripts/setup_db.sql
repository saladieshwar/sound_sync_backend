-- One-time local database bring-up. Run as the postgres superuser:
--   psql -U postgres -h localhost -v app_password='your_password' -f scripts/setup_db.sql
-- The password must match DATABASE_URL in .env.

SELECT format('CREATE ROLE soundsync LOGIN PASSWORD %L', :'app_password')
WHERE NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'soundsync')
\gexec

SELECT format('ALTER ROLE soundsync PASSWORD %L', :'app_password')
\gexec

SELECT 'CREATE DATABASE soundsync OWNER soundsync'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'soundsync')
\gexec

ALTER DATABASE soundsync OWNER TO soundsync;
