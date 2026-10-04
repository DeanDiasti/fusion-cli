import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import test_startup
from bridge.commands import EFFECTS, SPECS, prepare
from tools import admin, jobs


class Collection:
    def __init__(self, values=()): self.values=list(values)
    @property
    def count(self): return len(self.values)
    def item(self,index): return self.values[index]


def fake_document(name='Fixture',identity='doc-1',saved=False,data_file=None):
    return SimpleNamespace(name=name,creationId=identity,isActive=True,isModified=False,
                           isSaved=saved,isVisible=True,dataFile=data_file,products=Mock())


class AdminReleaseTests(unittest.TestCase):
    def test_approved_admin_inventory_is_typed(self):
        expected={
            'app inspect','app capabilities','app state','app diagnostics','app preferences',
            'app jobs list','app jobs inspect','app jobs cancel','app jobs forget',
            'workspace list','workspace activate',
            'documents list','documents inspect','documents create','documents activate',
            'documents close','documents save','documents save-as','documents open',
            'documents import','documents export',
            'projects list','projects inspect','projects create','projects rename','projects delete',
            'folders list','folders inspect','folders search','folders create','folders rename','folders delete',
            'files list','files search','files inspect','files rename','files copy','files move',
            'files delete','files upload','files download',
        }
        self.assertTrue(expected.issubset(SPECS))
        for command in expected:
            parsed=prepare({'command':'fusion help '+command})[1]
            self.assertIn('effect',parsed)
        self.assertEqual(EFFECTS['documents export'],'file_output')
        self.assertEqual(EFFECTS['documents inspect'],'inspection')
        self.assertEqual(EFFECTS['files download'],'file_output')
        with self.assertRaisesRegex(ValueError,'greater than zero'):
            prepare({'command':'fusion files search --project p --query q --limit 0'})

    def test_project_delete_reports_installed_api_boundary(self):
        with self.assertRaisesRegex(RuntimeError,'does not expose project deletion'):
            admin.projects_delete({'project':'fixture'})

    def test_folder_delete_requires_exact_safe_scope(self):
        root=SimpleNamespace(isRoot=True)
        with patch.object(admin,'folder',return_value=root),self.assertRaisesRegex(ValueError,'root'):
            admin.folders_delete({'folder':'root'})
        populated=SimpleNamespace(isRoot=False,id='f',dataFolders=Collection([1]),dataFiles=Collection(),deleteMe=Mock())
        with patch.object(admin,'folder',return_value=populated),self.assertRaisesRegex(ValueError,'not empty'):
            admin.folders_delete({'folder':'f'})
        populated.deleteMe.return_value=True
        with patch.object(admin,'folder',return_value=populated):
            self.assertEqual(admin.folders_delete({'folder':'f','recursive':True}),{'deleted':'f'})

    def test_cloud_search_is_case_insensitive_and_bounded(self):
        project=SimpleNamespace(rootFolder=None)
        one=SimpleNamespace(name='Fixtures',id='one')
        file=SimpleNamespace(name='Motor Fixture')
        one.dataFiles=Collection([file])
        with patch.object(admin,'project',return_value=project), \
             patch.object(admin,'_walk_folders',return_value=[one]), \
             patch.object(admin,'folder_info',return_value={'id':'one'}), \
             patch.object(admin,'file_info',return_value={'id':'file'}):
            self.assertEqual(admin.folders_search({'project':'p','query':'FIX','limit':4})['folders'],[{'id':'one'}])
            self.assertEqual(admin.files_search({'project':'p','query':'fixture','limit':4})['files'],[{'id':'file'}])

    def test_file_delete_refuses_referenced_file_without_override(self):
        f=SimpleNamespace(id='file',hasParentReferences=True,deleteMe=Mock(return_value=True))
        with patch.object(admin,'datafile',return_value=f),self.assertRaisesRegex(ValueError,'referenced'):
            admin.files_delete({'file':'file'})
        with patch.object(admin,'datafile',return_value=f):
            self.assertEqual(admin.files_delete({'file':'file','allow_referenced':True}),{'deleted':'file'})

    def test_upload_registers_future_and_download_verifies_output(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'fixture.txt'; source.write_text('fixture')
            future=object(); target=Mock(); target.uploadFile.return_value=future
            with patch.object(admin,'folder',return_value=target), \
                 patch.object(jobs,'register',return_value={'job':'j','status':'pending'}):
                result=admin.files_upload({'folder':'folder','path':str(source)})
            self.assertEqual(result['job'],'j')
            target.uploadFile.assert_called_once_with(str(source))

            output=Path(directory)/'download.txt'
            cloud=SimpleNamespace(id='file',name='download',fileExtension='txt')
            def download(path,handler): Path(path).write_text('downloaded'); return True
            cloud.download=download
            with patch.object(admin,'datafile',return_value=cloud):
                result=admin.files_download({'file':'file','path':str(output)})
            self.assertEqual(result['bytes'],10)

    def test_fusion_design_download_routes_to_document_export(self):
        cloud=SimpleNamespace(fileExtension='f3d')
        with patch.object(admin,'datafile',return_value=cloud),self.assertRaisesRegex(ValueError,'documents export'):
            admin.files_download({'file':'file','path':'/tmp/file.f3d'})

    def test_document_import_and_export_are_typed_and_verified(self):
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'fixture.step'; source.write_text('step')
            imported=fake_document()
            manager=Mock(); manager.createSTEPImportOptions.return_value='options'
            manager.importToNewDocument.return_value=imported
            application=SimpleNamespace(importManager=manager)
            with patch.object(admin,'app',return_value=application):
                result=admin.documents_import({'path':str(source)})
            self.assertEqual(result['format'],'step')
            manager.importToNewDocument.assert_called_once_with('options')

            target=Path(directory)/'fixture.f3d'
            export=Mock(); export.createFusionArchiveExportOptions.return_value='export-options'
            export.execute.side_effect=lambda _: target.write_text('archive') or True
            design=SimpleNamespace(exportManager=export)
            document=fake_document()
            design_type=SimpleNamespace(cast=Mock(return_value=design))
            with patch.object(admin,'doc',return_value=document), \
                 patch.object(admin.adsk.fusion,'Design',design_type,create=True):
                result=admin.documents_export({'document':'doc-1','format':'fusion_archive','path':str(target)})
            self.assertEqual(result['bytes'],7)

    def test_job_cancel_is_truthful_and_terminal_jobs_can_be_forgotten(self):
        states=SimpleNamespace(UploadFinished=2,UploadFailed=3)
        cloud=SimpleNamespace(id='file')
        future=SimpleNamespace(uploadState=2,dataFile=cloud)
        with patch.object(jobs.adsk.core,'UploadStates',states,create=True), \
             patch.object(admin,'file_info',return_value={'id':'file'}), \
             patch.object(jobs.time,'monotonic',return_value=2.0):
            jobs._jobs['job']={'future':future,'operation':'upload','started':1.0}
            result=jobs.cancel({'job':'job'})
            self.assertFalse(result['cancelled'])
            self.assertIn('cancellation is unavailable',result['blocker'])
            self.assertEqual(jobs.forget({'job':'job'}),{'forgotten':'job'})


if __name__ == '__main__': unittest.main()
