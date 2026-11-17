"""Offline behavioral tests. No real credentials or HTTP calls."""
import base64
import importlib.util
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock
from PIL import Image

spec=importlib.util.spec_from_file_location('runner',Path(__file__).with_name('generate_api.py'))
runner=importlib.util.module_from_spec(spec);spec.loader.exec_module(runner)

class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'batch.json';self.state=self.root/'runs-test'
        image=Image.new('RGBA',(32,32),(0,0,0,0));image.putpixel((16,16),(255,128,0,255))
        image.save(self.root/'character.png');self.raw=(self.root/'character.png').read_bytes()
        (self.root/'pose.txt').write_text('Test pose',encoding='utf-8')
        self.config={'schema_version':1,'batch_id':'test','total_cap':1,'parameters_verified':True,'verification_source':'test fixture','verified_on':'2026-11-16','pricing':None,'jobs':[{'id':'pose','cap':1,'images':['character.png'],'prompt_file':'pose.txt','fields':{'model':'test-model','n':1,'size':'1024x1024','quality':'high','output_format':'png','background':'transparent'}}]}
        self.write()
        self.network=patch.object(runner.urllib.request,'build_opener');self.opener=self.network.start().return_value
        self.env=patch.dict(runner.os.environ,{'OPENAI_API_KEY':'offline-test-not-a-real-key'});self.env.start()
    def tearDown(self):
        self.env.stop();self.network.stop();self.temp.cleanup()
    def write(self):self.path.write_text(json.dumps(self.config),encoding='utf-8')
    def approve(self):runner.run(self.path,self.state,'approve',approval_text='Fixture user authorized one request')
    def success(self,raw=None,usage=None):
        data={'data':[{'b64_json':base64.b64encode(raw or self.raw).decode()}]}
        if usage is not None:data['usage']=usage
        response=MagicMock();response.read.return_value=json.dumps(data).encode();response.headers={}
        self.opener.open.return_value.__enter__.return_value=response
    def test_dry_run_no_network_or_state(self):
        self.assertTrue(runner.run(self.path,self.state)['dry_run']);self.opener.open.assert_not_called();self.assertFalse(self.state.exists())
    def test_unapproved_stops(self):
        with self.assertRaises(ValueError):runner.run(self.path,self.state,'execute','pose')
        self.opener.open.assert_not_called()
    def test_approval_bound_to_prompt(self):
        self.approve();(self.root/'pose.txt').write_text('changed',encoding='utf-8')
        with self.assertRaises(ValueError):runner.run(self.path,self.state,'execute','pose')
        self.opener.open.assert_not_called()
    def test_reference_changed(self):
        self.approve();Image.new('RGBA',(32,32),'red').save(self.root/'character.png')
        with self.assertRaises(ValueError):runner.run(self.path,self.state,'execute','pose')
        self.opener.open.assert_not_called()
    def test_success_consumes_cap_and_retains_raw(self):
        self.approve();self.success();result=runner.run(self.path,self.state,'execute','pose')
        self.assertEqual(result['status'],'success');self.assertIsNone(result['estimated_usd'])
        self.assertEqual((self.state/'attempt-001/raw.png').read_bytes(),self.raw)
        with self.assertRaises(ValueError):runner.run(self.path,self.state,'execute','pose')
        self.assertEqual(self.opener.open.call_count,1)
    def test_error_never_retries_and_blocks_even_with_remaining_quota(self):
        self.config['total_cap']=3;self.config['jobs'][0]['cap']=3;self.write();self.approve()
        self.opener.open.side_effect=urllib.error.HTTPError(runner.ENDPOINT,520,'error',{},None)
        self.assertEqual(runner.run(self.path,self.state,'execute','pose')['status'],'http_error')
        with self.assertRaises(ValueError):runner.run(self.path,self.state,'execute','pose')
        self.assertEqual(self.opener.open.call_count,1)
        self.assertEqual(runner.run(self.path,self.state,'report')['unknown_cost_attempts'],1)
    def test_crash_reservation_blocks(self):
        self.approve();folder=self.state/'attempt-001';folder.mkdir();runner.save(folder/'attempt.json',{'job':'pose'})
        with self.assertRaises(ValueError):runner.run(self.path,self.state,'execute','pose')
        self.opener.open.assert_not_called()
    def test_lock_blocks_concurrent_run(self):
        self.approve();(self.state/'execution.lock').touch()
        with self.assertRaises(FileExistsError):runner.run(self.path,self.state,'execute','pose')
        self.opener.open.assert_not_called()
    def test_bad_output_preserved_without_retry(self):
        self.approve();self.success(b'not-an-image')
        self.assertEqual(runner.run(self.path,self.state,'execute','pose')['status'],'request_or_output_error')
        self.assertTrue((self.state/'attempt-001/response.json').exists());self.assertEqual(self.opener.open.call_count,1)
    def test_invalid_gif_params_fail_offline(self):
        fields=self.config['jobs'][0]['fields'];fields.update(output_format='gif',frame_count=17,frame_duration_ms=100);self.write()
        with self.assertRaises(ValueError):runner.run(self.path,self.state)
        self.opener.open.assert_not_called()
    def test_usage_cost(self):
        rates={'text_input_per_million':5,'image_input_per_million':8,'output_per_million':30}
        self.assertAlmostEqual(runner.estimate({'input_tokens_details':{'text_tokens':100,'image_tokens':200},'output_tokens':1000},rates),.0321)
        self.assertIsNone(runner.estimate({},rates))

if __name__=='__main__':unittest.main()
