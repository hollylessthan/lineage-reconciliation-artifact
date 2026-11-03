"""Round 2B: catalog breadth.

Adds to metamorphic_native.ADAPTERS:
  dh-ol-patch   DataHub OpenLineage endpoint with server usePatch=true (Additive contract)
  odd-dbt       Open Data Discovery Platform via the odd-dbt collector (Replace contract)

Older DataHub/OpenMetadata releases reuse the existing adapters with different
server images and client pins (see .github/workflows/round2b.yml).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import metamorphic_core as core  # noqa: E402
import metamorphic_native as mn  # noqa: E402
from pilot import ROOT, run, save  # noqa: E402


class DataHubOpenLineagePatch(mn.DataHubOpenLineage):
    """Server started with DATAHUB_OPENLINEAGE_USEPATCH=true: edges are patched in, never replaced."""
    contract = core.ADDITIVE


ODD_DB = dict(host='127.0.0.1', port=15432, dbname='odd-platform', user='odd-platform', password='odd-platform-password')
PROFILE = '''reconciliation_fixture:
  target: dev
  outputs:
    dev:
      type: postgres
      host: 127.0.0.1
      port: 5432
      user: pilot
      password: pilot
      dbname: fixture
      schema: {ns}
      threads: 1
'''


class ODDDbt(mn.Adapter):
    """Open Data Discovery: odd-dbt ingest-lineage. Documented: per emitting model, previous
    edges are deleted and the current payload's edges inserted (replaceLineagePaths)."""
    contract = core.REPLACE
    supports_omit = True
    supports_clear = False  # no native explicit-clear operation for collector lineage
    needs_manifests = False  # builds its own PostgreSQL-profile projects per namespace

    def __init__(self, *a):
        super().__init__(*a)
        self.oddrn = {}
        # A registered collector token is required; ingestion with an unknown token returns HTTP 500.
        from odd_models.api_client.v2.odd_api_client import Client
        self.client = Client(host=self.server)
        self.client.auth(name='metamorphic-harness', description='disposable CI collector')
        self.token = self.client._token

    def setup(self, ns, d):
        from odd_dbt.service.odd import create_datasource
        self.oddrn[ns] = create_datasource(name=ns, dbt_host=ns, client=self.client)
        save(d / 'datasource.json', {'oddrn': self.oddrn[ns]})

    def project(self, ns, revision, d):
        p = d / 'project'
        shutil.copytree(ROOT / 'fixtures', p, dirs_exist_ok=True)
        if revision == 'omit':
            (p / 'models/out.sql').unlink()
        else:
            (p / 'models/out.sql').write_text(mn.SQL[revision] + '\n')
        (p / 'profiles.yml').write_text(PROFILE.format(ns=ns))
        if run(['dbt', 'parse', '--no-partial-parse', '--project-dir', str(p), '--profiles-dir', str(p)],
               d / 'dbt-parse.log'):
            raise RuntimeError(f'dbt parse failed: {d}')
        return p

    def apply(self, ns, step, d):
        if step == core.CLEAR:
            raise RuntimeError('No native clear for ODD collector lineage')
        p = self.project(ns, step[1], d)
        code = run([sys.executable, '-m', 'odd_dbt.app', 'ingest-lineage', '--project-dir', str(p),
                    '--profiles-dir', str(p), '--host', self.server, '--token', self.token,
                    '--dbt-oddrn', self.oddrn[ns]], d / 'ingest.log', timeout=300)
        save(d / 'execution.json', {'exit_code': code})
        if code:
            raise RuntimeError(f'odd-dbt ingest-lineage failed: {d}')

    def read(self, ns):
        import psycopg2
        prefix = self.oddrn[ns].rstrip('/') + '/'
        with psycopg2.connect(**ODD_DB) as conn, conn.cursor() as c:
            c.execute("select parent_oddrn, child_oddrn, establisher_oddrn from lineage "
                      "where coalesce(is_deleted, false) = false and child_oddrn like %s", (prefix + '%',))
            rows = c.fetchall()

        def logical(oddrn):
            tail = oddrn.rsplit('/', 1)[-1]
            name = tail.rsplit('.', 1)[-1]
            return name if name in mn.NAMES else None
        edges = set()
        for parent, child, _ in rows:
            if not child.rsplit('/', 1)[-1].startswith('model.'):
                continue  # model -> materialized table edge
            p, c = logical(parent), logical(child)
            if p is None or c is None:
                raise RuntimeError(f'Unknown lineage endpoint {parent} -> {child}')
            edges.add((p, c))
        return edges, {'rows': [list(r) for r in rows]}


mn.ADAPTERS['dh-ol-patch'] = DataHubOpenLineagePatch
mn.ADAPTERS['odd-dbt'] = ODDDbt

if __name__ == '__main__':
    mn.main()
