"""Thin BrachyBot boundary around the user-supplied lung/head-neck/nasopharynx scripts."""
import tempfile
import subprocess
from pathlib import Path

import numpy as np
import SimpleITK as sitk

from tool_factory import BaseTool, ToolResult
from utils.cancellation import OperationCancelled, raise_if_cancelled
from .nnunet_cascade_tumor import NNUNetCascadeTumorTool
from .site_models import SITE_MODELS, site_model_availability, inference_command
from .site_model_runtime import inference_env, communicate_cancellable, on_gpu

class SiteModelTumorTool(BaseTool):
    MODEL_TYPE = ''

    @property
    def name(self):
        return self.MODEL_TYPE

    @property
    def description(self):
        return f"Segment {SITE_MODELS[self.MODEL_TYPE]['label']} using the supplied CT inference script."

    @property
    def input_schema(self):
        return {'type': 'object', 'properties': {'image_path': {'type': 'string'}}}

    @property
    def output_schema(self):
        return {'type': 'object', 'properties': {'ctv_array': {'type': 'array'}}}

    def _execute(self, **kwargs):
        try:
            image = kwargs.get('image')
            if image is None and kwargs.get('image_path'):
                image = sitk.ReadImage(str(kwargs['image_path']))
            if not isinstance(image, sitk.Image) or image.GetDimension() != 3 or image.GetNumberOfComponentsPerPixel() != 1:
                raise ValueError('This model requires a single-channel 3D CT.')
            if str(kwargs.get('image_modality') or 'CT').upper() not in ('CT', 'CTA', 'NCCT', 'CECT'):
                raise ValueError('This model supports CT only, not PET/MRI.')
            availability = site_model_availability(self.MODEL_TYPE)
            if not availability['available']:
                raise RuntimeError('; '.join(availability['missing']))
            return on_gpu(self.MODEL_TYPE, lambda gpu: self._infer(image, gpu))
        except OperationCancelled:
            raise
        except Exception as exc:
            return ToolResult(success=False, error=f'{self.name}: {exc}',
                              metadata={'code': 'site_model_inference_failed', 'tumor_type_used': self.name,
                                        'ctv_source': self.name})

    def _infer(self, image, gpu):
        spec = SITE_MODELS[self.MODEL_TYPE]
        with tempfile.TemporaryDirectory(prefix='brachybot-site-ctv-') as temp:
            directory = Path(temp)
            inputs, outputs = directory/'input', directory/'output'
            inputs.mkdir()
            outputs.mkdir()
            sitk.WriteImage(image, str(inputs/'case_0000.nii.gz'), True)
            command = inference_command(self.MODEL_TYPE, inputs, outputs, gpu)
            # Scripts may allocate temporary model packages; keep them under this request.
            env = inference_env()
            env['TMPDIR'] = temp
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env, start_new_session=True)
            try:
                output = communicate_cancellable(proc, 1200)
                raise_if_cancelled()
                path = outputs/'case.nii.gz'
                if proc.returncode or not path.is_file():
                    raise RuntimeError(f'Inference failed (exit={proc.returncode}, output={path.is_file()}): '
                                       + ' | '.join(output.splitlines()[-15:]))
                return self._result(image, sitk.ReadImage(str(path)), gpu)
            finally:
                NNUNetCascadeTumorTool._terminate_subprocess_group(proc)

    def _result(self, image, predicted, gpu):
        spec = SITE_MODELS[self.MODEL_TYPE]
        # Supplied scripts promise original geometry. Never silently resample a broken output.
        if (predicted.GetDimension() != 3 or predicted.GetSize() != image.GetSize()
            or any(not np.allclose(a, b, atol=1e-4, rtol=0) for a, b in (
                (predicted.GetSpacing(), image.GetSpacing()), (predicted.GetOrigin(), image.GetOrigin()),
                (predicted.GetDirection(), image.GetDirection())))):
            raise ValueError('Inference output does not match the input CT physical grid.')
        raw = sitk.GetArrayFromImage(predicted)
        if not np.isin(raw, [0, *spec['labels']]).all():
            raise ValueError('Inference output contains unexpected labels.')
        aligned = sitk.DICOMOrient(predicted, 'LPI')
        labels = sitk.GetArrayFromImage(aligned).astype(np.uint8)
        # Planning consumes binary target. Preserve primary/nodal labels separately for Data Tree.
        binary = (labels > 0).astype(np.uint8)
        mask = sitk.GetImageFromArray(binary)
        mask.CopyInformation(aligned)
        counts = {int(k): int(np.count_nonzero(labels == k)) for k in spec['labels']}
        return ToolResult(success=True, data=binary, message=f"{spec['label']} segmentation completed.", metadata={
            'ctv_mask': mask, 'ctv_array': binary, 'full_label_array': aligned,
            'label_map': dict(spec['labels']), 'label_counts': counts,
            'ctv_voxel_count': int(binary.sum()), 'ctv_volume_mm3': float(binary.sum()*np.prod(mask.GetSpacing())),
            'ctv_source': self.name, 'tumor_type_used': self.name, 'model_name': spec['label'],
            'checkpoint': str(spec['model']/spec['checkpoint']), 'model_validation': spec['validation'],
            'inference_precision': spec['precision'], 'inference_script': str(spec['script']),
            'inference_gpu': f'cuda:{gpu}', 'image_modality': 'CT', 'ct_phase': spec.get('ct_phase'),
            'source_labels_exposed': list(spec['labels'].values()), 'output_orientation': 'LPI',
            'target_semantics': 'primary_and_nodal_gtv_union' if len(counts) > 1 else 'lung_tumor_only',
        })

class VistaLungTumorTool(SiteModelTumorTool):
    MODEL_TYPE = 'vista3d_lung_tumor'

class HeadNeckGTVTool(SiteModelTumorTool):
    MODEL_TYPE = 'nnunet_head_neck_gtv'

class NasopharynxNCCTTool(SiteModelTumorTool):
    MODEL_TYPE = 'nnunet_nasopharynx_ncct'

class NasopharynxCECTTool(SiteModelTumorTool):
    MODEL_TYPE = 'nnunet_nasopharynx_cect'
