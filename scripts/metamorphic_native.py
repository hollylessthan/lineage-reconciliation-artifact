"""Native adapters for contract-conditioned metamorphic relations (G2/G3).

Every history runs in its own namespace on one disposable server (an isolated
dbt platform instance, PostgreSQL schema, OpenMetadata service, or OpenLineage
namespace). Observations read primary catalog state and map entities back to
the logical names a, b, c, out. No catalog behavior is emulated.

OpenLineage events are controlled inputs written by this harness; the consumer
endpoints that ingest them are native.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import itertools
import json
import os
from pathlib import Path
import shutil
import sys
import time
import uuid
from urllib.parse import quote, urlparse

import requests

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metamorphic_core as core  # noqa: E402
from pilot import ROOT, run, save  # noqa: E402

NAMES = ('a', 'b', 'c', 'out')
INPUTS = {'r0': ('a', 'b'), 'r1': ('a', 'c'), 'empty': ()}
SQL = {'r0': "select * from {{ ref('a') }} union all select * from {{ ref('b') }}",
       'r1': "select * from {{ ref('a') }} union all select * from {{ ref('c') }}",
       'empty': 'select 42 as id'}
VIEW_SQL = {'r0': 'select id from {s}.a union all select id from {s}.b',
            'r1': 'select id from {s}.a union all select id from {s}.c',
            'empty': 'select 42::integer as id'}
DS_NS = 'postgres://127.0.0.1:5432'
PRODUCER = 'https://github.com/hollylessthan/lineage-reconciliation-artifact/metamorphic'
SCHEMA_URL = 'https://openlineage.io/spec/2-0-2/OpenLineage.json#/definitions/RunEvent'
# Real integrations send this run facet; DataHub's converter derives the orchestrator from it.
ENGINE = {'_producer': PRODUCER, 'version': '1.0', 'name': 'harness', 'openlineageAdapterVersion': '1.0',
          '_schemaURL': 'https://openlineage.io/spec/facets/1-1-1/ProcessingEngineRunFacet.json#/$defs/ProcessingEngineRunFacet'}
PG = dict(host='127.0.0.1', port=5432, dbname='fixture', user='pilot', password='pilot')


# ---------------------------------------------------------------- fixtures
def build_manifests(out: Path):
    manifests = {}
    for name in ('r0', 'r1', 'empty', 'omit'):
        project = out / 'projects' / name
        shutil.copytree(ROOT / 'fixtures', project, dirs_exist_ok=True)
        if name == 'omit':
            (project / 'models/out.sql').unlink()
        else:
            (project / 'models/out.sql').write_text(SQL[name] + '\n')
        if run(['dbt', 'parse', '--no-partial-parse', '--project-dir', str(project), '--profiles-dir', str(project)],
               out / 'logs' / f'dbt-{name}.log'):
            raise RuntimeError(f'dbt parse failed for {name}')
        manifest = project / 'target/manifest.json'
        nodes = json.loads(manifest.read_text())['nodes']
        got = {(nodes[d]['name'], n['name']) for n in nodes.values() if n['resource_type'] == 'model'
               for d in n['depends_on']['nodes'] if d.startswith('model.')}
        want = set() if name == 'omit' else {(x, 'out') for x in INPUTS[name]}
        if got != want:
            raise RuntimeError(f'Compiler contradicts oracle for {name}: {got}')
        manifests[name] = manifest
    return manifests


def pg_conn():
    import psycopg2
    conn = psycopg2.connect(**PG)
    conn.autocommit = True
    return conn


def pg_schema(ns: str):
    with pg_conn() as conn, conn.cursor() as c:
        c.execute('select 1 from pg_namespace where nspname=%s', (ns,))
        if c.fetchone():
            raise RuntimeError(f'Schema {ns} already exists')
        c.execute(f'create schema {ns}')
        for name in ('a', 'b', 'c'):
            c.execute(f'create table {ns}.{name} (id integer)')


def pg_view(ns: str, revision: str):
    with pg_conn() as conn, conn.cursor() as c:
        c.execute(f'create or replace view {ns}.out as ' + VIEW_SQL[revision].format(s=ns))


def ol_events(ns: str, revision: str, pattern: str, clock):
    run_id = str(uuid.uuid4())
    job = {'namespace': ns, 'name': f'{ns}_outjob'}
    ins = [{'namespace': DS_NS, 'name': f'fixture.{ns}.{x}'} for x in INPUTS[revision]]
    outs = [{'namespace': DS_NS, 'name': f'fixture.{ns}.out'}]
    shapes = {'full': [('START', ins, outs), ('COMPLETE', ins, outs)],
              'single': [('COMPLETE', ins, outs)],
              'inputs_in_start': [('START', ins, outs), ('COMPLETE', [], outs)],
              'inputs_in_complete': [('START', [], []), ('COMPLETE', ins, outs)],
              'inputs_omitted_complete': [('START', ins, outs), ('COMPLETE', None, outs)],
              'start_only': [('START', ins, outs)]}[pattern]
    return [{'eventType': kind, 'eventTime': next(clock), 'producer': PRODUCER, 'schemaURL': SCHEMA_URL,
             'run': {'runId': run_id, 'facets': {'processing_engine': ENGINE}}, 'job': job,
             **({'inputs': i} if i is not None else {}), 'outputs': o} for kind, i, o in shapes]


def iso_clock():
    base = time.time()
    for k in itertools.count():
        yield time.strftime('%Y-%m-%dT%H:%M:%S', time.gmtime(base + k)) + '.000Z'


def stable(read, directory: Path, seconds=60, interval=2.0):
    """Poll until three consecutive identical observations or timeout."""
    start, samples, streak, last = time.monotonic(), [], 0, None
    while True:
        state, raw = read()
        samples.append({'t': round(time.monotonic() - start, 1), 'edges': sorted(state), 'raw': raw})
        streak = streak + 1 if state == last else 1
        last = state
        if streak >= 3 or time.monotonic() - start > seconds:
            break
        time.sleep(interval)
    save(directory / 'observations.json', samples)
    return frozenset(last), streak >= 3


# ---------------------------------------------------------------- adapters
class Adapter:
    family = core.BATCH
    contract = core.REPLACE
    supports_omit = False
    supports_cut = False

    def __init__(self, server, out, manifests):
        self.server, self.out, self.manifests = server, out, manifests

    def setup(self, ns, d):
        pass

    def apply(self, ns, step, d):
        raise NotImplementedError

    def read(self, ns):
        raise NotImplementedError


class DataHubBase(Adapter):
    def __init__(self, *a):
        super().__init__(*a)
        from datahub.ingestion.graph.client import DataHubGraph
        from datahub.ingestion.graph.config import DatahubClientConfig
        self.graph = DataHubGraph(DatahubClientConfig(server=self.server))

    def ingest(self, recipe, d):
        save(d / 'recipe.json', recipe)
        code = run(['datahub', 'ingest', '-c', str(d / 'recipe.json')], d / 'ingest.log', timeout=300)
        save(d / 'execution.json', {'exit_code': code})
        if code:
            raise RuntimeError(f'Native ingestion failed: {d}')

    def upstreams(self, urns, aliases=None):
        from datahub.metadata.schema_classes import UpstreamLineageClass
        edges, raw = set(), {}
        names = {u: n for n, u in urns.items()}
        names.update({u: n for n, u in (aliases or {}).items()})
        for name, urn in urns.items():
            aspect = self.graph.get_aspect(urn, UpstreamLineageClass)
            raw[name] = aspect.to_obj() if aspect else None
            for up in aspect.upstreams if aspect else []:
                if up.dataset not in names:
                    raise RuntimeError(f'Unknown upstream identity {up.dataset}')
                edges.add((names[up.dataset], name))
        return edges, raw

    def clear(self, urn):
        from datahub.emitter.mcp import MetadataChangeProposalWrapper
        from datahub.metadata.schema_classes import UpstreamLineageClass
        self.graph.emit_mcp(MetadataChangeProposalWrapper(entityUrn=urn, aspect=UpstreamLineageClass(upstreams=[])))


class DataHubDbt(DataHubBase):
    supports_omit = True

    def urns(self, ns):
        from datahub.emitter.mce_builder import make_dataset_urn_with_platform_instance as mk
        return {n: mk('dbt', f'fixture.main.{n}', ns, 'DEV') for n in NAMES}

    def setup(self, ns, d):
        if any(self.graph.exists(u) for u in self.urns(ns).values()):
            raise RuntimeError('Fresh namespace required')

    def apply(self, ns, step, d):
        if step == core.CLEAR:
            return self.clear(self.urns(ns)['out'])
        self.ingest({'pipeline_name': f'mm-{ns}', 'source': {'type': 'dbt', 'config': {
            'manifest_path': str(self.manifests[step[1]]), 'target_platform': 'postgres', 'env': 'DEV',
            'platform_instance': ns, 'target_platform_instance': ns, 'include_column_lineage': False,
            'infer_dbt_schemas': False, 'stateful_ingestion': {'enabled': False}}},
            'sink': {'type': 'datahub-rest', 'config': {'server': self.server, 'mode': 'SYNC'}}}, d)

    def read(self, ns):
        # dbt model aspects point at the target-platform siblings of upstream models.
        from datahub.emitter.mce_builder import make_dataset_urn_with_platform_instance as mk
        siblings = {n: mk('postgres', f'fixture.main.{n}', ns, 'DEV') for n in NAMES}
        return self.upstreams(self.urns(ns), siblings)


class DataHubView(DataHubBase):
    incremental = False

    def urns(self, ns):
        from datahub.emitter.mce_builder import make_dataset_urn
        return {n: make_dataset_urn('postgres', f'fixture.{ns}.{n}', 'DEV') for n in NAMES}

    def setup(self, ns, d):
        pg_schema(ns)

    def apply(self, ns, step, d):
        if step == core.CLEAR:
            return self.clear(self.urns(ns)['out'])
        pg_view(ns, step[1])
        self.ingest({'pipeline_name': f'mm-{ns}', 'source': {'type': 'postgres', 'config': {
            'host_port': '127.0.0.1:5432', 'database': 'fixture', 'username': 'pilot', 'password': 'pilot',
            'env': 'DEV', 'schema_pattern': {'allow': [f'^{ns}$']}, 'include_view_lineage': True,
            'include_view_column_lineage': False, 'incremental_lineage': self.incremental,
            'profiling': {'enabled': False}, 'stateful_ingestion': {'enabled': False}}},
            'sink': {'type': 'datahub-rest', 'config': {'server': self.server, 'mode': 'SYNC'}}}, d)

    def read(self, ns):
        return self.upstreams(self.urns(ns))


class DataHubViewIncremental(DataHubView):
    incremental = True
    contract = core.ADDITIVE


class DataHubOpenLineage(DataHubBase):
    family = core.OPENLINEAGE

    def __init__(self, *a):
        super().__init__(*a)
        self.clock, self.jobs = iso_clock(), {}

    def apply(self, ns, step, d):
        events = ol_events(ns, step[1], step[2], self.clock)
        responses = []
        for e in events:
            r = requests.post(self.server + '/openapi/openlineage/api/v1/lineage', json=e, timeout=60)
            responses.append({'eventType': e['eventType'], 'status': r.status_code, 'body': r.text[:500]})
            if r.status_code >= 300:
                raise RuntimeError(f'OpenLineage POST failed: {r.status_code} {r.text[:300]}')
        save(d / 'events.json', {'events': events, 'responses': responses})

    def job(self, ns):
        if ns not in self.jobs:
            for _ in range(30):
                found = [u for u in self.graph.get_urns_by_filter(entity_types=['dataJob'], query=f'{ns}_outjob')
                         if f'{ns}_outjob' in u]
                if found:
                    self.jobs[ns] = found
                    break
                time.sleep(2)
        return self.jobs.get(ns, [])

    def read(self, ns):
        from datahub.metadata.schema_classes import DataJobInputOutputClass
        jobs = self.job(ns)
        edges, raw = set(), {'jobs': jobs}

        def logical(urn):
            for n in NAMES:
                if f'fixture.{ns}.{n},'.lower() in urn.lower():
                    return n
            raise RuntimeError(f'Unknown dataset identity {urn}')
        for urn in jobs:
            io = self.graph.get_aspect(urn, DataJobInputOutputClass)
            raw[urn] = io.to_obj() if io else None
            if not io:
                continue
            ins = {logical(e.destinationUrn) for e in io.inputDatasetEdges or []} | \
                  {logical(u) for u in io.inputDatasets or []}
            outs = {logical(e.destinationUrn) for e in io.outputDatasetEdges or []} | \
                   {logical(u) for u in io.outputDatasets or []}
            edges |= {(i, o) for i in ins for o in outs}
        return edges, raw


class OMBase(Adapter):
    def api(self, method, path, body=None, ok404=False):
        r = requests.request(method, self.server + '/api/v1' + path, json=body, timeout=60)
        if ok404 and r.status_code == 404:
            return None
        if r.status_code >= 300:
            raise RuntimeError(f'{method} {path}: {r.status_code} {r.text[:400]}')
        return r.json() if r.content else None

    def recipe(self, source, service, config, connection=None):
        rec = {'source': {'type': source, 'serviceName': service, 'sourceConfig': {'config': config}},
               'sink': {'type': 'metadata-rest', 'config': {}},
               'workflowConfig': {'loggerLevel': 'INFO', 'openMetadataServerConfig': {
                   'hostPort': self.server + '/api', 'authProvider': 'openmetadata',
                   'securityConfig': {'jwtToken': 'disposable-no-auth'}}}}
        if connection:
            rec['source']['serviceConnection'] = {'config': connection}
        return rec

    def ingest(self, recipe, d):
        save(d / 'recipe.json', recipe)
        code = run(['metadata', 'ingest', '-c', str(d / 'recipe.json')], d / 'ingest.log', timeout=300)
        save(d / 'execution.json', {'exit_code': code})
        if code:
            raise RuntimeError(f'Native ingestion failed: {d}')

    def custom_tables(self, service, schema, d):
        if self.api('GET', f'/services/databaseServices/name/{service}', ok404=True) is None:
            self.api('POST', '/services/databaseServices', {'name': service, 'serviceType': 'CustomDatabase',
                     'connection': {'config': {'type': 'CustomDatabase'}}})
            self.api('POST', '/databases', {'name': 'fixture', 'service': service})
        self.api('POST', '/databaseSchemas', {'name': schema, 'database': f'{service}.fixture'})
        ents = {n: self.api('POST', '/tables', {'name': n, 'databaseSchema': f'{service}.fixture.{schema}',
                                                'columns': [{'name': 'id', 'dataType': 'INT'}]}) for n in NAMES}
        save(d / 'registered-entities.json', ents)
        return ents

    def snapshot(self, ents):
        ids = {e['id']: n for n, e in ents.items()}
        edges, raw = set(), {}
        for name, e in ents.items():
            lin = self.api('GET', f"/lineage/table/{e['id']}?upstreamDepth=1&downstreamDepth=0")
            raw[name] = lin.get('upstreamEdges')
            for edge in lin.get('upstreamEdges') or []:
                if edge['toEntity'] != e['id']:
                    continue
                if edge['fromEntity'] not in ids:
                    raise RuntimeError('Unknown lineage endpoint')
                edges.add((ids[edge['fromEntity']], name))
        return edges, raw

    def clear_source(self, ents, source):
        self.api('DELETE', f"/lineage/table/{ents['out']['id']}/type/{source}")


class OMDbt(OMBase):
    supports_omit = True
    supports_cut = True
    override = True

    def __init__(self, *a):
        super().__init__(*a)
        self.ents = {}
        self.contract = core.REPLACE if self.override else core.ADDITIVE

    def setup(self, ns, d):
        self.ents[ns] = self.custom_tables(ns, 'main', d)

    def config(self, revision):
        c = {'type': 'DBT', 'dbtConfigSource': {'dbtConfigType': 'local',
             'dbtManifestFilePath': str(self.manifests[revision])}}
        if self.override:
            c['overrideLineage'] = True
        return c

    def apply(self, ns, step, d):
        if step == core.CLEAR:
            return self.clear_source(self.ents[ns], 'DbtLineage')
        if step[0] == 'cut':
            from openmetadata_pilot import interrupted
            mode = 'override' if self.override else 'default'
            d.mkdir(parents=True, exist_ok=True)
            interrupted(self.manifests[step[1]], ns, mode, d, self.server, self.ents[ns]['out']['id'])
            return
        self.ingest(self.recipe('dbt', ns, self.config(step[1])), d)

    def read(self, ns):
        return self.snapshot(self.ents[ns])


class OMDbtDefault(OMDbt):
    override = False


class OMView(OMBase):
    """PostgreSQL view lineage with overrideViewLineage=true; metadata re-ingested each step."""
    service = 'mmpg'

    def __init__(self, *a):
        super().__init__(*a)
        self.ents = {}

    def conn(self):
        return {'type': 'Postgres', 'username': 'pilot', 'authType': {'password': 'pilot'},
                'hostPort': '127.0.0.1:5432', 'database': 'fixture'}

    def setup(self, ns, d):
        pg_schema(ns)

    def apply(self, ns, step, d):
        if step == core.CLEAR:
            return self.clear_source(self.ents[ns], 'ViewLineage')
        pg_view(ns, step[1])
        self.ingest(self.recipe('postgres', self.service, {
            'type': 'DatabaseMetadata', 'markDeletedTables': False, 'includeTables': True, 'includeViews': True,
            'schemaFilterPattern': {'includes': [f'^{ns}$']}}, self.conn()), d / 'metadata')
        if ns not in self.ents:
            self.ents[ns] = {n: self.api('GET', f'/tables/name/{self.service}.fixture.{ns}.{n}') for n in NAMES}
            save(d / 'registered-entities.json', self.ents[ns])
        self.ingest(self.recipe('postgres-lineage', self.service, {
            'type': 'DatabaseLineage', 'processViewLineage': True, 'processQueryLineage': False,
            'processStoredProcedureLineage': False, 'incrementalLineageProcessing': False,
            'overrideViewLineage': True, 'schemaFilterPattern': {'includes': [f'^{ns}$']}}, self.conn()),
            d / 'lineage')

    def read(self, ns):
        return self.snapshot(self.ents[ns])


class OMOpenLineage(OMBase):
    family = core.OPENLINEAGE
    contract = core.UNDETERMINED
    service = 'mmol'

    def __init__(self, *a):
        super().__init__(*a)
        self.clock, self.ents, self.ready = iso_clock(), {}, False

    def configure(self, d):
        if self.ready:
            return
        before = self.api('GET', '/system/settings/openLineageSettings', ok404=True)
        if self.api('GET', '/services/pipelineServices/name/mmolpipes', ok404=True) is None:
            self.api('POST', '/services/pipelineServices', {'name': 'mmolpipes', 'serviceType': 'CustomPipeline',
                     'connection': {'config': {'type': 'CustomPipeline'}}})
        value = dict((before or {}).get('config_value') or (before or {}).get('configValue') or {})
        value.update({'enabled': True, 'autoCreateEntities': False, 'defaultPipelineService': 'mmolpipes',
                      'namespaceToServiceMapping': {DS_NS: self.service}})
        try:
            self.api('PUT', '/system/settings', {'config_type': 'openLineageSettings', 'config_value': value})
        except RuntimeError:
            self.api('PUT', '/system/settings', {'configType': 'openLineageSettings', 'configValue': value})
        after = self.api('GET', '/system/settings/openLineageSettings', ok404=True)
        save(d / 'openlineage-settings.json', {'before': before, 'after': after})
        self.ready = True

    def setup(self, ns, d):
        self.configure(d)
        self.ents[ns] = self.custom_tables(self.service, ns, d)

    def apply(self, ns, step, d):
        events = ol_events(ns, step[1], step[2], self.clock)
        responses = []
        for e in events:
            r = requests.post(self.server + '/api/v1/openlineage/lineage', json=e, timeout=60)
            responses.append({'eventType': e['eventType'], 'status': r.status_code, 'body': r.text[:800]})
            if r.status_code >= 300:
                raise RuntimeError(f'OpenLineage POST failed: {r.status_code} {r.text[:300]}')
        save(d / 'events.json', {'events': events, 'responses': responses})

    def read(self, ns):
        return self.snapshot(self.ents[ns])


class Marquez(Adapter):
    family = core.OPENLINEAGE
    contract = core.REPLACE

    def __init__(self, *a):
        super().__init__(*a)
        self.clock = iso_clock()

    def apply(self, ns, step, d):
        events = ol_events(ns, step[1], step[2], self.clock)
        responses = []
        for e in events:
            r = requests.post(self.server + '/api/v1/lineage', json=e, timeout=60)
            responses.append({'eventType': e['eventType'], 'status': r.status_code, 'body': r.text[:500]})
            if r.status_code >= 300:
                raise RuntimeError(f'OpenLineage POST failed: {r.status_code} {r.text[:300]}')
        save(d / 'events.json', {'events': events, 'responses': responses})

    def read(self, ns):
        job = f'{ns}_outjob'
        node = f'job:{ns}:{job}'
        r = requests.get(self.server + '/api/v1/lineage', params={'nodeId': node, 'depth': 1}, timeout=60)
        if r.status_code == 404:
            return set(), {'lineage': None}
        r.raise_for_status()
        graph = r.json()

        def logical(node_id):
            for n in NAMES:
                if node_id.endswith(f'fixture.{ns}.{n}'):
                    return n
            raise RuntimeError(f'Unknown dataset node {node_id}')
        ins, outs = set(), set()
        for n in graph.get('graph', []):
            if n['id'] != node:
                continue
            ins |= {logical(e['origin']) for e in n.get('inEdges', [])}
            outs |= {logical(e['destination']) for e in n.get('outEdges', [])}
        jr = requests.get(f"{self.server}/api/v1/namespaces/{quote(ns, safe='')}/jobs/{quote(job, safe='')}", timeout=60)
        return {(i, o) for i in ins for o in outs}, {'lineage': graph, 'job': jr.json() if jr.ok else jr.status_code}


ADAPTERS = {'dh-dbt': DataHubDbt, 'dh-view': DataHubView, 'dh-view-incremental': DataHubViewIncremental,
            'dh-ol': DataHubOpenLineage, 'om-dbt-override': OMDbt, 'om-dbt-default': OMDbtDefault,
            'om-view': OMView, 'om-ol': OMOpenLineage, 'marquez-ol': Marquez}


# ---------------------------------------------------------------- runner
class Runner:
    def __init__(self, adapter: Adapter, out: Path, prefix: str):
        self.adapter, self.out, self.prefix, self.n = adapter, out, prefix, 0
        self.log = []

    def fresh(self, history):
        self.n += 1
        ns = f'{self.prefix}{self.n:03d}'
        d = self.out / 'histories' / ns
        save(d / 'history.json', core.fmt(history))
        try:
            self.adapter.setup(ns, d / 'setup')
            for i, step in enumerate(history):
                self.adapter.apply(ns, step, d / f'step{i}-{"-".join(step)}')
            state, steady = stable(lambda: self.adapter.read(ns), d)
            self.log.append({'ns': ns, 'history': core.fmt(history), 'edges': sorted(state), 'stable': steady})
            return state if steady else None
        except Exception as exc:  # recorded, not hidden
            save(d / 'error.json', {'error': repr(exc)})
            self.log.append({'ns': ns, 'history': core.fmt(history), 'error': repr(exc)})
            return None


def main():
    p = argparse.ArgumentParser()
    p.add_argument('path', choices=sorted(ADAPTERS))
    p.add_argument('--server', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--skip-calibration', action='store_true',
                   help='Exploratory runs only: the integrity gate fails, so results cannot be promoted.')
    a = p.parse_args()
    if urlparse(a.server).scheme != 'http' or urlparse(a.server).hostname not in ('localhost', '127.0.0.1'):
        p.error('Disposable loopback HTTP catalog required')
    out = a.output.resolve()
    out.mkdir(parents=True, exist_ok=True)
    cls = ADAPTERS[a.path]
    needs = getattr(cls, 'needs_manifests', cls.family == core.BATCH and a.path.split('-')[1] == 'dbt')
    manifests = build_manifests(out) if needs else {}
    adapter = cls(a.server, out, manifests)
    prefix = 'mm' + hashlib.sha1(a.path.encode()).hexdigest()[:4]
    runner = Runner(adapter, out, prefix)
    if adapter.family == core.BATCH:
        rels = core.batch_relations(supports_omit=adapter.supports_omit)
        if adapter.supports_cut:
            rels += core.fault_relations()
        if not getattr(adapter, 'supports_clear', True):
            # No native explicit-clear operation exists; the control is inapplicable, not failed.
            rels = [r for r in rels if r.id != 'MR3']
    else:
        rels = core.openlineage_relations()
    started = time.time()
    calibration = None if a.skip_calibration else core.calibrate(adapter.family, runner.fresh)
    rows = core.evaluate(rels, adapter.contract, runner.fresh)
    pkgs = {}
    for n in ('acryl-datahub', 'openmetadata-ingestion', 'dbt-core', 'dbt-postgres'):
        try:
            pkgs[n] = importlib.metadata.version(n)
        except importlib.metadata.PackageNotFoundError:
            pass
    save(out / 'metamorphic-results.json', {
        'path': a.path, 'contract': adapter.contract, 'family': adapter.family,
        'github_sha': os.environ.get('GITHUB_SHA'), 'packages': pkgs, 'seconds': round(time.time() - started),
        'calibration': calibration, 'relations': rows, 'summary': core.summarize(rows), 'histories': runner.log})
    print(json.dumps({'path': a.path, 'summary': core.summarize(rows),
                      'calibration_false_alarms': calibration and calibration['false_alarms']}))
    # Evidence also goes to the job log, which stays readable when artifacts are not.
    for r in rows:
        print('MMREL ' + json.dumps({'path': a.path, 'rel': r['relation'], 'verdict': r['verdict'],
                                     'a': r['state_a'], 'b': r['state_b']}))
    for h in runner.log:
        print('MMHIST ' + json.dumps({'path': a.path, **h}))
    if calibration:
        print('MMCAL ' + json.dumps({'path': a.path, **calibration}))
    # Non-vacuity: single-step fresh histories must match the authored oracle,
    # otherwise 'holds' could come from a path that observed nothing.
    for h in runner.log:
        steps = h['history']
        if len(steps) == 1 and 'edges' in h:
            name = steps[0].split(':')[1]
            want = sorted([x, 'out'] for x in INPUTS.get(name, ()))
            print('MMORACLE ' + json.dumps({'path': a.path, 'history': steps, 'observed': h['edges'],
                                            'expected': want, 'match': [list(e) for e in h['edges']] == want}))

    # Only harness integrity failures are fatal. A genuine contract violation is evidence,
    # not an infrastructure error, and remains recorded in the result JSON.
    failures = []
    if calibration is None:
        failures.append('calibration skipped (--skip-calibration): exploratory run, not promotable')
    elif calibration['false_alarms']:
        failures.append('calibration inconsistent')
    if any(h.get('error') or not h.get('stable', False) for h in runner.log):
        failures.append('history execution failed or did not stabilize')
    if any(r['verdict'] in ('not_testable', 'control_failed') for r in rows):
        failures.append('required relation/control not testable or failed')
    # A path that cannot reproduce the authored fresh state makes every 'holds' vacuous.
    # Patterns that are themselves under test (partial OpenLineage runs) are exempt.
    exempt = ('inputs_in_start', 'inputs_omitted_complete', 'inputs_in_complete', 'start_only')
    for h in runner.log:
        steps = h['history']
        if len(steps) == 1 and 'edges' in h and not any(steps[0].endswith(':' + x) for x in exempt):
            name = steps[0].split(':')[1]
            want = sorted([x, 'out'] for x in INPUTS.get(name, ()))
            if name in INPUTS and [list(e) for e in h['edges']] != want:
                failures.append(f'fresh-state oracle mismatch for {steps[0]}')
                break
    if failures:
        raise SystemExit('Harness integrity gate failed: ' + '; '.join(failures))


if __name__ == '__main__':
    main()
