"""Round 2A: SQL-view relations on more engines, for DataHub and OpenMetadata.

Usage: python scripts/engines.py dh-view-mysql --server ... --output ...
Adds adapters to metamorphic_native.ADAPTERS and reuses its runner, relations,
calibration and oracle checks unchanged. Engines run as disposable containers on
non-default host ports so they cannot collide with catalog infrastructure.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metamorphic_core as core  # noqa: E402
import metamorphic_native as mn  # noqa: E402
from pilot import save  # noqa: E402

PW = 'Pilot_pass1'
ENGINES = {
    'mysql': {
        'url': f'mysql+pymysql://root:{PW}@127.0.0.1:13306/', 'host': '127.0.0.1:13306', 'user': 'root',
        'q': '{ns}.{t}', 'ddl_schema': ['create database {ns}'], 'table': 'create table {ns}.{t} (id integer)',
        'view': 'create or replace view {ns}.out as {body}',
        'dh': {'type': 'mysql', 'platform': 'mysql', 'filter': 'database_pattern'},
        'om': {'conn': {'type': 'Mysql', 'username': 'root', 'authType': {'password': PW}}, 'lineage': 'mysql-lineage',
               'db': 'default'},
    },
    'mariadb': {
        'url': f'mysql+pymysql://root:{PW}@127.0.0.1:13307/', 'host': '127.0.0.1:13307', 'user': 'root',
        'q': '{ns}.{t}', 'ddl_schema': ['create database {ns}'], 'table': 'create table {ns}.{t} (id integer)',
        'view': 'create or replace view {ns}.out as {body}',
        'dh': {'type': 'mariadb', 'platform': 'mariadb', 'filter': 'database_pattern'},
        'om': {'conn': {'type': 'MariaDB', 'username': 'root', 'password': PW}, 'lineage': 'mariadb-lineage',
               'db': 'default'},
    },
    'clickhouse': {
        'url': f'clickhouse+http://default:{PW}@127.0.0.1:18123/default', 'host': '127.0.0.1:18123', 'user': 'default',
        'q': '{ns}.{t}', 'ddl_schema': ['create database {ns}'],
        'table': 'create table {ns}.{t} (id Int32) engine = Memory',
        'view': 'create or replace view {ns}.out as {body}',
        'dh': {'type': 'clickhouse', 'platform': 'clickhouse', 'filter': 'database_pattern'},
        'om': {'conn': {'type': 'Clickhouse', 'username': 'default', 'password': PW}, 'lineage': 'clickhouse-lineage',
               'db': 'default'},
    },
    'trino': {
        'url': 'trino://pilot@127.0.0.1:18090/memory', 'host': '127.0.0.1:18090', 'user': 'pilot',
        'q': 'memory.{ns}.{t}', 'ddl_schema': ['create schema memory.{ns}'],
        'table': 'create table memory.{ns}.{t} (id integer)',
        'view': 'create or replace view memory.{ns}.out as {body}',
        'dh': {'type': 'trino', 'platform': 'trino', 'filter': 'schema_pattern', 'extra': {'database': 'memory'}},
        'om': {'conn': {'type': 'Trino', 'username': 'pilot', 'catalog': 'memory'}, 'lineage': 'trino-lineage',
               'db': 'memory'},
    },
    'mssql': {
        'url': f'mssql+pytds://sa:{PW}@127.0.0.1:11433/fixture', 'host': '127.0.0.1:11433', 'user': 'sa',
        'admin_url': f'mssql+pytds://sa:{PW}@127.0.0.1:11433/master',
        'q': '{ns}.{t}', 'ddl_schema': ['create schema {ns}'], 'table': 'create table {ns}.{t} (id int)',
        'view': 'create or alter view {ns}.out as {body}',
        'dh': {'type': 'mssql', 'platform': 'mssql', 'filter': 'schema_pattern', 'extra': {'database': 'fixture'}},
        'om': {'conn': {'type': 'Mssql', 'username': 'sa', 'password': PW, 'database': 'fixture',
                        'scheme': 'mssql+pytds'}, 'lineage': 'mssql-lineage', 'db': 'fixture'},
    },
}
BODY = {'r0': 'select id from {a} union all select id from {b}',
        'r1': 'select id from {a} union all select id from {c}',
        'empty': 'select 42 as id'}


def sql_engine(cfg, url=None):
    from sqlalchemy import create_engine
    return create_engine(url or cfg['url'])


def execute(cfg, statements, url=None):
    if (url or cfg['url']).startswith('mssql'):
        # The pytds SQLAlchemy dialect rejects AUTOCOMMIT; CREATE DATABASE needs it.
        import pytds
        db = (url or cfg['url']).rsplit('/', 1)[1]
        with pytds.connect(server='127.0.0.1', port=11433, user='sa', password=PW, database=db,
                           autocommit=True) as conn, conn.cursor() as cur:
            for s in statements:
                cur.execute(s)
        return
    from sqlalchemy import text
    eng = sql_engine(cfg, url)
    with eng.connect() as conn:
        for s in statements:
            conn.execute(text(s))
        if hasattr(conn, 'commit'):
            try:
                conn.commit()
            except Exception:  # autocommit engines
                pass
    eng.dispose()


def wait_ready(cfg, seconds=240):
    start, last = time.monotonic(), None
    while time.monotonic() - start < seconds:
        try:
            if 'admin_url' in cfg:
                execute(cfg, ["if db_id('fixture') is null create database fixture"], cfg['admin_url'])
            execute(cfg, ['select 1'])
            return
        except Exception as exc:  # engine still starting
            last = exc
            time.sleep(3)
    raise RuntimeError(f'Engine not ready: {last!r}')


class EngineFixture:
    def __init__(self, engine):
        self.name, self.cfg = engine, ENGINES[engine]
        wait_ready(self.cfg)

    def schema(self, ns):
        c = self.cfg
        execute(c, [s.format(ns=ns) for s in c['ddl_schema']] +
                [c['table'].format(ns=ns, t=t) for t in ('a', 'b', 'c')])

    def view(self, ns, revision):
        c = self.cfg
        q = {t: c['q'].format(ns=ns, t=t) for t in ('a', 'b', 'c')}
        execute(c, [c['view'].format(ns=ns, body=BODY[revision].format(**q))])


def make_datahub(engine):
    class DataHubEngineView(mn.DataHubBase):
        contract = core.REPLACE

        def __init__(self, *a):
            super().__init__(*a)
            self.fx, self.map = EngineFixture(engine), {}

        def setup(self, ns, d):
            self.fx.schema(ns)

        def recipe(self, ns):
            c, dh = self.fx.cfg, self.fx.cfg['dh']
            conf = {'host_port': c['host'], 'username': c['user'], 'env': 'PROD',
                    dh['filter']: {'allow': [f'^{ns}$']}, 'include_view_lineage': True,
                    'include_view_column_lineage': False, 'incremental_lineage': False,
                    'profiling': {'enabled': False}, 'stateful_ingestion': {'enabled': False}, **dh.get('extra', {})}
            if c['user'] != 'pilot':
                conf['password'] = PW
            return {'pipeline_name': f'mm-{ns}', 'source': {'type': dh['type'], 'config': conf},
                    'sink': {'type': 'datahub-rest', 'config': {'server': self.server, 'mode': 'SYNC'}}}

        def urns(self, ns):
            if ns not in self.map:
                from datahub.emitter.mce_builder import make_dataset_urn
                plat = self.fx.cfg['dh']['platform']
                found = {}
                for n in mn.NAMES:
                    for prefix in ('', 'memory.', 'fixture.', 'default.', 'def.'):
                        urn = make_dataset_urn(plat, f'{prefix}{ns}.{n}', 'PROD')
                        if self.graph.exists(urn):
                            found[n] = urn
                            break
                if set(found) != set(mn.NAMES):
                    raise RuntimeError(f'Could not resolve dataset identities: {found}')
                self.map[ns] = found
            return self.map[ns]

        def apply(self, ns, step, d):
            if step == core.CLEAR:
                return self.clear(self.urns(ns)['out'])
            self.fx.view(ns, step[1])
            self.ingest(self.recipe(ns), d)

        def read(self, ns):
            urns = self.urns(ns)
            save(self.out / 'identities' / f'{ns}.json', urns)
            return self.upstreams(urns)
    return DataHubEngineView


def make_openmetadata(engine):
    class OMEngineView(mn.OMBase):
        contract = core.REPLACE

        def __init__(self, *a):
            super().__init__(*a)
            self.fx, self.ents = EngineFixture(engine), {}
            self.service = f'mm{engine}'

        def conn(self):
            return {**self.fx.cfg['om']['conn'], 'hostPort': self.fx.cfg['host']}

        def setup(self, ns, d):
            self.fx.schema(ns)

        def resolve(self, ns, d):
            db = self.fx.cfg['om']['db']
            ents = {}
            for n in mn.NAMES:
                for fqn in (f'{self.service}.{db}.{ns}.{n}', f'{self.service}.default.{ns}.{n}'):
                    e = self.api('GET', f'/tables/name/{fqn}', ok404=True)
                    if e:
                        ents[n] = e
                        break
            if set(ents) != set(mn.NAMES):
                raise RuntimeError(f'Could not resolve table entities: {sorted(ents)}')
            save(d / 'registered-entities.json', ents)
            return ents

        def apply(self, ns, step, d):
            if step == core.CLEAR:
                return self.clear_source(self.ents[ns], 'ViewLineage')
            self.fx.view(ns, step[1])
            filt = {'schemaFilterPattern': {'includes': [f'^{ns}$']}}
            self.ingest(self.recipe(self.fx.cfg['dh']['type'], self.service, {
                'type': 'DatabaseMetadata', 'markDeletedTables': False, 'includeTables': True, 'includeViews': True,
                **filt}, self.conn()), d / 'metadata')
            if ns not in self.ents:
                self.ents[ns] = self.resolve(ns, d)
            self.ingest(self.recipe(self.fx.cfg['om']['lineage'], self.service, {
                'type': 'DatabaseLineage', 'processViewLineage': True, 'processQueryLineage': False,
                'processStoredProcedureLineage': False, 'incrementalLineageProcessing': False,
                'overrideViewLineage': True, **filt}, self.conn()), d / 'lineage')

        def read(self, ns):
            return self.snapshot(self.ents[ns])
    return OMEngineView


for _e in ENGINES:
    mn.ADAPTERS[f'dh-view-{_e}'] = make_datahub(_e)
    mn.ADAPTERS[f'om-view-{_e}'] = make_openmetadata(_e)


if __name__ == '__main__':
    mn.main()
