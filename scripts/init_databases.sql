-- Executed only by PostgreSQL on a new Docker volume. Existing data is preserved.
SELECT 'CREATE DATABASE vit_research_app OWNER vit_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='vit_research_app')\gexec
SELECT 'CREATE DATABASE vit_research_test OWNER vit_app'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname='vit_research_test')\gexec
