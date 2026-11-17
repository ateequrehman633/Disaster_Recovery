"""Static packaging checks; no Docker / external services required."""
import json
import pathlib
import subprocess
import sys
import unittest
try: import yaml
except ImportError: yaml=None
ROOT=pathlib.Path(__file__).resolve().parents[1]
class PackagingTests(unittest.TestCase):
    def test_python_syntax(self):
        source=(ROOT/'app/main.py').read_text()
        compile(source,'app/main.py','exec')
    def test_js_syntax(self):
        if subprocess.call(['bash','-lc','command -v node >/dev/null'])!=0:
            self.skipTest('Node not available')
        subprocess.run(['node','--check',str(ROOT/'app/static/app.js')],check=True)
    def test_grafana_provisioning(self):
        docs=list((ROOT/'monitoring/grafana/dashboards').glob('*.json'))
        self.assertEqual(len(docs),4)
        for d in docs:
            obj=json.loads(d.read_text())
            self.assertTrue(obj['panels'])
            self.assertTrue(obj['uid'].startswith('cloudlab-'))
            for p in obj['panels']:
                self.assertEqual(p['targets'][0]['refId'],'A')
                self.assertEqual(p['datasource']['uid'],'cloudlab-prom')
    def test_compose_and_prometheus_yaml(self):
        if yaml is None:self.skipTest('PyYAML unavailable')
        compose=yaml.safe_load((ROOT/'compose.yaml').read_text())
        self.assertEqual(len(compose['services']),10)
        self.assertEqual(compose['services']['prometheus']['ports'][0],'127.0.0.1:9090:9090')
        prom=yaml.safe_load((ROOT/'monitoring/prometheus.yml').read_text())
        self.assertGreaterEqual(len(prom['scrape_configs']),5)
        alerts=yaml.safe_load((ROOT/'monitoring/alerts.yml').read_text())
        self.assertTrue(alerts['groups'])
    def test_no_secrets_in_zip(self):
        self.assertFalse((ROOT/'.env').exists())
        self.assertFalse((ROOT/'.lab-credentials').exists())
    def test_all_teaching_images(self):
        self.assertEqual(len(list((ROOT/'docs/images').glob('*.png'))),3)
if __name__=='__main__': unittest.main()
