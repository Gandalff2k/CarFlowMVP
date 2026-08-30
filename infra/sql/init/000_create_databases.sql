-- Each service gets its own logical database on the shared local Postgres
-- instance (no cross-service schema sharing), created once when the
-- container's data volume is first initialized.
CREATE DATABASE auth;
