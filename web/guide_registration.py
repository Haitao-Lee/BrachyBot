"""Owned durable registration jobs, reviewed pose publication and overlay data."""
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import multiprocessing
import os
from pathlib import Path
import sqlite3
import threading
import time
from types import SimpleNamespace
from uuid import UUID

import numpy as np

from web.guide_placement import GuidePlacementError, RigidTransform, _digest, _basis
from web.guide_service import GuidePlacementService
from utils.guide_registration_cpu import RegistrationLimits, image_payload, registration_process


TERMINAL = frozenset({'completed', 'failed', 'cancelled', 'interrupted', 'timed_out', 'stale'})


def _now():
    return datetime.now(timezone.utc).isoformat()


def owned_service(store, owner, session_id):
    return GuidePlacementService(SimpleNamespace(_workspace_store=store,
        config={'_workspace_owner_id': owner, '_workspace_session_id': session_id}))


def _process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


class GuideRegistrationJobs:
    """One active job per target; at most two executing children per app.

    The child process owns only immutable captured arrays, has no store, and
    cannot publish. Cancellation and publication are serialized by the job
    journal transaction. Restart never repeats an optimizer automatically.
    """

    def __init__(self, store, *, limits=None):
        self.store = store
        self.limits = limits or RegistrationLimits()
        self.slots = threading.BoundedSemaphore(2)
        self.lock = threading.RLock()
        self.threads = {}

    @contextmanager
    def database(self, owner, session_id, target_id):
        self.store.require_local_session(owner, session_id)
        self.store._timepoint_record(self.store.list_timepoints(owner, session_id), target_id)
        root = self.store.workspace_root(owner, session_id, create=True)
        directory = root / 'timepoints' / target_id / 'guide-registration'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = directory / 'jobs.sqlite3'
        connection = sqlite3.connect(path, timeout=10.)
        connection.row_factory = sqlite3.Row
        connection.execute('PRAGMA journal_mode=DELETE')
        connection.execute('CREATE TABLE IF NOT EXISTS jobs (request_id TEXT PRIMARY KEY, payload_hash TEXT NOT NULL, status TEXT NOT NULL, record TEXT NOT NULL, owner_pid INTEGER NOT NULL)')
        try:
            yield connection
        finally:
            connection.close()

    @staticmethod
    def _read(connection, request_id):
        row = connection.execute('SELECT record FROM jobs WHERE request_id=?', (request_id,)).fetchone()
        if row is None:
            raise GuidePlacementError('The registration job is unavailable in this owned target')
        return json.loads(row['record'])

    @staticmethod
    def _write(connection, record):
        connection.execute('UPDATE jobs SET status=?, record=? WHERE request_id=?',
            (record['status'], json.dumps(record, allow_nan=False, separators=(',', ':')), record['job_id']))

    def _recover(self, connection, service, target_id):
        rows = connection.execute("SELECT * FROM jobs WHERE status NOT IN ('completed','failed','cancelled','interrupted','timed_out','stale')").fetchall()
        snapshot = None
        for row in rows:
            if _process_alive(row['owner_pid']):
                continue
            record = json.loads(row['record'])
            if snapshot is None:
                snapshot = service._snapshot(target_id)
            candidates = service._results(snapshot).get('guide_placement_candidates') or {}
            committed = next((candidate for candidate in candidates.values()
                if candidate.get('evidence', {}).get('registration_job_id') == record['job_id']), None)
            record.update(status='completed' if committed else 'interrupted', updated_at_utc=_now(),
                restart_recovered=True, auto_resumed=False)
            if committed:
                record['placement_id'] = committed['placement_id']
                record['saved_state_revision'] = snapshot['timepoint_state_revision']
            self._write(connection, record)

    def start(self, owner, session_id, target_id, data):
        allowed = {'request_id', 'source_timepoint_id', 'guide_version', 'manufactured_guide_id',
                   'expected_state_revision', 'method', 'guide_roi_index_xyz', 'guide_threshold_hu',
                   'source_roi_index_xyz', 'target_roi_index_xyz', 'initial_matrix',
                   'max_residual_mm', 'ambiguity_margin_mm','expected_clinical_revision'}
        if not isinstance(data, dict) or set(data) - allowed:
            raise GuidePlacementError('Unknown registration request fields')
        request_id = str(UUID(data.get('request_id', '')))
        if data.get('method') not in {'auto', 'visible_guide', 'image_rigid'}:
            raise GuidePlacementError('Choose auto, visible_guide or image_rigid registration')
        for key in ('max_residual_mm', 'ambiguity_margin_mm'):
            value = data.get(key)
            if type(value) not in {int, float} or not np.isfinite(value) or not (0 < value <= 20 if key == 'max_residual_mm' else 0 <= value <= 20):
                raise GuidePlacementError('Provide explicit bounded fit and ambiguity review thresholds')
        if data.get('guide_roi_index_xyz') is not None and type(data.get('guide_threshold_hu')) not in {int, float}:
            raise GuidePlacementError('Selected visible guide reconstruction requires a material threshold')
        if data.get('initial_matrix') is not None:
            RigidTransform.from_matrix(data['initial_matrix'])
        service = owned_service(self.store, owner, session_id)
        signature = _digest(data)
        # Idempotent retry does not recapture a newer target or run twice.
        with self.lock, self.database(owner, session_id, target_id) as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._recover(connection, service, target_id)
            row = connection.execute('SELECT payload_hash,record FROM jobs WHERE request_id=?', (request_id,)).fetchone()
            if row:
                if row['payload_hash'] != signature:
                    raise GuidePlacementError('Registration request ID was reused with different inputs')
                connection.commit()
                return json.loads(row['record'])
            if connection.execute("SELECT count(*) FROM jobs WHERE status NOT IN ('completed','failed','cancelled','interrupted','timed_out','stale')").fetchone()[0]:
                raise GuidePlacementError('This target already has an active registration job')
            if connection.execute('SELECT count(*) FROM jobs').fetchone()[0] >= 64:
                raise GuidePlacementError('Registration journal retention limit reached; retain/export existing jobs first')
            if sum(thread.is_alive() for thread in self.threads.values()) >= 16:
                raise GuidePlacementError('The bounded registration queue is full')
            context, source, _, guide, target_image, binding = service.capture_registration(
                source_timepoint_id=data.get('source_timepoint_id'), target_timepoint_id=target_id,
                guide_version=data.get('guide_version'), expected_state_revision=data.get('expected_state_revision'),
                manufactured_guide_id=data.get('manufactured_guide_id'),
                expected_clinical_revision=data.get('expected_clinical_revision'))
            payload = {'guide': guide, 'target': image_payload(target_image), 'request': data, 'limits': asdict(self.limits)}
            if data['method'] == 'image_rigid' or (data['method'] == 'auto' and data.get('guide_roi_index_xyz') is None):
                with self.store._case_guard(owner, session_id):
                    source_image, provenance = service._guide_source_image(source, guide)
                binding['source_image'] = provenance['image']
                binding['source_provenance'] = provenance
                payload['source'] = image_payload(source_image)
            record = {'job_id': request_id, 'session_id': session_id, 'timepoint_id': target_id,
                'source_timepoint_id': data['source_timepoint_id'], 'guide_version': data['guide_version'],
                'request': data, 'input_readset': binding, 'status': 'queued', 'cancel_requested': False,
                'created_at_utc': _now(), 'updated_at_utc': _now(), 'clinical_use_approved': False,
                'limits': asdict(self.limits), 'auto_resumed': False}
            # The journal is bounded to 64 small JSON rows, and remains inside
            # the owned Session tree for export/quota accounting.
            with self.store._quota_commit_lock(owner):
                path = Path(connection.execute('PRAGMA database_list').fetchone()[2])
                self.store._ensure_replacement_capacity(owner, path, path.stat().st_size + len(json.dumps(record)) * 3 + 16384)
                connection.execute('INSERT INTO jobs VALUES (?,?,?,?,?)',
                    (request_id, signature, 'queued', json.dumps(record, allow_nan=False), os.getpid()))
                connection.commit()
                self.store._invalidate_storage_usage(owner)
            thread = threading.Thread(target=self._run, args=(owner, session_id, target_id, request_id, service, context, binding, payload),
                                      name='guide-registration-' + request_id[:8], daemon=True)
            self.threads[(owner, session_id, target_id, request_id)] = thread
            thread.start()
            return record

    def _update(self, owner, sid, target, rid, **updates):
        with self.database(owner, sid, target) as connection:
            connection.execute('BEGIN IMMEDIATE')
            record = self._read(connection, rid)
            if record['status'] not in TERMINAL:
                record.update(updates, updated_at_utc=_now())
                self._write(connection, record)
            connection.commit()
            return record

    def get(self, owner, sid, target, rid):
        rid = str(UUID(rid))
        with self.database(owner, sid, target) as connection:
            connection.execute('BEGIN IMMEDIATE')
            self._recover(connection, owned_service(self.store, owner, sid), target)
            record = self._read(connection, rid)
            connection.commit()
            return record

    def cancel(self, owner, sid, target, rid):
        return self._update(owner, sid, target, str(UUID(rid)), cancel_requested=True)

    def _run(self, owner, sid, target, rid, service, context, binding, payload):
        process = None
        receiver = None
        started = time.monotonic()
        acquired = False
        try:
            while not acquired:
                if self.get(owner, sid, target, rid)['cancel_requested']:
                    self._update(owner, sid, target, rid, status='cancelled'); return
                if time.monotonic() - started > self.limits.max_seconds:
                    self._update(owner, sid, target, rid, status='timed_out'); return
                acquired = self.slots.acquire(timeout=.1)
            self._update(owner, sid, target, rid, status='running')
            spawn = multiprocessing.get_context('spawn')
            receiver, sender = spawn.Pipe(duplex=False)
            process = spawn.Process(target=registration_process, args=(sender, payload), daemon=True)
            process.start(); sender.close()
            answer = None
            while True:
                if self.get(owner, sid, target, rid)['cancel_requested']:
                    self._update(owner, sid, target, rid, status='cancelled'); return
                if time.monotonic() - started > self.limits.max_seconds + 5:
                    self._update(owner, sid, target, rid, status='timed_out'); return
                if receiver.poll(.1):
                    try:
                        answer = receiver.recv()
                    except EOFError as exc:
                        raise GuidePlacementError('Registration child exited without a result') from exc
                    break
                if not process.is_alive():
                    raise GuidePlacementError('Registration child exited without a result')
            if not answer['success']:
                raise GuidePlacementError(answer['error'])
            with self.database(owner, sid, target) as connection:
                connection.execute('BEGIN IMMEDIATE')
                record = self._read(connection, rid)
                if record['cancel_requested']:
                    record.update(status='cancelled', updated_at_utc=_now())
                else:
                    candidate, revision = service.publish_registration(answer['result'], binding, context, job_id=rid)
                    record.update(status='completed', placement_id=candidate['placement_id'], saved_state_revision=revision,
                        candidate_sha256=candidate['candidate_sha256'], qc=candidate['qc'], updated_at_utc=_now())
                self._write(connection, record); connection.commit()
        except Exception as exc:
            try:
                from web.timepoints import TimepointConflict
                self._update(owner, sid, target, rid, status='stale' if isinstance(exc, TimepointConflict) else 'failed',
                    error=str(exc)[:1000], error_code=getattr(exc, 'error_code', None))
            except Exception:
                # A deleted/archived Session remains unpublishable; restart
                # recovery exposes interrupted status if it is restored.
                pass
        finally:
            if receiver:
                receiver.close()
            if process:
                if process.is_alive():
                    process.terminate()
                process.join(timeout=2.)
            if acquired:
                self.slots.release()


