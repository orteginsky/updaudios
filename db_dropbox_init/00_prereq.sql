-- Crea roles de Cloud SQL que no existen en PostgreSQL local.
-- Este script corre antes que backup_dropbox.sql (orden alfabético).
DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'cloudsqlsuperuser') THEN
    CREATE ROLE cloudsqlsuperuser;
  END IF;
END
$$;
