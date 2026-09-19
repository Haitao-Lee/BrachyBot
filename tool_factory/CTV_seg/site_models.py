"""Deployment contracts for the supplied CT inference scripts (no model reimplementation)."""
from pathlib import Path
import os
from functools import lru_cache
import json
import subprocess

ROOT = Path(
    os.environ.get("BRACHYBOT_DEPLOY_ROOT") or Path(__file__).resolve().parents[3]
)
SITE_MODELS = {
    'vista3d_lung_tumor': dict(
        site='lung', label='Lung tumor', script=ROOT/'lung_tumor_seg/infer_lung_vista.py',
        model=ROOT/'lung_tumor_seg/trained_models/vista3d_lung',
        labels={1: 'lung tumor'}, precision='supplied VISTA-3D default',
        checkpoint='vista3d_pretrained_model/model.safetensors',
        args=['--label_prompt', '23'], modality='CT',
        validation={'dataset_dice': 0.728, 'case_mean_dice': 0.713, 'source': 'user-provided MSD Task06 evaluation; foundation model, not fine-tuned'}),
    'nnunet_head_neck_gtv': dict(
        site='head_neck', label='Head and neck GTV (CT)', script=ROOT/'headneck_tumor_seg/infer_headneck.py',
        model=ROOT/'headneck_tumor_seg/data/nnUNet_results/Dataset510_HECKTOR_CT/nnUNetTrainerMax500__nnUNetPlans__3d_fullres/best_model',
        labels={1: 'GTVp (primary)', 2: 'GTVn (nodal)'}, precision='fp32',
        checkpoint='checkpoint_final.pth', args=['--checkpoint', 'final'], modality='CT',
        validation={'gtvp_dice': 0.599, 'gtvn_dice': 0.516, 'source': 'user-provided best fold 1 evaluation'}),
    **{f'nnunet_nasopharynx_{phase}': dict(
        site='nasopharynx', label=f'Nasopharynx GTV ({phase.upper()})',
        script=ROOT/'nasopharynx_tumor_seg/infer_nasopharynx.py',
        model=ROOT/f'nasopharynx_tumor_seg/trained_models/nasopharynx_cancer_seg_{phase}',
        labels={1: 'GTVnx (primary)', 2: 'GTVnd (nodal)'}, precision='fp16',
        checkpoint='checkpoint_best.pth', args=[], modality='CT', ct_phase=phase,
        validation={'source': 'user-provided five-fold CV; deployed package is best fold 3',
                    'cv_gtvnx_dice': nx, 'cv_gtvnd_dice': nd})
       for phase, nx, nd in [('ncct', 0.786, 0.678), ('cect', 0.781, 0.717)]},
}

def runtime_python():
    return os.environ.get('BRACHYBOT_SITE_MODEL_PYTHON', '/opt/miniconda3/bin/python')

@lru_cache(maxsize=4)
def _runtime_probe(python):
    # Run with the same sanitized environment as inference, without loading CUDA.
    from .site_model_runtime import inference_env
    code = ('import os,json,importlib.metadata as m; '
            'print(json.dumps({"user":__import__("pwd").getpwuid(os.getuid()).pw_name,'
            '"versions":{p:m.version(p) for p in ["torch","monai","nnunetv2","transformers","SimpleITK"]}}))')
    try:
        result = subprocess.run([python, '-c', code], env=inference_env(), capture_output=True, text=True, timeout=15, check=True)
        return json.loads(result.stdout.strip().splitlines()[-1])
    except Exception as exc:
        return {'error': f'Runtime dependency probe failed: {type(exc).__name__}'}

def site_model_availability(model_type):
    spec = SITE_MODELS[model_type]
    model = Path(spec['model'])
    required = [Path(spec['script']), model/spec['checkpoint']]
    required += ([model/'vista3d_pretrained_model/config.json', model/'hugging_face_pipeline.py',
                  model/'vista3d_pipeline.py', model/'vista3d_model.py', model/'vista3d_config.py']
                 if model_type == 'vista3d_lung_tumor' else [model/'plans.json', model/'dataset.json'])
    missing = [str(p) for p in required if not p.is_file() or not p.stat().st_size]
    runtime = _runtime_probe(runtime_python())
    if runtime.get('error'):
        missing.append(runtime['error'])
    elif runtime.get('user') != 'brachybot':
        missing.append('Inference must run as brachybot (dependencies are in the brachybot user site).')
    if model_type == 'vista3d_lung_tumor' and runtime.get('versions', {}).get('transformers') != '4.46.3':
        missing.append('VISTA-3D requires installed transformers==4.46.3; do not upgrade.')
    return dict(available=not missing, missing=missing, python=runtime_python(),
                script=str(spec['script']), model_root=str(model), runtime=runtime)

def inference_command(model_type, input_dir, output_dir, gpu):
    spec = SITE_MODELS[model_type]
    return [runtime_python(), str(spec['script']), '--input', str(input_dir),
            '--output', str(output_dir), '--gpu', str(gpu),
            '--model_dir' if model_type == 'vista3d_lung_tumor' else '--model',
            str(spec['model']), *spec['args']]