def guide_overlay(service, *, source_timepoint_id, target_timepoint_id, guide_version, placement_id):
    """Actual CT samples and original transformed triangles for 2D/3D review."""
    import SimpleITK as sitk
    from utils.guide_registration_cpu import reduced_image

    source, target, guide, candidate = service.current_candidate(source_timepoint_id=source_timepoint_id,
        target_timepoint_id=target_timepoint_id, guide_version=guide_version, placement_id=placement_id)
    matrix = RigidTransform.from_matrix(candidate['matrix'])
    vertices = matrix.points(guide['vertices'])
    faces = np.asarray(guide['faces'], dtype=int)
    if len(faces) > 500_000:
        raise GuidePlacementError('Guide review mesh exceeds the bounded overlay limit')
    current = reduced_image(service._target_ct_image(target), RegistrationLimits(max_edge=96))
    array = sitk.GetArrayViewFromImage(current)
    source_array = None
    if candidate.get('source_to_target_matrix'):
        inverse = np.linalg.inv(np.asarray(candidate['source_to_target_matrix']))
        pull = sitk.AffineTransform(3); pull.SetMatrix(inverse[:3, :3].ravel().tolist()); pull.SetTranslation(inverse[:3, 3].tolist())
        original, provenance = service._check_source_image(source, guide, candidate['evidence']['input_readset'])
        source_image = reduced_image(original, RegistrationLimits(max_edge=96))
        registered_source = sitk.Resample(source_image, current, pull, sitk.sitkLinear, -1000., sitk.sitkFloat32)
        source_array = sitk.GetArrayFromImage(registered_source)
    # Intersections use the actual image grid, including oblique direction.
    direction = np.asarray(current.GetDirection()).reshape(3, 3)
    indices = ((vertices - current.GetOrigin()) @ direction) / current.GetSpacing()
    center = np.clip(np.round(indices.mean(axis=0)).astype(int), 0, np.asarray(current.GetSize()) - 1)
    slices = []
    triangles = indices[faces]
    for axis, name in ((0, 'sagittal'), (1, 'coronal'), (2, 'axial')):
        plane = int(center[axis])
        dimensions = [i for i in range(3) if i != axis]
        crossing = triangles[(triangles[:, :, axis].min(axis=1) <= plane) & (triangles[:, :, axis].max(axis=1) >= plane)]
        segments = []
        for triangle in crossing:
            points = []
            for a, b in zip(triangle, np.roll(triangle, -1, axis=0)):
                denominator = b[axis] - a[axis]
                if abs(denominator) > 1e-10 and (a[axis] - plane) * (b[axis] - plane) <= 0:
                    point = a + (b - a) * ((plane - a[axis]) / denominator)
                    points.append(point[dimensions].tolist())
            if len(points) >= 2:
                segments.append(points[:2])
        pixels = np.take(array, plane, axis=2 - axis)
        slices.append({'name': name, 'axis_xyz': axis, 'index': plane, 'width': pixels.shape[1],
                       'height': pixels.shape[0], 'ct_hu': pixels.tolist(), 'guide_segments_pixels': segments,
                       'registered_source_hu': np.take(source_array, plane, axis=2 - axis).tolist() if source_array is not None else None})
    from skimage.measure import marching_cubes
    body_surface = None
    body = array > -300
    if np.any(body) and not np.all(body):
        body_vertices, body_faces, _, _ = marching_cubes(body.astype(np.uint8), level=.5, step_size=2)
        body_vertices = (body_vertices[:, ::-1] * current.GetSpacing()) @ direction.T + current.GetOrigin()
        body_surface = {'vertices_lps_mm': body_vertices.tolist(), 'faces': body_faces.tolist(),
                        'evidence': 'current_ct_threshold_surface_for_review_display_only', 'threshold_hu': -300}
    bores = []
    for bore in guide['bore_manifest']['bores']:
        record = {'bore_id': bore['bore_id'], 'kind': bore['kind'], 'eligible': bore['eligible'],
                  'reason': bore.get('reason'), 'guiding_length_mm': bore.get('guiding_length_mm'),
                  'minimum_wall_lower_bound_mm': bore.get('minimum_wall_lower_bound_mm'),
                  'minimum_interbore_wall_mm': bore.get('minimum_interbore_wall_mm')}
        if bore['eligible']:
            record['centerline_lps_mm'] = matrix.points(bore['centerline_local_mm']).tolist()
            record['axis_lps'] = matrix.directions(bore['axis_local']).tolist()
        bores.append(record)
    return {'session_id': service.session_id, 'timepoint_id': target_timepoint_id,
            'source_timepoint_id': source_timepoint_id, 'state_revision': target['timepoint_state_revision'],
            'clinical_revision':target['timepoint_clinical_revision'],
            'target_image': candidate['target_image'], 'placement_id': placement_id,
            'candidate_sha256': candidate['candidate_sha256'], 'review_state': candidate['review_state'],
            'matrix': candidate['matrix'], 'vertices_lps_mm': vertices.tolist(), 'faces': faces.tolist(),
            'bores': bores, 'slices': slices, 'observed_surface': candidate.get('observed_surface'),
            'current_body_surface': body_surface,
            'source_to_target_matrix': candidate.get('source_to_target_matrix'), 'qc': candidate['qc'],
            'source_provenance': candidate.get('evidence', {}).get('input_readset', {}).get('source_provenance'),
            'coordinate_system': 'physical_lps_mm', 'guide_deformed': False, 'clinical_use_approved': False}
