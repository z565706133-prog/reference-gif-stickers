"""Offline integration checks with synthetic, redistributable fixtures."""
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image,ImageDraw
import sticker_workflow as flow

class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.master=self.base/'master.png';im=Image.new('RGBA',(64,64));d=ImageDraw.Draw(im);d.rectangle((20,12,43,55),fill='orange');im.save(self.master)
        self.reference=self.base/'reference.gif'
        frames=[im.copy(),im.copy(),im.copy()]
        flow.encode_gif(frames,[100,200,100],self.reference,128)
        self.root=self.base/'project';flow.init(self.root,self.master,[self.reference],None)
        project=flow.read(self.root/'project.json');flow.extract(self.root,project)
        task=self.root/'tasks/R001';(task/'inputs').mkdir()
        for i in range(3):
            frame=Image.new('RGBA',(64,64));draw=ImageDraw.Draw(frame);draw.rectangle((20,12+i,43,55),fill='orange');frame.save(task/'inputs'/f'{i}.png')
        cfg=flow.read(task/'render.json');cfg['frames']=[f'inputs/{i}.png' for i in range(3)]
        flow.write(task/'render.json',cfg,True)
    def tearDown(self):self.tmp.cleanup()
    def render(self):return flow.render(self.root,flow.read(self.root/'project.json'),'R001','test')
    def test_extract_complete(self):
        task=self.root/'tasks/R001/analysis'
        self.assertEqual(len(list(task.glob('frame-*.png'))),3)
        self.assertEqual(flow.read(task/'metadata.json')['durations_ms'],[100,200,100])
    def test_export_repeated_frames_timing_and_outline(self):
        self.render();report=flow.read(self.root/'tasks/R001/revisions/test/validation.json')
        self.assertEqual(report['actual']['durations_ms'],[100,200,100]);self.assertEqual(report['outline_px_at_240'],3)
        self.assertEqual(report['actual']['size'],[240,240]);self.assertTrue(report['technical_pass'])
        self.assertEqual(flow.read(self.root/'project.json')['tasks'][0]['status'],'pending_review')
    def test_originals_unchanged_and_revision_not_overwritten(self):
        before=flow.sha(self.master);self.render();self.assertEqual(flow.sha(self.master),before)
        with self.assertRaises(ValueError):self.render()
    def test_timing_change_rejected(self):
        p=self.root/'tasks/R001/render.json';cfg=flow.read(p);cfg['durations_ms']=[100]*3;flow.write(p,cfg,True)
        with self.assertRaises(ValueError):self.render()
    def test_flood_preserves_enclosed_white_and_mask(self):
        im=Image.new('RGBA',(30,30),'white');d=ImageDraw.Draw(im);d.rectangle((6,6,23,23),fill='black');d.rectangle((10,10,18,18),fill='white')
        result=flow.remove_background(im,{'rgb':[255,255,255],'tolerance':5})
        self.assertEqual(result.getpixel((0,0))[3],0);self.assertEqual(result.getpixel((14,14))[3],255)
        mask=Image.new('L',im.size);ImageDraw.Draw(mask).rectangle((0,0,3,3),fill=255);mask.save(self.base/'protect.png')
        result=flow.remove_background(im,{'rgb':[255,255,255]},self.base/'protect.png');self.assertEqual(result.getpixel((0,0))[3],255)
    def test_package_only_approved_and_unchanged_bytes(self):
        self.render();project=flow.read(self.root/'project.json')
        with self.assertRaises(ValueError):flow.package(self.root,project,'unapproved')
        flow.approval(self.root,project,'R001','approved','Synthetic fixture approval; not a real user project')
        project=flow.read(self.root/'project.json');flow.package(self.root,project,'candidate')
        original=self.root/'tasks/R001/revisions/test/sticker.gif';copy=self.root/'packages/candidate/表情图/01.gif'
        self.assertEqual(original.read_bytes(),copy.read_bytes())
        self.assertFalse(flow.read(self.root/'packages/candidate/manifest.json')['official_rules_verified'])
    def test_approval_hash_tamper_blocks_package(self):
        self.render();project=flow.read(self.root/'project.json');flow.approval(self.root,project,'R001','approved','Fixture')
        p=self.root/'tasks/R001/revisions/test/sticker.gif';p.write_bytes(p.read_bytes()+b'changed')
        with self.assertRaises(ValueError):flow.package(self.root,flow.read(self.root/'project.json'),'bad')
    def test_same_frames_not_merged(self):
        im=Image.open(self.master).convert('RGBA');p=self.base/'same.gif';flow.encode_gif([im,im,im],[100,100,100],p,128)
        self.assertEqual(flow.inspect(p)['frame_count'],3)
    def test_import_gif_exact_timing_and_original_preserved(self):
        project=flow.read(self.root/'project.json');result=flow.import_gif(self.root,project,'R001',self.reference,'import-test')
        self.assertEqual(result['imported_frames'],3)
        copied=self.root/'tasks/R001/inputs/import-test/original.gif';self.assertEqual(copied.read_bytes(),self.reference.read_bytes())
    def test_new_revision_resets_approval(self):
        self.render();project=flow.read(self.root/'project.json');flow.approval(self.root,project,'R001','approved','Fixture')
        flow.render(self.root,flow.read(self.root/'project.json'),'R001','second')
        self.assertEqual(flow.read(self.root/'project.json')['tasks'][0]['status'],'pending_review')

if __name__=='__main__':unittest.main()
