"""Explicit stopped-owner additive migration, never an unrestricted Store startup.

The protected gateway supplies a reviewed exact SQL-hash allowlist. Existing rows,
column definitions, constraints and indexes must survive the transaction. New
columns must be nullable and NULL; new tables empty. No data backfill or restore.
"""

from hashlib import sha256
import json
from pathlib import Path
import re
import sys

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

NAME = re.compile(r'[a-z_][a-z_0-9]*\Z')


def catalog(db):
    columns = db.execute("""SELECT table_name,column_name,data_type,udt_name,is_nullable,
        column_default,character_maximum_length,numeric_precision,numeric_scale
        FROM information_schema.columns WHERE table_schema='public'
        ORDER BY table_name,ordinal_position""").fetchall()
    constraints = db.execute("""SELECT c.relname AS table_name,con.conname,pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
        JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public'
        ORDER BY c.relname,con.conname""").fetchall()
    indexes = db.execute("""SELECT tablename AS table_name,indexname,indexdef FROM pg_indexes
        WHERE schemaname='public' ORDER BY tablename,indexname""").fetchall()
    return {'columns': columns, 'constraints': constraints, 'indexes': indexes}


def rows(db, tables, added_columns):
    result = {}
    for table in sorted(tables - {'schema_migrations'}):
        query = sql.SQL("SELECT count(*) AS count,md5(COALESCE(string_agg("
            "md5((to_jsonb(t)-%s::text[])::text),'' ORDER BY md5((to_jsonb(t)-%s::text[])::text)),'')) AS digest "
            "FROM public.{} t").format(sql.Identifier(table))
        excluded = added_columns.get(table, [])
        result[table] = db.execute(query, (excluded, excluded)).fetchone()
    return result


def migration_files(directory, transition):
    """Pure exact-file/DDL preflight shared with offline enrollment preparation."""
    if set(transition) != {'from', 'to', 'migrations', 'added_tables', 'added_columns'}:
        raise ValueError('Unsupported transition contract')
    old, new = transition['from'], transition['to']
    if type(old) is not int or type(new) is not int or not 0 < old < new:
        raise ValueError('Only an explicitly qualified forward transition is supported')
    additions = transition['added_columns']
    tables_added = set(transition['added_tables'])
    names = [*tables_added, *additions, *(column for columns in additions.values() for column in columns)]
    if not all(isinstance(name, str) and NAME.fullmatch(name) for name in names):
        raise ValueError('Invalid additive schema projection')
    files = sorted(directory.glob('[0-9]*.sql'))
    if [int(path.name.split('_')[0]) for path in files] != list(range(1, new + 1)):
        raise ValueError('Candidate migration history is not contiguous/exact')
    pending = [path for path in files if int(path.name.split('_')[0]) > old]
    if {path.name: sha256(path.read_bytes()).hexdigest() for path in pending} != transition['migrations']:
        raise ValueError('Migration SQL differs from installed allowlist')
    for path in pending:
        statement = path.read_text().strip()
        # This lane deliberately supports one DDL statement per migration, not a
        # general SQL program (transaction control could escape our rollback).
        if not re.fullmatch(r'(?:CREATE TABLE [a-z_][a-z_0-9]*\s*\([^;]+\)|'
                            r'ALTER TABLE [a-z_][a-z_0-9]* ADD COLUMN [a-z_][a-z_0-9]* '
                            r'(?:text|boolean|integer|bigint|timestamptz|jsonb));', statement, re.DOTALL):
            raise ValueError('Migration is outside the narrow additive DDL lane')
    return pending


def migrate(dsn, transition, directory=None):
    directory = directory or Path(__file__).parent / 'migrations'
    pending = migration_files(directory, transition)
    old, new = transition['from'], transition['to']
    additions = transition['added_columns']
    tables_added = set(transition['added_tables'])
    with psycopg.connect(dsn, autocommit=True, row_factory=dict_row) as db:
        if not db.execute('SELECT pg_try_advisory_lock(hashtext(current_database()),20261028) AS held').fetchone()['held']:
            raise ValueError('Store still owns migration target')
        with db.transaction():
            db.execute("SET LOCAL statement_timeout='60s'")
            versions = [row['version'] for row in db.execute('SELECT version FROM schema_migrations ORDER BY version')]
            if versions != list(range(1, old + 1)):
                raise ValueError('Migration source schema differs; no replay')
            before = catalog(db)
            tables = {row['table_name'] for row in before['columns']}
            if tables_added & tables or not set(additions) <= tables - {'schema_migrations'}:
                raise ValueError('Additive projection targets differ')
            retained = rows(db, tables, {})
            for path in pending:
                db.execute(path.read_text(), prepare=False)
                db.execute('INSERT INTO schema_migrations VALUES (%s)', (int(path.name.split('_')[0]),))
            after = catalog(db)
            expected_columns = {(row['table_name'], row['column_name']) for row in before['columns']}
            actual_new = {(row['table_name'], row['column_name']) for row in after['columns']
                          if row['table_name'] in tables} - expected_columns
            if actual_new != {(table, column) for table, columns in additions.items() for column in columns}:
                raise ValueError('Unexpected added/removed columns')
            for kind, definitions in before.items():
                preserved = [row for row in after[kind] if row['table_name'] in tables and
                             not (kind == 'columns' and (row['table_name'], row['column_name']) in actual_new)]
                if preserved != definitions:
                    raise ValueError('Retained schema definition changed')
            if {row['table_name'] for row in after['columns']} != tables | tables_added:
                raise ValueError('Unexpected added/removed tables')
            if rows(db, tables, additions) != retained:
                raise ValueError('Retained rows changed')
            for table in tables_added:
                if db.execute(sql.SQL('SELECT count(*) AS count FROM {}').format(sql.Identifier(table))).fetchone()['count']:
                    raise ValueError('New table contains a backfill')
            for table, column in actual_new:
                definition = next(row for row in after['columns'] if (row['table_name'], row['column_name']) == (table, column))
                if definition['is_nullable'] != 'YES' or definition['column_default'] is not None:
                    raise ValueError('New column is not nullable without default')
                query = sql.SQL('SELECT count(*) AS count FROM {} WHERE {} IS NOT NULL').format(
                    sql.Identifier(table), sql.Identifier(column))
                if db.execute(query).fetchone()['count']:
                    raise ValueError('New column contains a backfill')
    return {'schema': new, 'status': 'migrated'}


if __name__ == '__main__':
    from m2.http_boundary.config import deployment_dsn
    content = sys.stdin.buffer.read(65537)
    if len(content) > 65536:
        raise ValueError('Transition exceeds bound')
    transition = json.loads(content)
    dsn = deployment_dsn('/run/secrets/db_password', 'db', 'kat', 'kat')
    print(json.dumps(migrate(dsn, transition)))
