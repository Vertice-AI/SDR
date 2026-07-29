-- A Evolution API (dev/homologação, ADR-003) mantém seu próprio schema via
-- Prisma, separado do banco de negócio `sdr`. Roda uma vez, na primeira
-- inicialização do volume do Postgres.
CREATE DATABASE evolution;
