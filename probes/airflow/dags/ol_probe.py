"""Item 3 probe: what OpenLineage events does a real Airflow producer emit?

Each task is one OpenLineage run. Revisions mirror the harness fixture: r0 reads a,b;
r1 reads a,c; empty reads nothing. Both a view and an INSERT ... SELECT target are used.
"""
import pendulum
from airflow import DAG
from airflow.providers.common.sql.operators.sql import SQLExecuteQueryOperator

SQL = {
    'view_r0': 'create or replace view probe.out_v as select id from probe.a union all select id from probe.b',
    'view_r1': 'create or replace view probe.out_v as select id from probe.a union all select id from probe.c',
    'view_empty': 'create or replace view probe.out_v as select 42::integer as id',
    'insert_r0': 'insert into probe.out_t select id from probe.a union all select id from probe.b',
    'insert_r1': 'insert into probe.out_t select id from probe.a union all select id from probe.c',
    'insert_empty': 'insert into probe.out_t select 42',
}

with DAG('ol_probe', start_date=pendulum.datetime(2026, 1, 1), schedule=None, catchup=False) as dag:
    prev = SQLExecuteQueryOperator(task_id='setup', conn_id='pg', sql=[
        'drop schema if exists probe cascade', 'create schema probe',
        'create table probe.a (id int)', 'create table probe.b (id int)', 'create table probe.c (id int)',
        'create table probe.out_t (id int)'])
    for name, sql in SQL.items():
        t = SQLExecuteQueryOperator(task_id=name, conn_id='pg', sql=sql)
        prev >> t
        prev = t
